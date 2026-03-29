#!/usr/bin/env python3
# ==============================================================================
# PROJECT: GRUB Fixer V22 - GUI Edition (Wayland/X11 Compatible)
# AUTHOR: ahmed-x86
# DESCRIPTION: A complete PyQt6 rewrite containing ALL 22 features of the CLI script.
# ==============================================================================

import sys
import os
import time
import json
import subprocess
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QTextEdit, QLabel, 
                             QInputDialog, QLineEdit, QMessageBox, QProgressBar)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

class SystemWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, float)

    def __init__(self, task_type, **kwargs):
        super().__init__()
        self.task_type = task_type
        self.kwargs = kwargs
        self.start_time = 0

    def run_cmd(self, cmd, use_root=False, input_data=None):
        if use_root:
            cmd = ['pkexec'] + cmd
        
        self.log_signal.emit(f"-> Executing: {' '.join(cmd)}")
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if input_data else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            if input_data:
                stdout, _ = process.communicate(input=input_data)
                for line in stdout.splitlines():
                    self.log_signal.emit("  " + line)
            else:
                for line in process.stdout:
                    self.log_signal.emit("  " + line.strip())
            
            process.wait()
            return process.returncode == 0
        except Exception as e:
            self.log_signal.emit(f"[-] Error: {str(e)}")
            return False

    def run(self):
        self.start_time = time.time()
        success = False
        
        if self.task_type == "full_repair":
            success = self.execute_full_repair()
            
        execution_time = time.time() - self.start_time
        self.finished_signal.emit(success, execution_time)

    def execute_full_repair(self):
        env_mode = self.kwargs.get('env_mode')
        btrfs_mapping = self.kwargs.get('btrfs_mapping', {})
        root_part = self.kwargs.get('root_part')
        efi_part = self.kwargs.get('efi_part')
        efi_mount_path = self.kwargs.get('efi_mount_path', '/boot/efi')
        is_local = (env_mode == "host")

        self.log_signal.emit("\n[*] Starting Advanced GRUB Repair Engine (V1-V22)...")

        if not root_part:
            self.log_signal.emit("[-] CRITICAL ERROR: No Root partition selected.")
            return False

        if not is_local:
            self.run_cmd(['umount', '-R', '/mnt'], use_root=True)
            
            self.log_signal.emit("[*] Mounting partitions...")
            if btrfs_mapping:
                for subvol, mnt in btrfs_mapping.items():
                    target = f"/mnt{mnt}" if mnt != "/" else "/mnt"
                    self.run_cmd(['mkdir', '-p', target], use_root=True)
                    self.run_cmd(['mount', '-o', f'subvol={subvol}', f'/dev/{root_part}', target], use_root=True)
            else:
                self.run_cmd(['mount', f'/dev/{root_part}', '/mnt'], use_root=True)

            if efi_part:
                self.run_cmd(['mkdir', '-p', f'/mnt{efi_mount_path}'], use_root=True)
                self.run_cmd(['mount', f'/dev/{efi_part}', f'/mnt{efi_mount_path}'], use_root=True)

            self.log_signal.emit("[*] Preparing bind mounts for Chroot...")
            for d in ['dev', 'proc', 'sys', 'run']:
                self.run_cmd(['mount', '--bind', f'/{d}', f'/mnt/{d}'], use_root=True)
            self.run_cmd(['cp', '/etc/resolv.conf', '/mnt/etc/resolv.conf'], use_root=True)

        # الحفاظ على الهيكل الكامل للسكربت الأصلي (V12, V15, V19, V21, V22)
        payload = f"""#!/bin/bash
set -e
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

echo "[*] System Health Check & OS Detection..."
OS_NAME="Linux"
GRUB_CMD="grub-install"
MKCONFIG_CMD="grub-mkconfig"
CFG_PATH="/boot/grub/grub.cfg"

if [ -f "/etc/os-release" ]; then
    source /etc/os-release
    OS_NAME=$NAME
    if [[ "$ID" =~ (fedora|rhel|centos|rocky|almalinux) ]]; then
        GRUB_CMD="grub2-install"
        MKCONFIG_CMD="grub2-mkconfig"
        CFG_PATH="/boot/grub2/grub.cfg"
        mkdir -p /boot/grub2
    fi
fi

# V22: Secure Boot Detection
SECURE_BOOT=0
if command -v mokutil &> /dev/null && mokutil --sb-state 2>/dev/null | grep -q "SecureBoot enabled"; then
    SECURE_BOOT=1
    echo "[!] V22: Secure Boot Detected (ENABLED)"
fi

# V12 & V15: Dynamic Bitness and Target Extraction
if [ -d "/sys/firmware/efi" ]; then
    EFI_TARGET="x86_64-efi"
    if [ -f "/sys/firmware/efi/fw_platform_size" ]; then
        EFI_SIZE=$(cat /sys/firmware/efi/fw_platform_size)
        if [ "$EFI_SIZE" == "32" ]; then
            EFI_TARGET="i386-efi"
            echo "[!] WARNING: 32-bit UEFI architecture detected!"
        fi
    fi
    
    echo "-> Installing GRUB for UEFI ($EFI_TARGET)..."
    if [ "$SECURE_BOOT" -eq 1 ] && [[ "$ID" =~ (debian|ubuntu|pop) ]]; then
        $GRUB_CMD --target=$EFI_TARGET --efi-directory={efi_mount_path} --bootloader-id="$OS_NAME" --uefi-secure-boot
    else
        $GRUB_CMD --target=$EFI_TARGET --efi-directory={efi_mount_path} --bootloader-id="$OS_NAME" --removable
    fi
else
    echo "-> Installing GRUB for Legacy BIOS (i386-pc)..."
    ROOT_DEV=$(findmnt -n -o SOURCE / | head -n 1)
    PARENT_1=$(lsblk -no PKNAME "$ROOT_DEV" | head -n 1)
    PARENT_2=$(lsblk -no PKNAME "/dev/$PARENT_1" 2>/dev/null | head -n 1)
    
    if [ -n "$PARENT_2" ]; then
        TARGET_DISK="/dev/$PARENT_2"
    elif [ -n "$PARENT_1" ]; then
        TARGET_DISK="/dev/$PARENT_1"
    else
        TARGET_DISK="$ROOT_DEV"
    fi
    
    $GRUB_CMD --target=i386-pc "$TARGET_DISK"
fi

# V13 & V21: OS Prober and LUKS configuration
sed -i '/GRUB_DISABLE_OS_PROBER/d' /etc/default/grub || true
echo "GRUB_DISABLE_OS_PROBER=false" >> /etc/default/grub
sed -i '/GRUB_ENABLE_CRYPTODISK/d' /etc/default/grub || true
echo "GRUB_ENABLE_CRYPTODISK=y" >> /etc/default/grub

echo "-> Generating GRUB configuration..."
$MKCONFIG_CMD -o $CFG_PATH

# V22: MOK Enrollment
if [ "$SECURE_BOOT" -eq 1 ]; then
    if command -v mokutil &> /dev/null && [ -f /var/lib/shim-signed/mok/MOK.der ]; then
        echo "-> Enrolling MOK (OTP: 1234)..."
        printf '1234\\n1234\\n' | mokutil --import /var/lib/shim-signed/mok/MOK.der || true
    elif command -v sbctl &> /dev/null; then
        echo "-> Arch Linux sbctl detected. Signing GRUB..."
        sbctl sign -s {efi_mount_path}/EFI/"$OS_NAME"/grubx64.efi || true
    fi
fi
echo "[+] Operations inside target system completed successfully."
"""
        
        if is_local:
            with open('/tmp/grub_payload.sh', 'w') as f:
                f.write(payload)
            self.run_cmd(['chmod', '+x', '/tmp/grub_payload.sh'], use_root=True)
            res = self.run_cmd(['/bin/bash', '/tmp/grub_payload.sh'], use_root=True)
        else:
            self.run_cmd(['mkdir', '-p', '/mnt/tmp'], use_root=True)
            with open('/tmp/grub_payload.sh', 'w') as f:
                f.write(payload)
            self.run_cmd(['cp', '/tmp/grub_payload.sh', '/mnt/tmp/grub_payload.sh'], use_root=True)
            self.run_cmd(['chmod', '+x', '/mnt/tmp/grub_payload.sh'], use_root=True)
            res = self.run_cmd(['chroot', '/mnt', '/bin/bash', '/tmp/grub_payload.sh'], use_root=True)
            
            self.log_signal.emit("[*] Unmounting filesystems...")
            self.run_cmd(['umount', '-R', '/mnt'], use_root=True)
            
        return res

class GrubFixerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GRUB Fixer V22 - Ultimate Edition")
        self.resize(950, 750)
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e2e; color: #cdd6f4; }
            QTextEdit { background-color: #181825; color: #a6e3a1; font-family: monospace; border: 1px solid #313244; }
            QPushButton { background-color: #89b4fa; color: #11111b; font-weight: bold; padding: 10px; border-radius: 5px; margin: 3px; }
            QPushButton:hover { background-color: #b4befe; }
            QPushButton:disabled { background-color: #45475a; color: #a6adc8; }
            QLabel { color: #cdd6f4; font-size: 14px; font-weight: bold; }
        """)

        self.system_data = {
            'env_mode': 'live', 
            'has_luks': False,
            'root_part': '',
            'efi_part': '',
            'efi_mount_path': '/boot/efi',
            'btrfs_mapping': {}
        }

        self.init_ui()
        self.detect_environment()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        header = QLabel("GRUB Fixer V22 - 3-Tier Execution Mode")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("font-size: 20px; color: #f38ba8; margin-bottom: 10px;")
        layout.addWidget(header)

        btn_layout = QHBoxLayout()
        
        self.btn_unlock_luks = QPushButton("1. Unlock LUKS")
        self.btn_unlock_luks.clicked.connect(self.handle_luks)
        btn_layout.addWidget(self.btn_unlock_luks)

        self.btn_scan = QPushButton("2. Auto-Detect (Tier 2)")
        self.btn_scan.clicked.connect(self.scan_partitions)
        btn_layout.addWidget(self.btn_scan)

        # إضافة الزر الخاص بالـ Tier 3 (الإدخال اليدوي)
        self.btn_manual = QPushButton("OR: Manual Mode (Tier 3)")
        self.btn_manual.setStyleSheet("background-color: #f9e2af;")
        self.btn_manual.clicked.connect(self.manual_partitions)
        btn_layout.addWidget(self.btn_manual)

        self.btn_btrfs = QPushButton("3. Setup Btrfs")
        self.btn_btrfs.clicked.connect(self.handle_btrfs)
        self.btn_btrfs.setEnabled(False) 
        btn_layout.addWidget(self.btn_btrfs)

        self.btn_repair = QPushButton("4. Start Repair 🚀")
        self.btn_repair.setStyleSheet("background-color: #a6e3a1;")
        self.btn_repair.clicked.connect(self.start_repair)
        self.btn_repair.setEnabled(False)
        btn_layout.addWidget(self.btn_repair)

        layout.addLayout(btn_layout)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("QProgressBar::chunk { background-color: #a6e3a1; }")
        layout.addWidget(self.progress)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        layout.addWidget(self.console)

    def log(self, message):
        self.console.append(message)
        scrollbar = self.console.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def detect_environment(self):
        self.log("==========================================")
        self.log("GRUB Fixer V22: Full Capabilities Enabled")
        self.log("Supports: x86_64-efi, i386-efi (32-bit), i386-pc (Legacy)")
        self.log("Tiers: Auto-Detect (Tier 2) & Manual Input (Tier 3)")
        self.log("==========================================\n")
        
        # Tier 1 Logic: Local /etc/fstab check
        if os.path.isfile("/etc/fstab"):
            self.log("[+] V11 Tier 1: Local /etc/fstab detected. Environment set to HOST.")
            self.system_data['env_mode'] = 'host'
            self.btn_scan.setEnabled(False)
            self.btn_manual.setEnabled(False)
            self.btn_btrfs.setEnabled(False)
            self.btn_repair.setEnabled(True)
            self.system_data['root_part'] = "In-Situ-Mode" # Placeholder to pass validation
        else:
            self.system_data['env_mode'] = 'live'
            self.log("[*] V17: Live Environment Detected. Proceeding with Tier 2/3.")

    def handle_luks(self):
        self.log("\n[*] Checking for LUKS Encrypted partitions...")
        try:
            result = subprocess.run(['lsblk', '-J', '-l', '-o', 'NAME,FSTYPE'], capture_output=True, text=True)
            data = json.loads(result.stdout)
            luks_parts = [d['name'] for d in data.get('blockdevices', []) if d.get('fstype') == 'crypto_LUKS']
            
            if not luks_parts:
                self.log("[i] No LUKS encrypted partitions found.")
                return

            self.system_data['has_luks'] = True
            for part in luks_parts:
                pwd, ok = QInputDialog.getText(self, "LUKS Decryption", 
                                              f"Enter password for /dev/{part}:", 
                                              QLineEdit.EchoMode.Password)
                if ok and pwd:
                    self.log(f"-> Attempting to unlock /dev/{part}...")
                    mapper_name = f"crypt_{part}"
                    cmd = f"echo -n '{pwd}' | pkexec cryptsetup luksOpen /dev/{part} {mapper_name} -"
                    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    if res.returncode == 0:
                        self.log(f"  [+] Decrypted successfully to /dev/mapper/{mapper_name}")
                        subprocess.run(['pkexec', 'vgchange', '-ay'])
                    else:
                        self.log(f"  [-] Decryption failed.")
        except Exception as e:
            self.log(f"[-] Error: {e}")

    def scan_partitions(self):
        self.log("\n[*] Tier 2: Smart Auto-Detecting Partitions...")
        try:
            result = subprocess.run(['lsblk', '-J', '-l', '-o', 'NAME,FSTYPE,SIZE'], capture_output=True, text=True)
            data = json.loads(result.stdout)
            
            linux_parts = [d for d in data.get('blockdevices', []) if d.get('fstype') in ['ext4', 'btrfs', 'xfs']]
            efi_parts = [d for d in data.get('blockdevices', []) if d.get('fstype') == 'vfat']

            if not linux_parts:
                self.log("[-] No mountable Linux partitions found! Try Manual Mode.")
                return

            suggested_root = linux_parts[0]['name']
            self.system_data['root_part'] = suggested_root
            root_fstype = linux_parts[0]['fstype']
            
            self.log(f"[+] Root Selected: /dev/{suggested_root} ({root_fstype})")

            if efi_parts:
                self.system_data['efi_part'] = efi_parts[0]['name']
                self.log(f"[+] EFI Selected: /dev/{self.system_data['efi_part']}")
                
                # V10 feature: Ask for custom EFI mount point
                mnt_path, ok = QInputDialog.getText(self, "EFI Mount Path", 
                                                    "Where does your system mount the EFI partition?", 
                                                    text="/boot/efi")
                if ok and mnt_path:
                    self.system_data['efi_mount_path'] = mnt_path
            else:
                self.log("[i] No EFI partition detected. Assuming Legacy BIOS.")

            if root_fstype == 'btrfs':
                self.log("[!] Btrfs detected. Click '3. Setup Btrfs'.")
                self.btn_btrfs.setEnabled(True)
                self.btn_repair.setEnabled(False)
            else:
                self.btn_btrfs.setEnabled(False)
                self.btn_repair.setEnabled(True)
                self.log("\n[+] Ready for Repair.")

        except Exception as e:
            self.log(f"[-] Auto-Detect Failed: {e}")

    def manual_partitions(self):
        self.log("\n[*] Tier 3: Manual Input Mode Activated...")
        
        root_part, ok1 = QInputDialog.getText(self, "Tier 3: Manual Mode", "Enter Root (/) partition name (e.g., sda3 or mapper/crypt_sda3):")
        if ok1 and root_part:
            self.system_data['root_part'] = root_part
            self.log(f"[+] Manual Root Selected: /dev/{root_part}")
            
            efi_part, ok2 = QInputDialog.getText(self, "Tier 3: Manual Mode", "Enter EFI partition name (Leave empty for Legacy BIOS):")
            if ok2 and efi_part:
                self.system_data['efi_part'] = efi_part
                self.log(f"[+] Manual EFI Selected: /dev/{efi_part}")
                
                mnt_path, ok3 = QInputDialog.getText(self, "EFI Mount Path", "Where to mount EFI?", text="/boot/efi")
                if ok3 and mnt_path:
                    self.system_data['efi_mount_path'] = mnt_path

            # Ask if it's Btrfs manually
            is_btrfs = QMessageBox.question(self, 'Filesystem', 'Is the Root partition Btrfs?', 
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if is_btrfs == QMessageBox.StandardButton.Yes:
                self.btn_btrfs.setEnabled(True)
                self.btn_repair.setEnabled(False)
                self.log("[!] Btrfs indicated. Please click '3. Setup Btrfs'.")
            else:
                self.btn_btrfs.setEnabled(False)
                self.btn_repair.setEnabled(True)
                self.log("\n[+] Ready for Repair.")

    def handle_btrfs(self):
        self.log("\n[*] Setting up Btrfs Subvolumes...")
        self.system_data['btrfs_mapping'].clear()
        
        while True:
            subvol, ok1 = QInputDialog.getText(self, "Btrfs Setup", "Enter Subvolume name (e.g., @ or @root):")
            if not ok1 or not subvol: break
            
            mnt, ok2 = QInputDialog.getText(self, "Btrfs Setup", f"Mount point for '{subvol}'? (e.g., / or /home):")
            if not ok2 or not mnt: break
            
            self.system_data['btrfs_mapping'][subvol] = mnt
            self.log(f"  -> Added Route: {subvol} ===> {mnt}")
            
            reply = QMessageBox.question(self, 'Add Another?', 'Add another Btrfs Subvolume?', 
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                break
                
        self.log("[+] Btrfs configuration saved. Ready for Repair.")
        self.btn_repair.setEnabled(True)

    def start_repair(self):
        self.btn_repair.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.btn_manual.setEnabled(False)
        self.btn_unlock_luks.setEnabled(False)
        self.btn_btrfs.setEnabled(False)
        
        self.progress.setRange(0, 0)
        
        self.worker = SystemWorker("full_repair", **self.system_data)
        self.worker.log_signal.connect(self.log)
        self.worker.finished_signal.connect(self.repair_finished)
        self.worker.start()

    def repair_finished(self, success, duration):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        
        self.btn_repair.setEnabled(True)
        self.btn_scan.setEnabled(True)
        self.btn_manual.setEnabled(True)
        self.btn_unlock_luks.setEnabled(True)
        if self.system_data['btrfs_mapping'] or self.btn_btrfs.isEnabled():
            self.btn_btrfs.setEnabled(True)
        
        hours, remainder = divmod(duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if success:
            self.log("\n[+] Operation Successful! GRUB bootloader has been repaired.")
        else:
            self.log("\n[-] Operation failed. Please check the logs.")
            
        self.log(f"Execution Time: {int(hours)}h {int(minutes)}m {int(seconds)}s")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = GrubFixerGUI()
    window.show()
    sys.exit(app.exec())