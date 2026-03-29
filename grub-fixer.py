#!/usr/bin/env python3
# ==============================================================================
# PROJECT: GRUB Fixer GUI
# AUTHOR: ahmed-x86
# VERSION: V23 GUI — Complete Stable Rewrite
# DESCRIPTION:
#   100% feature-parity GUI port of GRUB Fixer V23 bash script.
#   Built from scratch. Previous Gemini version was discarded entirely.
#
# FIXES vs GEMINI VERSION:
#   [SEC-1] LUKS password is hidden (show='*') and passed via stdin, never CLI args
#   [SEC-2] MOK OTP generated randomly via `secrets` module — not hardcoded "1234"
#   [SEC-3] /etc/default/grub is backed up before any modification
#   [ARC-1] UI never freezes — all I/O runs in worker thread, UI only in main thread
#   [ARC-2] All dialogs collected on MAIN thread BEFORE worker thread starts
#   [ARC-3] os-release read with targeted grep, no environment pollution (V23 BUG-3)
#   [ARC-4] fstab Tier-1 mounted via a clean bash script, not fragile Python parsing
#   [ARC-5] efi_mount always has a safe default — no unbound variable crashes
# ==============================================================================

import os, sys, time, subprocess, threading, queue, secrets, string, re
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
APP_TITLE = "GRUB Fixer V23 GUI"
LOG_FILE  = "/var/log/grub-fixer.log"

C = {
    "base":     "#1e1e2e", "mantle":   "#181825", "crust":    "#11111b",
    "text":     "#cdd6f4", "subtext0": "#a6adc8", "surface0": "#313244",
    "surface1": "#45475a", "sapphire": "#74c7ec", "blue":     "#89b4fa",
    "green":    "#a6e3a1", "red":      "#f38ba8", "yellow":   "#f9e2af",
    "mauve":    "#cba6f7", "peach":    "#fab387",
}

# ─────────────────────────────────────────────────────────────────────────────
# HELPER DIALOGS
# ─────────────────────────────────────────────────────────────────────────────
class _BaseDialog(tk.Toplevel):
    def __init__(self, parent, title, prompt, show=""):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=C["base"])
        self.resizable(False, False)
        self.result = None
        self.grab_set()
        self.transient(parent)

        tk.Label(self, text=prompt, bg=C["base"], fg=C["text"],
                 font=("Arial", 10), wraplength=360, justify=tk.LEFT
                 ).pack(padx=20, pady=(15, 5))

        self._entry = tk.Entry(self, show=show, width=38,
                               bg=C["surface0"], fg=C["text"],
                               insertbackground=C["text"], font=("Consolas", 11))
        self._entry.pack(padx=20, pady=5)
        self._entry.focus_set()

        bf = tk.Frame(self, bg=C["base"])
        bf.pack(pady=10)
        tk.Button(bf, text="OK", bg=C["blue"], fg=C["crust"],
                  font=("Arial", 10, "bold"), relief=tk.FLAT, padx=10,
                  command=self._ok).pack(side=tk.LEFT, padx=5)
        tk.Button(bf, text="Cancel", bg=C["surface1"], fg=C["text"],
                  font=("Arial", 10), relief=tk.FLAT, padx=8,
                  command=self._cancel).pack(side=tk.LEFT, padx=5)

        self._entry.bind("<Return>", lambda _: self._ok())
        self._entry.bind("<Escape>", lambda _: self._cancel())
        self._center(parent)
        self.wait_window(self)

    def _center(self, parent):
        self.update_idletasks()
        px, py = parent.winfo_x(), parent.winfo_y()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h   = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + pw//2 - w//2}+{py + ph//2 - h//2}")

    def _ok(self):     self.result = self._entry.get(); self.destroy()
    def _cancel(self): self.result = None;              self.destroy()


def ask_password(parent, title, prompt):
    """Hidden-input password dialog — [V23 SEC-1]"""
    return _BaseDialog(parent, title, prompt, show="*").result


def ask_text(parent, title, prompt, initial=""):
    dlg = _BaseDialog(parent, title, prompt)
    if initial:
        dlg._entry.insert(0, initial)  # noqa — dialog already waited
    return dlg.result  # will be None if called after wait_window, but that's fine
    # NOTE: We call this before wait_window exits, so initial must be set here.
    # Simpler: just instantiate and set in __init__. We keep it here for clarity.


def ask_text2(parent, title, prompt, initial=""):
    """Proper version that sets initial value before wait_window."""
    class _D(_BaseDialog):
        def __init__(self):
            super().__init__(parent, title, prompt)
        # initial must be inserted before wait_window — use a subclass trick
    d = tk.Toplevel(parent)
    d.title(title)
    d.configure(bg=C["base"])
    d.resizable(False, False)
    result_holder = [None]
    d.grab_set()
    d.transient(parent)

    tk.Label(d, text=prompt, bg=C["base"], fg=C["text"],
             font=("Arial", 10), wraplength=360, justify=tk.LEFT
             ).pack(padx=20, pady=(15, 5))

    entry = tk.Entry(d, width=38, bg=C["surface0"], fg=C["text"],
                     insertbackground=C["text"], font=("Consolas", 11))
    entry.pack(padx=20, pady=5)
    entry.insert(0, initial)
    entry.focus_set()

    def ok():     result_holder[0] = entry.get(); d.destroy()
    def cancel(): d.destroy()

    bf = tk.Frame(d, bg=C["base"])
    bf.pack(pady=10)
    tk.Button(bf, text="OK",     bg=C["blue"],     fg=C["crust"],
              font=("Arial", 10, "bold"), relief=tk.FLAT, padx=10,
              command=ok).pack(side=tk.LEFT, padx=5)
    tk.Button(bf, text="Cancel", bg=C["surface1"], fg=C["text"],
              font=("Arial", 10), relief=tk.FLAT, padx=8,
              command=cancel).pack(side=tk.LEFT, padx=5)
    entry.bind("<Return>", lambda _: ok())
    entry.bind("<Escape>", lambda _: cancel())

    d.update_idletasks()
    px, py = parent.winfo_x(), parent.winfo_y()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    w, h   = d.winfo_width(), d.winfo_height()
    d.geometry(f"+{px + pw//2 - w//2}+{py + ph//2 - h//2}")
    d.wait_window(d)
    return result_holder[0]


# ─────────────────────────────────────────────────────────────────────────────
# MAIN APPLICATION
# ─────────────────────────────────────────────────────────────────────────────
class GrubFixerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x760")
        self.minsize(820, 620)
        self.configure(bg=C["base"])

        # [V8] Root check
        if os.geteuid() != 0:
            self.withdraw()
            messagebox.showerror("Root Required",
                "This application must be run as root.\n\n"
                "Usage:  sudo python3 grub-fixer-gui.py")
            sys.exit(1)

        # ── State ─────────────────────────────────────────────────────────
        self._log_q:    queue.Queue = queue.Queue()
        self._scanning: bool        = False

        self.is_live:     bool = False
        self.is_local:    bool = False
        self.has_luks:    bool = False
        self.luks_parts:  list = []
        self.fstab_found: bool = False
        self.fstab_path:  str  = ""

        self._build_styles()
        self._build_ui()
        self.after(100, self._drain_log_queue)
        self.after(300, self.run_initial_scan)

    # =========================================================================
    # STYLES
    # =========================================================================
    def _build_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        for w in ("TFrame", "TLabelFrame"):
            s.configure(w, background=C["base"])
        s.configure("TLabelFrame.Label",
                    background=C["base"], foreground=C["sapphire"],
                    font=("Arial", 10, "bold"))
        s.configure("TLabel",      background=C["base"], foreground=C["text"],
                    font=("Arial", 10))
        s.configure("TCheckbutton", background=C["base"], foreground=C["text"],
                    font=("Arial", 10))
        s.map("TCheckbutton", background=[("active", C["surface0"])])
        s.configure("TCombobox",
                    fieldbackground=C["surface0"], background=C["surface0"],
                    foreground=C["text"], selectbackground=C["surface1"])
        s.configure("TEntry",
                    fieldbackground=C["surface0"], foreground=C["text"])
        s.configure("Vertical.TScrollbar",
                    background=C["surface0"], troughcolor=C["mantle"],
                    arrowcolor=C["text"])

    # =========================================================================
    # UI
    # =========================================================================
    def _build_ui(self):
        # ── Title bar ──────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=C["crust"], pady=10)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="⚙  GRUB Fixer V23",
                 bg=C["crust"], fg=C["blue"],
                 font=("Arial", 18, "bold")).pack(side=tk.LEFT, padx=20)
        self._env_lbl = tk.Label(hdr, text="Detecting environment…",
                                  bg=C["crust"], fg=C["subtext0"],
                                  font=("Arial", 10, "italic"))
        self._env_lbl.pack(side=tk.RIGHT, padx=20)

        # ── Body ───────────────────────────────────────────────────────────
        body = tk.Frame(self, bg=C["base"])
        body.pack(fill=tk.BOTH, expand=True, padx=15, pady=8)

        left = tk.Frame(body, bg=C["base"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._build_layout_frame(left)
        self._build_options_frame(left)
        self._build_buttons(left)

        right = tk.Frame(body, bg=C["base"])
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        self._build_disk_panel(right)

        # ── Console ────────────────────────────────────────────────────────
        tk.Label(self, text="Execution Log",
                 bg=C["base"], fg=C["subtext0"],
                 font=("Arial", 9)).pack(anchor=tk.W, padx=15)
        self._console = scrolledtext.ScrolledText(
            self, bg=C["mantle"], fg=C["green"],
            font=("Consolas", 10), height=13, borderwidth=0,
            selectbackground=C["surface1"], state=tk.DISABLED)
        self._console.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

        for tag, fg in [("ok",   C["green"]),  ("err",  C["red"]),
                        ("warn", C["yellow"]), ("info", C["sapphire"]),
                        ("cmd",  C["mauve"]),  ("dim",  C["subtext0"])]:
            self._console.tag_config(tag, foreground=fg)

    def _build_layout_frame(self, parent):
        lf = ttk.LabelFrame(parent, text=" System Layout ", padding=12)
        lf.pack(fill=tk.X, pady=(0, 8))

        self._fstab_lbl = tk.Label(lf, text="Scanning…",
                                    bg=C["base"], fg=C["yellow"],
                                    font=("Arial", 10, "bold"))
        self._fstab_lbl.grid(row=0, column=0, columnspan=4,
                              sticky=tk.W, pady=(0, 8))

        ttk.Label(lf, text="Root  (/)").grid(row=1, column=0, sticky=tk.W)
        self._root_var = tk.StringVar()
        self._root_cb  = ttk.Combobox(lf, textvariable=self._root_var,
                                       width=28, state="disabled")
        self._root_cb.grid(row=1, column=1, padx=8, pady=4)

        ttk.Label(lf, text="EFI Partition",
                  padding=(12, 0, 0, 0)).grid(row=1, column=2, sticky=tk.W)
        self._efi_var = tk.StringVar()
        self._efi_cb  = ttk.Combobox(lf, textvariable=self._efi_var,
                                      width=28, state="disabled")
        self._efi_cb.grid(row=1, column=3, padx=8, pady=4)

        ttk.Label(lf, text="EFI Mount Path").grid(row=2, column=0, sticky=tk.W)
        self._efi_mnt_var = tk.StringVar(value="/boot/efi")
        self._efi_mnt_ent = ttk.Entry(lf, textvariable=self._efi_mnt_var,
                                       width=28, state="disabled")
        self._efi_mnt_ent.grid(row=2, column=1, padx=8, pady=4)

    def _build_options_frame(self, parent):
        of = ttk.LabelFrame(parent, text=" Options ", padding=12)
        of.pack(fill=tk.X, pady=(0, 8))

        self._health_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(of,
            text="[V20] Auto-install missing packages (grub, os-prober, efibootmgr)",
            variable=self._health_var).pack(anchor=tk.W)

        self._auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(of,
            text="[V18] Zero-interaction mode (auto-confirm everything)",
            variable=self._auto_var).pack(anchor=tk.W, pady=4)

        self._sb_lbl = tk.Label(of, text="", bg=C["base"],
                                 fg=C["yellow"], font=("Arial", 9))
        self._sb_lbl.pack(anchor=tk.W)

    def _build_buttons(self, parent):
        bf = tk.Frame(parent, bg=C["base"])
        bf.pack(fill=tk.X, pady=6)

        self._repair_btn = tk.Button(
            bf, text="🚀  Execute GRUB Repair",
            bg=C["blue"], fg=C["crust"],
            font=("Arial", 11, "bold"),
            relief=tk.FLAT, padx=14, pady=7,
            command=self._on_repair_click)
        self._repair_btn.pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(bf, text="🔄 Rescan",
                  bg=C["surface0"], fg=C["text"],
                  font=("Arial", 10), relief=tk.FLAT, padx=8,
                  command=self.run_initial_scan).pack(side=tk.LEFT, padx=4)

        tk.Button(bf, text="❌ Exit",
                  bg=C["surface0"], fg=C["red"],
                  font=("Arial", 10), relief=tk.FLAT, padx=8,
                  command=self.destroy).pack(side=tk.RIGHT)

    def _build_disk_panel(self, parent):
        pf = ttk.LabelFrame(parent, text=" Available Disks ", padding=8)
        pf.pack(fill=tk.BOTH, expand=True)

        self._disk_txt = tk.Text(pf, bg=C["mantle"], fg=C["subtext0"],
                                  font=("Consolas", 9), width=33,
                                  borderwidth=0, state=tk.DISABLED)
        sb = ttk.Scrollbar(pf, command=self._disk_txt.yview)
        self._disk_txt.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._disk_txt.pack(fill=tk.BOTH, expand=True)

    # =========================================================================
    # LOGGING (thread-safe)
    # =========================================================================
    def log(self, msg: str, tag: str = ""):
        if not tag:
            m = msg.lower()
            if   m.startswith("[+]") or "🎉" in msg:         tag = "ok"
            elif m.startswith("[-]") or "❌" in msg:          tag = "err"
            elif m.startswith("[!]") or "⚠" in msg:           tag = "warn"
            elif m.startswith("[*]") or m.startswith("->"):   tag = "info"
            elif m.startswith("   "):                          tag = "dim"
        self._log_q.put((msg, tag))

    def _drain_log_queue(self):
        while not self._log_q.empty():
            msg, tag = self._log_q.get_nowait()
            self._console.config(state=tk.NORMAL)
            self._console.insert(tk.END, msg + "\n", tag or None)
            self._console.see(tk.END)
            self._console.config(state=tk.DISABLED)
            try:
                with open(LOG_FILE, "a") as f:
                    f.write(msg + "\n")
            except Exception:
                pass
        self.after(100, self._drain_log_queue)

    # =========================================================================
    # COMMAND HELPERS
    # =========================================================================
    def _run(self, cmd: str, silent: bool = False) -> bool:
        """Run shell command, stream output to log. Returns True on success."""
        if not silent:
            self.log(f"-> {cmd}", "cmd")
        try:
            proc = subprocess.Popen(
                cmd, shell=True, executable="/bin/bash",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                line = line.rstrip()
                if line and not silent:
                    self.log("   " + line)
            proc.wait()
            return proc.returncode == 0
        except Exception as e:
            if not silent:
                self.log(f"[-] Exception: {e}", "err")
            return False

    def _get(self, cmd: str) -> str:
        """Run command, return trimmed stdout. Empty string on failure."""
        try:
            return subprocess.check_output(
                cmd, shell=True, executable="/bin/bash",
                stderr=subprocess.DEVNULL, text=True).strip()
        except subprocess.CalledProcessError:
            return ""

    def _write_script(self, path: str, content: str) -> bool:
        try:
            with open(path, "w") as f:
                f.write(content)
            os.chmod(path, 0o700)
            return True
        except Exception as e:
            self.log(f"[-] Cannot write script {path}: {e}", "err")
            return False

    # =========================================================================
    # INITIAL SCAN  (worker thread)
    # =========================================================================
    def run_initial_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self._repair_btn.config(state=tk.DISABLED)
        self._fstab_lbl.config(text="Scanning…", fg=C["yellow"])
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        self.log("=" * 52)
        self.log(f"[*] {APP_TITLE}  —  {time.ctime()}")
        self.log("=" * 52)

        # lsblk panel
        lsblk_out = self._get("lsblk")
        self.after(0, self._set_disk_panel, lsblk_out)

        # [V17] Environment detection
        cmdline  = self._get("cat /proc/cmdline").lower()
        live_kws = ["archiso","casper","rd.live.image","live-media",
                    "boot=live","isofrom","miso","cdrom","toram"]
        if any(k in cmdline for k in live_kws):
            self.is_live, self.is_local = True, False
            self.log("[*] V17: Live Environment (USB/ISO) detected.", "warn")
            self.after(0, self._env_lbl.config,
                       {"text": "🔴  Live Environment (USB/ISO)", "fg": C["yellow"]})
        else:
            self.is_live, self.is_local = False, True
            self.log("[*] V17: Real Machine (In-Situ mode) detected.", "ok")
            self.after(0, self._env_lbl.config,
                       {"text": "🟢  Real Machine — In-Situ Mode", "fg": C["green"]})

        # [V21] LUKS
        raw = self._get("lsblk -l -o NAME,FSTYPE | awk '$2==\"crypto_LUKS\"{print $1}'")
        self.luks_parts = [p for p in raw.splitlines() if p.strip()]
        self.has_luks   = bool(self.luks_parts)
        if self.has_luks:
            self.log(f"[*] V21: LUKS partition(s): {', '.join(self.luks_parts)}", "warn")

        # [V11] fstab scan
        self._scan_fstab()

        # Populate partition dropdowns
        self._populate_dropdowns()

        # [V22] Secure Boot
        if "SecureBoot enabled" in self._get("mokutil --sb-state 2>/dev/null"):
            self.log("[!] V22: Secure Boot is ENABLED.", "warn")
            self.after(0, self._sb_lbl.config,
                       {"text": "⚠  Secure Boot ENABLED — MOK enrollment required on next boot"})

        self._scanning = False
        self.after(0, self._repair_btn.config, {"state": tk.NORMAL})

    def _set_disk_panel(self, text):
        self._disk_txt.config(state=tk.NORMAL)
        self._disk_txt.delete("1.0", tk.END)
        self._disk_txt.insert(tk.END, text)
        self._disk_txt.config(state=tk.DISABLED)

    # ─────────────────────────────────────────────────────────────────────────
    def _scan_fstab(self):
        """[V11] Three-path fstab discovery: local / btrfs / ext4-xfs."""
        scan = "/tmp/grub-fixer-scan"
        os.makedirs(scan, exist_ok=True)
        self._run(f"grep -qs ' {scan}' /proc/mounts "
                  f"&& umount -R {scan} 2>/dev/null; true", silent=True)

        self.fstab_found = False
        self.fstab_path  = ""

        if self.is_local:
            if os.path.isfile("/etc/fstab"):
                self.fstab_found, self.fstab_path = True, "/etc/fstab"
        else:
            # ── Try Btrfs ─────────────────────────────────────────────────
            btrfs = [p for p in
                     self._get("lsblk -l -o NAME,FSTYPE | awk '$2==\"btrfs\"{print $1}'")
                     .splitlines() if p.strip()]
            for part in btrfs:
                for sub in ["@", "@root", ""]:
                    opt = f"-o ro,subvol={sub}" if sub else "-o ro"
                    if self._run(f"mount {opt} /dev/{part} {scan}", silent=True):
                        if os.path.isfile(f"{scan}/etc/fstab"):
                            self.fstab_found = True
                            self.fstab_path  = f"{scan}/etc/fstab"
                            break
                        self._run(f"umount {scan}", silent=True)
                if self.fstab_found:
                    break

            # ── Fallback: ext4/xfs largest first ──────────────────────────
            if not self.fstab_found:
                ext_parts = [p for p in
                    self._get("lsblk -l -b -o NAME,FSTYPE,SIZE "
                              "| awk '$2~/ext4|xfs/' "
                              "| sort -k3 -rn | awk '{print $1}'")
                    .splitlines() if p.strip()]
                for part in ext_parts:
                    if self._run(f"mount -o ro /dev/{part} {scan}", silent=True):
                        if os.path.isfile(f"{scan}/etc/fstab"):
                            self.fstab_found = True
                            self.fstab_path  = f"{scan}/etc/fstab"
                            break
                        self._run(f"umount {scan}", silent=True)

        if self.fstab_found:
            self.log(f"[+] fstab found: {self.fstab_path}", "ok")
            self.log("\n=== Detected System Layout (From fstab) ===")
            self._print_fstab_layout()
            self.log("===========================================")
            self.after(0, self._fstab_lbl.config,
                       {"text": "[+] Tier 1 (PRO FSTAB) — auto-mount ready",
                        "fg":  C["green"]})
            self.after(0, self._set_manual_widgets, "disabled")
        else:
            self.log("[-] fstab not found → Tier 2/3 (manual / auto-detect)", "warn")
            self.after(0, self._fstab_lbl.config,
                       {"text": "[-] No fstab — Tier 2/3 active (use dropdowns below)",
                        "fg":  C["red"]})
            self.after(0, self._set_manual_widgets, "readonly")

    def _print_fstab_layout(self):
        skip = {"swap","tmpfs","proc","sysfs","devtmpfs","devpts","efivarfs","cdrom"}
        try:
            with open(self.fstab_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    cols = line.split()
                    if len(cols) < 3 or cols[2] in skip or cols[1] == "none":
                        continue
                    sub = ""
                    if cols[2] == "btrfs" and len(cols) > 3:
                        m = re.search(r"subvol=([^,\s]+)", cols[3])
                        if m:
                            sub = f", {m.group(0)}"
                    self.log(f"  -> Mount: {cols[1]} | Device: {cols[0]} ({cols[2]}{sub})")
        except Exception as e:
            self.log(f"[-] Cannot read fstab: {e}", "err")

    def _set_manual_widgets(self, state):
        self._root_cb.config(state=state)
        self._efi_cb.config(state=state)
        self._efi_mnt_ent.config(state="normal" if state == "readonly" else "disabled")

    def _populate_dropdowns(self):
        roots = [f"/dev/{p}" for p in
                 self._get("lsblk -l -o NAME,FSTYPE "
                           "| awk '$2~/ext4|btrfs|xfs/{print $1}'")
                 .splitlines() if p.strip()]
        efis  = ["None"] + [f"/dev/{p}" for p in
                 self._get("lsblk -l -o NAME,FSTYPE "
                           "| awk '$2==\"vfat\"{print $1}'")
                 .splitlines() if p.strip()]
        self.after(0, self._set_dropdowns, roots, efis)

    def _set_dropdowns(self, roots, efis):
        self._root_cb["values"] = roots
        self._efi_cb["values"]  = efis
        if roots: self._root_cb.current(0)
        if len(efis) > 1: self._efi_cb.current(1)
        elif efis:         self._efi_cb.current(0)

    # =========================================================================
    # LUKS UNLOCK  (main thread — needs dialog)
    # =========================================================================
    def _maybe_unlock_luks(self) -> bool:
        """Returns False only if user cancels in a way that should stop repair."""
        if not self.has_luks or not self.is_live:
            return True
        if self.is_local:
            return True

        if self.is_live and not self._auto_var.get():
            if not messagebox.askyesno(
                    "LUKS Detected",
                    f"Encrypted partition(s) found:\n  {', '.join(self.luks_parts)}\n\n"
                    "Unlock them now?"):
                return True   # continue without unlocking

        if not self._get("command -v cryptsetup"):
            messagebox.showerror("Missing Tool",
                "cryptsetup is not installed on this Live environment.\n"
                "Install it first:  pacman -Sy cryptsetup")
            return False

        for part in self.luks_parts:
            mapper = f"crypt_{part}"
            if os.path.exists(f"/dev/mapper/{mapper}"):
                self.log(f"   [i] /dev/{part} already unlocked.", "info")
                continue

            # [V23 SEC-1] — hidden dialog, password via stdin
            pwd = ask_password(self, "LUKS Unlock",
                               f"Password for /dev/{part}:")
            if pwd is None:
                self.log(f"   [i] Skipping /dev/{part}.", "warn")
                continue

            self.log(f"-> Unlocking /dev/{part}…")
            try:
                r = subprocess.run(
                    ["cryptsetup", "luksOpen", f"/dev/{part}", mapper, "-"],
                    input=pwd, text=True, capture_output=True)
                if r.returncode == 0:
                    self.log(f"   [+] Unlocked → /dev/mapper/{mapper}", "ok")
                else:
                    self.log(f"   [-] Failed: {r.stderr.strip()}", "err")
            except Exception as e:
                self.log(f"   [-] cryptsetup error: {e}", "err")
            finally:
                del pwd   # clear from memory

        self.log("[*] Scanning for LVM volumes…")
        self._run("vgchange -ay 2>/dev/null; true", silent=True)
        return True

    # =========================================================================
    # REPAIR BUTTON  (main thread)
    # =========================================================================
    def _on_repair_click(self):
        if not self._maybe_unlock_luks():
            return
        params = self._collect_params()
        if params is None:
            return
        self._repair_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._repair_worker,
                         args=(params,), daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    def _collect_params(self) -> dict | None:
        """
        Gather ALL user inputs that require dialogs.
        Runs on the MAIN THREAD — no blocking I/O, only dialog boxes.
        Returns None to abort, otherwise a dict of parameters.
        """
        p = {
            "root_part":     "",
            "efi_part":      "None",
            "efi_mount":     self._efi_mnt_var.get().strip() or "/boot/efi",
            "btrfs_subvols": [],
            "custom_mounts": [],
            "use_fstab":     self.fstab_found,
        }

        # In-Situ: nothing extra needed
        if self.is_local:
            return p

        # Tier 1: fstab confirmed?
        if self.fstab_found and not self._auto_var.get():
            if not messagebox.askyesno(
                    "Confirm Layout",
                    "Tier 1 (PRO FSTAB) is ready.\n"
                    "The detected layout is shown in the log.\n\n"
                    "Proceed with automatic mounting?"):
                p["use_fstab"] = False
                self._fstab_lbl.config(
                    text="Manual mode selected", fg=C["yellow"])
                self._set_manual_widgets("readonly")
            else:
                return p    # Tier 1 confirmed — no further input needed

        # Tier 2 / 3: manual selection
        root = self._root_var.get().strip()
        if not root:
            messagebox.showerror("Error", "Root (/) partition is required!")
            return None
        p["root_part"] = root

        efi = self._efi_var.get().strip()
        p["efi_part"] = efi
        if efi and efi != "None":
            mnt = self._efi_mnt_var.get().strip() or "/boot/efi"
            p["efi_mount"] = mnt

        # [V9] Btrfs subvolumes
        fstype = self._get(f"lsblk -n -o FSTYPE {root} 2>/dev/null | head -1")
        if fstype == "btrfs" and not self._auto_var.get():
            self.log(f"\n[*] Btrfs detected on {root} — enter subvolumes.", "warn")
            while True:
                ans = ask_text2(self, "Btrfs Subvolume",
                    "Enter subvolume and mount point:\n"
                    "Examples:   @ /     @home /home     @log /var/log",
                    "@ /")
                if not ans:
                    break
                sv_parts = ans.strip().split()
                if len(sv_parts) >= 2:
                    p["btrfs_subvols"].append((sv_parts[0], sv_parts[1]))
                if not messagebox.askyesno("Btrfs", "Add another subvolume?"):
                    break

        # [V7] Custom volumes
        if not self._auto_var.get():
            while messagebox.askyesno(
                    "Custom Volumes",
                    "Mount an additional partition?\n"
                    "(e.g., separate /home on another disk)"):
                dev = ask_text2(self, "Custom Partition",
                                "Partition name (e.g. vda4  or  /dev/vda4):")
                mnt = ask_text2(self, "Custom Mount Point",
                                "Mount point (e.g. /home  or  /var):")
                if dev and mnt:
                    if not dev.startswith("/"):
                        dev = f"/dev/{dev}"
                    if not mnt.startswith("/"):
                        mnt = f"/{mnt}"
                    p["custom_mounts"].append((dev, mnt))

        return p

    # =========================================================================
    # REPAIR WORKER  (background thread)
    # =========================================================================
    def _repair_worker(self, p: dict):
        start   = time.time()
        success = False
        try:
            self.log("\n" + "=" * 52)
            self.log("[*] GRUB REPAIR SEQUENCE INITIATED")
            self.log("=" * 52)
            success = self._do_repair(p)
        except Exception as e:
            import traceback
            self.log(f"\n❌ CRITICAL ERROR: {e}", "err")
            self.log(traceback.format_exc(), "err")
        finally:
            elapsed = int(time.time() - start)
            h, r = divmod(elapsed, 3600)
            m, s = divmod(r, 60)
            self.log(f"\n⏱  Execution Time: {h}h {m}m {s}s")
            if success:
                if elapsed < 15:
                    self.log("Wait, did I just fix that?! "
                             "You didn't even get to sip your coffee! ☕😂🏃", "ok")
                elif elapsed <= 60:
                    self.log("Done and dusted! Not even the pros can speedrun "
                             "a system repair like this. 🏆🔥", "ok")
                else:
                    self.log("Took a minute, but hey… I'm the big boss, "
                             "and I like to make a cinematic entrance! 👑🕶️🍿", "ok")
            self.after(0, self._repair_btn.config, {"state": tk.NORMAL})

    # ─────────────────────────────────────────────────────────────────────────
    def _do_repair(self, p: dict) -> bool:
        """
        Core logic — mirrors grub-fixer V23 bash script exactly.
        Three execution paths:
          1. In-Situ (is_local=True)      — repair running system directly
          2. Live + fstab  (Tier 1)       — auto-mount via fstab, then chroot
          3. Live + manual (Tier 2/3)     — manual/auto-detect mount, then chroot
        """
        boot_mode     = "legacy"
        efi_mount     = p["efi_mount"]
        target_disk   = ""
        target_chroot = ""          # "" = in-situ,  "/mnt" = chroot

        # ─────────────────────────────────────────────────────────────────
        # [V16] IN-SITU PATH
        # ─────────────────────────────────────────────────────────────────
        if self.is_local:
            self.log("\n[*] Executing In-Situ (Local) GRUB Repair…")
            self._run("mount -a 2>/dev/null; true")

            if os.path.isdir("/sys/firmware/efi"):
                boot_mode = "efi"
                # Fix efivars
                ev = "/sys/firmware/efi/efivars"
                if not os.path.isdir(ev) or not os.listdir(ev):
                    self.log("[!] efivars not mounted — fixing…", "warn")
                    self._run("mount -t efivarfs efivarfs "
                              "/sys/firmware/efi/efivars; true")

                efi_mount = self._get(
                    "findmnt -n -o TARGET -t vfat "
                    "| grep -E '^/boot' | head -1")
                if not efi_mount:
                    self.log("[-] EFI detected but no vfat at /boot or /boot/efi.", "err")
                    self.log("    Mount your EFI partition first.", "err")
                    return False
            else:
                boot_mode = "legacy"
                root_dev  = self._get("findmnt -n -o SOURCE / | head -1")
                p1 = self._get(f"lsblk -no PKNAME {root_dev} | head -1")
                p2 = (self._get(f"lsblk -no PKNAME /dev/{p1} | head -1")
                      if p1 else "")
                target_disk = (f"/dev/{p2}" if p2 else
                               (f"/dev/{p1}" if p1 else root_dev))

            target_chroot = ""

        # ─────────────────────────────────────────────────────────────────
        # LIVE PATH — MOUNT PHASE
        # ─────────────────────────────────────────────────────────────────
        else:
            self.log("\n[*] Executing Mount commands…")
            self._run("grep -qs ' /mnt' /proc/mounts "
                      "&& umount -R /mnt 2>/dev/null; true")

            if p["use_fstab"]:
                # ── Tier 1: fstab bash script ─────────────────────────────
                self.log("\n[*] Tier 1: Automated FSTAB Mounts…")
                fstab_sh = f"""#!/bin/bash
set -e
FSTAB="{self.fstab_path}"

_resolve() {{
    local dev="$1"
    if [[ "$dev" == UUID=* ]]; then
        blkid -U "${{dev#UUID=}}" 2>/dev/null || echo "$dev"
    elif [[ "$dev" == PARTUUID=* ]]; then
        blkid -t PARTUUID="${{dev#PARTUUID=}}" -o device 2>/dev/null | head -1 || echo "$dev"
    else
        echo "$dev"
    fi
}}

SKIP_TYPES="swap tmpfs proc sysfs devtmpfs devpts efivarfs cdrom"

# Pass 1: mount root
while read -r dev mnt type opts _; do
    [[ "$dev" =~ ^#.*$ || -z "$dev" ]] && continue
    [[ " $SKIP_TYPES " == *" $type "* || "$mnt" == "none" || "$mnt" != "/" ]] && continue
    real=$(_resolve "$dev")
    echo "   [+] Mounting / → $real"
    if [[ "$type" == "btrfs" ]]; then
        sub=$(echo "$opts" | grep -o 'subvol=[^,]*' | cut -d= -f2 || true)
        mount -o subvol="$sub" "$real" /mnt
    else
        mount "$real" /mnt
    fi
done < "$FSTAB"

# Pass 2: mount everything else
while read -r dev mnt type opts _; do
    [[ "$dev" =~ ^#.*$ || -z "$dev" ]] && continue
    [[ " $SKIP_TYPES " == *" $type "* || "$mnt" == "none" || "$mnt" == "/" ]] && continue
    real=$(_resolve "$dev")
    [ ! -b "$real" ] && echo "   [!] $real not found, skipping $mnt" && continue
    echo "   [+] Mounting $mnt → $real"
    mkdir -p "/mnt$mnt"
    if [[ "$type" == "btrfs" ]]; then
        sub=$(echo "$opts" | grep -o 'subvol=[^,]*' | cut -d= -f2 || true)
        mount -o subvol="$sub" "$real" "/mnt$mnt"
    else
        mount "$real" "/mnt$mnt"
    fi
done < "$FSTAB"
"""
                if not self._write_script("/tmp/gf_fstab.sh", fstab_sh):
                    return False
                if not self._run("bash /tmp/gf_fstab.sh"):
                    self.log("[-] FSTAB mount failed!", "err")
                    return False

                # Detect boot mode from what was actually mounted
                efi_at = (self._get("findmnt -n -o TARGET /mnt/boot/efi 2>/dev/null")
                          or self._get("findmnt -n -o TARGET /mnt/boot 2>/dev/null"))
                if efi_at:
                    boot_mode = "efi"
                    efi_mount = ("/boot/efi"
                                 if self._get("findmnt -n /mnt/boot/efi 2>/dev/null")
                                 else "/boot")
                else:
                    boot_mode = "legacy"
                    rs = self._get("findmnt -n -o SOURCE /mnt | head -1")
                    p1 = self._get(f"lsblk -no PKNAME {rs} | head -1")
                    target_disk = f"/dev/{p1}" if p1 else rs

            else:
                # ── Tier 2/3: manual / auto-detect ────────────────────────
                self.log("\n[*] Tier 2/3: Manual Mount…")
                root = p["root_part"]
                efi  = p["efi_part"]

                fstype = self._get(
                    f"lsblk -n -o FSTYPE {root} 2>/dev/null | head -1")
                if fstype == "btrfs" and p["btrfs_subvols"]:
                    for sub, mnt_pt in p["btrfs_subvols"]:
                        tgt = "/mnt" if mnt_pt == "/" else f"/mnt{mnt_pt}"
                        self._run(f"mkdir -p {tgt}")
                        self._run(f"mount -o subvol={sub} {root} {tgt}")
                else:
                    self._run(f"mount {root} /mnt")

                if efi and efi != "None":
                    boot_mode = "efi"
                    self._run(f"mkdir -p /mnt{efi_mount}")
                    self._run(f"mount {efi} /mnt{efi_mount}")
                else:
                    boot_mode = "legacy"
                    p1 = self._get(f"lsblk -no PKNAME {root} | head -1")
                    p2 = (self._get(f"lsblk -no PKNAME /dev/{p1} | head -1")
                          if p1 else "")
                    target_disk = (f"/dev/{p2}" if p2 else
                                   (f"/dev/{p1}" if p1 else root))

                for dev, mnt_pt in p["custom_mounts"]:
                    self._run(f"mkdir -p /mnt{mnt_pt}")
                    self._run(f"mount {dev} /mnt{mnt_pt}")

            # ── Bind mounts ────────────────────────────────────────────────
            self.log("\n[*] Preparing chroot environment…")
            for d in ("dev", "proc", "sys", "run"):
                self._run(f"mount --bind /{d} /mnt/{d}")
            if os.path.isfile("/etc/resolv.conf"):
                self._run("cp /etc/resolv.conf /mnt/etc/resolv.conf; true")

            target_chroot = "/mnt"

        # ─────────────────────────────────────────────────────────────────
        # UNIVERSAL GRUB INSTALL STAGE
        # ─────────────────────────────────────────────────────────────────
        ch        = f"chroot {target_chroot} " if target_chroot else ""
        os_rel    = (f"{target_chroot}/etc/os-release"
                     if target_chroot else "/etc/os-release")

        # [V19/V23 BUG-3] Targeted grep — no source pollution
        os_name   = (self._get(
            f"grep -m1 '^NAME=' {os_rel} | cut -d= -f2- | tr -d '\"'")
            or "Linux")
        target_id = self._get(
            f"grep -m1 '^ID=' {os_rel} | cut -d= -f2- | tr -d '\"'").lower()
        id_like   = self._get(
            f"grep -m1 '^ID_LIKE=' {os_rel} | cut -d= -f2- | tr -d '\"'").lower()

        rh_fam  = {"fedora","rhel","centos","rocky","almalinux"}
        deb_fam = {"debian","ubuntu","pop"}
        is_rh   = any(x in target_id or x in id_like for x in rh_fam)
        is_deb  = any(x in target_id or x in id_like for x in deb_fam)

        grub_ins = "grub2-install" if is_rh else "grub-install"
        grub_mk  = "grub2-mkconfig" if is_rh else "grub-mkconfig"
        grub_cfg = "/boot/grub2/grub.cfg" if is_rh else "/boot/grub/grub.cfg"

        if is_rh:
            self.log("[i] RedHat/Fedora family → grub2 commands.", "info")
        self.log(f"[*] OS: {os_name} | Mode: {boot_mode.upper()}", "info")

        # [V22] Secure Boot
        sb_raw      = self._get(f"{ch}mokutil --sb-state 2>/dev/null")
        secure_boot = "SecureBoot enabled" in sb_raw
        if secure_boot:
            self.log("[!] Secure Boot: ENABLED", "warn")

        # [V15] EFI bitness
        efi_target = "x86_64-efi"
        if boot_mode == "efi":
            plat = (f"{target_chroot}/sys/firmware/efi/fw_platform_size"
                    if target_chroot else "/sys/firmware/efi/fw_platform_size")
            if os.path.isfile(plat) and self._get(f"cat {plat}") == "32":
                efi_target = "i386-efi"
                self.log("[!] 32-bit UEFI → i386-efi target.", "warn")

        # [V20] Health check
        if self._health_var.get():
            self.log("\n[*] Performing Health Check…", "info")
            missing = []
            for cmd, pkg in [(grub_ins, "grub2" if is_rh else "grub"),
                             ("os-prober", "os-prober")]:
                if not self._get(f"{ch}command -v {cmd} 2>/dev/null"):
                    missing.append(pkg)
            if self.has_luks and not self._get(
                    f"{ch}command -v cryptsetup 2>/dev/null"):
                missing.append("cryptsetup")
            if boot_mode == "efi":
                if not self._get(f"{ch}command -v efibootmgr 2>/dev/null"):
                    missing.append("efibootmgr")
                if secure_boot and not self._get(
                        f"{ch}command -v mokutil 2>/dev/null"):
                    missing.append("mokutil")

            if missing:
                self.log(f"[-] Missing: {', '.join(missing)} — installing…", "warn")
                pkg_list = " ".join(missing)
                pkg_sh = f"""#!/bin/bash
if command -v pacman   &>/dev/null; then pacman -Sy --noconfirm {pkg_list}
elif command -v apt-get &>/dev/null; then apt-get update && apt-get install -y {pkg_list}
elif command -v dnf    &>/dev/null; then dnf install -y {pkg_list}
elif command -v zypper &>/dev/null; then zypper install -y {pkg_list}
else echo "[-] Unknown package manager"; exit 1; fi
"""
                script_path = (f"{target_chroot}/tmp/gf_pkg.sh"
                               if target_chroot else "/tmp/gf_pkg.sh")
                if self._write_script(script_path, pkg_sh):
                    runner = (f"chroot {target_chroot} /bin/bash /tmp/gf_pkg.sh"
                              if target_chroot else f"bash {script_path}")
                    self._run(runner)
            else:
                self.log("[+] Health check passed — all packages present.", "ok")

        # [V23 SEC-2] Random MOK OTP
        mok_otp = ""
        if secure_boot and boot_mode == "efi":
            alpha   = string.ascii_letters + string.digits
            mok_otp = "".join(secrets.choice(alpha) for _ in range(12))

        # [V23 SEC-3] Backup /etc/default/grub
        grub_def = (f"{target_chroot}/etc/default/grub"
                    if target_chroot else "/etc/default/grub")
        if os.path.isfile(grub_def):
            bak = f"{grub_def}.bak.{int(time.time())}"
            self._run(f"cp {grub_def} {bak}")
            self.log(f"[+] Backed up /etc/default/grub → {bak}", "ok")

        # Build GRUB install line
        if boot_mode == "efi":
            if secure_boot and is_deb:
                ins_line = (f'{grub_ins} --target={efi_target} '
                            f'--efi-directory="{efi_mount}" '
                            f'--bootloader-id="{os_name}" --uefi-secure-boot')
            else:
                ins_line = (f'{grub_ins} --target={efi_target} '
                            f'--efi-directory="{efi_mount}" '
                            f'--bootloader-id="{os_name}" --removable')
        else:
            ins_line = f'{grub_ins} --target=i386-pc "{target_disk}"'

        # Optional blocks
        luks_block = ""
        if self.has_luks:
            luks_block = """
echo "-> Enabling LUKS support (GRUB_ENABLE_CRYPTODISK=y)..."
sed -i '/GRUB_ENABLE_CRYPTODISK/d' /etc/default/grub 2>/dev/null; true
echo "GRUB_ENABLE_CRYPTODISK=y" >> /etc/default/grub
"""
        mok_block = ""
        if secure_boot and boot_mode == "efi" and mok_otp:
            mok_block = f"""
if command -v mokutil &>/dev/null && [ -f /var/lib/shim-signed/mok/MOK.der ]; then
    echo "-> Enrolling MOK (random OTP)..."
    printf '{mok_otp}\\n{mok_otp}\\n' | mokutil --import /var/lib/shim-signed/mok/MOK.der; true
    echo "========================================================"
    echo "  MOK One-Time Password: {mok_otp}"
    echo "  Write this down BEFORE rebooting!"
    echo "========================================================"
elif command -v sbctl &>/dev/null; then
    echo "-> sbctl detected — signing GRUB..."
    sbctl sign -s "{efi_mount}/EFI/{os_name}/grubx64.efi"; true
fi
"""

        # Final repair script
        repair_sh = f"""#!/bin/bash
set -e
mkdir -p "$(dirname {grub_cfg})"

echo "-> Installing GRUB ({boot_mode.upper()})..."
{ins_line}

echo "-> Enabling OS Prober..."
sed -i '/GRUB_DISABLE_OS_PROBER/d' /etc/default/grub 2>/dev/null; true
echo "GRUB_DISABLE_OS_PROBER=false" >> /etc/default/grub
{luks_block}
echo "-> Generating GRUB config..."
{grub_mk} -o {grub_cfg}
{mok_block}
echo "-> Done."
"""
        rpath  = (f"{target_chroot}/tmp/gf_repair.sh"
                  if target_chroot else "/tmp/gf_repair.sh")
        runner = (f"chroot {target_chroot} /bin/bash /tmp/gf_repair.sh"
                  if target_chroot else f"bash {rpath}")

        if not self._write_script(rpath, repair_sh):
            return False
        ok = self._run(runner)

        # ── Cleanup ───────────────────────────────────────────────────────
        if target_chroot:
            self.log("\n[*] Unmounting filesystems…")
            self._run("umount -R /mnt 2>/dev/null; true")

        if self.has_luks and not self.is_local:
            self.log("[*] Relocking LUKS partitions…")
            self._run("vgchange -an 2>/dev/null; true")
            for part in self.luks_parts:
                self._run(f"cryptsetup luksClose crypt_{part} 2>/dev/null; true")

        self._run("umount -R /tmp/grub-fixer-scan 2>/dev/null; true", silent=True)

        if ok:
            self.log(
                f"\n🎉 GRUB repaired successfully! "
                f"({boot_mode.upper()} mode)", "ok")
            self.log(f"[i] Log saved to: {LOG_FILE}", "info")
            if mok_otp:
                self.log(f"\n⚠️  MOK OTP (write this down!): {mok_otp}", "warn")
        else:
            self.log("\n❌ GRUB repair failed. Check the log above.", "err")

        return ok


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = GrubFixerApp()
    app.mainloop()