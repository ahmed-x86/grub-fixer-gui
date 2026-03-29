# grub-fixer-gui
A modern, user-friendly GUI for the ultimate Linux bootloader rescue suite. Effortlessly repair GRUB, unlock LUKS/LVM, and configure Secure Boot with just a few clicks. No terminal wizardry required.
# 🛠️ GRUB Fixer GUI

![Linux](https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Bash](https://img.shields.io/badge/Powered_by-Bash-4EAA25?style=for-the-badge&logo=gnu-bash&logoColor=white)
![Encryption](https://img.shields.io/badge/LUKS_%26_LVM-Supported-blueviolet?style=for-the-badge)
![SecureBoot](https://img.shields.io/badge/Secure_Boot-MOK_Ready-0078D4?style=for-the-badge)

**GRUB Fixer GUI** brings the legendary power of the `grub-fixer` CLI script to a modern, easy-to-use graphical interface. Say goodbye to panic when you see the dreaded `grub rescue>` prompt. 

Whether your system uses complex **Btrfs subvolumes**, is fully encrypted with **LUKS & LVM**, or is locked behind **Secure Boot**, GRUB Fixer GUI handles the heavy lifting in the background. Just point, click, and reboot into your repaired system.

## ✨ Why GRUB Fixer GUI?

The terminal is powerful, but when your system is broken, you need a fast, foolproof, and visual way to get things back online. 

* **🖱️ 1-Click Recovery:** Visual disk selection. No more guessing if your root is `sda3` or `nvme0n1p2`.
* **🔐 Visual LUKS Unlocking:** Securely enter your decryption password through the UI. The tool automatically mounts the mapped drives and activates hidden LVMs.
* **🛡️ Secure Boot Made Easy:** Automatically detects Secure Boot and prepares the `shim` and MOK enrollment (OTP: 1234) without touching the command line.
* **🩺 Auto-Dependency Resolver:** If your broken system is missing crucial packages (like `efibootmgr` or `os-prober`), the GUI will notify you and install them automatically inside the chroot environment.
* **🗂️ Btrfs Mastery:** Visually map your `@`, `@home`, and `@log` subvolumes effortlessly.

## ⚙️ How it Works
This application serves as a smart frontend wrapper. Under the hood, it dynamically generates instructions and feeds them to the bulletproof **GRUB Fixer V22 Engine** (a 1000+ line advanced Bash script) to execute the repair securely and cleanly.

## 🚀 Installation & Usage
*(Here you will add instructions on how to run the Python/GUI app once you build it, e.g., `git clone`, `pip install -r requirements.txt`, `sudo python main.py`)*

## 🖥️ Screenshots
*(Add a screenshot or GIF of the beautiful UI here in the future)*

---
**Developed with by [ahmed-x86](https://github.com/ahmed-x86)**
*Making Linux Recovery Accessible for Everyone.*