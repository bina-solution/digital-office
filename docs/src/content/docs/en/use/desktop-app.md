---
title: The desktop app
description: Download the Digital Office app for Windows, macOS or Linux. It opens your offices in a window of its own, with no browser.
---

## Why

The app puts the office in your computer's list of apps: the Start menu, Applications, a Linux launcher. It opens the office in a window of its own, and no browser is needed.

- One window holds every office you work in. Each office is signed in on its own, and a rail on the side switches between them.
- Closing the window keeps the app in the tray (on a Mac, the menu bar), so the office's notices keep coming.

## Download

| Computer | The file |
|---|---|
| Windows 10 or 11, 64-bit | [dgo-desktop-win-x64.exe](https://github.com/bina-solution/digital-office/releases/latest/download/dgo-desktop-win-x64.exe) |
| macOS 13 or later, Apple silicon or Intel | [dgo-desktop-mac-universal.dmg](https://github.com/bina-solution/digital-office/releases/latest/download/dgo-desktop-mac-universal.dmg) |
| Debian or Ubuntu | [dgo-desktop-linux-amd64.deb](https://github.com/bina-solution/digital-office/releases/latest/download/dgo-desktop-linux-amd64.deb) |
| Fedora or RHEL | [dgo-desktop-linux-x86_64.rpm](https://github.com/bina-solution/digital-office/releases/latest/download/dgo-desktop-linux-x86_64.rpm) |
| Any other Linux | [dgo-desktop-linux-x86_64.AppImage](https://github.com/bina-solution/digital-office/releases/latest/download/dgo-desktop-linux-x86_64.AppImage) |

Each link gives the newest version. Every version is on [the releases page](https://github.com/bina-solution/digital-office/releases).

## Install

The app is not signed yet, so each system warns once, the first time. After that it opens like any other app.

### Windows

1. Open `dgo-desktop-win-x64.exe`.
2. Windows says «Windows protected your PC». Click «More info», then «Run anyway».
3. The app installs for you alone, with no administrator password, and opens.

«הלשכה הדיגיטלית» is now in the Start menu and on the desktop.

### macOS

1. Open `dgo-desktop-mac-universal.dmg` and drag «Digital Office» to Applications.
2. Open it from Applications. macOS says it cannot check or verify the app. Close the message: «Done», or «Cancel»
   on macOS 13 and 14. Do not move it to the Trash.
3. Open System Settings → Privacy & Security. Under Security, next to «Digital Office», click «Open Anyway», and confirm with your password.

From then on it opens from Applications, Launchpad and the Dock.

### Linux

- **Debian or Ubuntu:** `sudo apt install ./dgo-desktop-linux-amd64.deb`. apt installs what the app needs.
- **Fedora or RHEL:** `sudo dnf install ./dgo-desktop-linux-x86_64.rpm`.
- **AppImage:** make the file executable (`chmod +x dgo-desktop-linux-x86_64.AppImage`) and open it.

The package puts «הלשכה הדיגיטלית» in the launcher's list of apps. There is no warning on Linux.

## The first time it opens

The app asks which office to open:

- **Connect to an office:** type its address. The domain is enough: for `example.co.il` the app tries `console.example.co.il` first. Then sign in, as in the browser.
- **The office on this computer:** when the office runs on this computer, the app opens it. When it is installed but not running, the app starts it.

To add another office later: `Ctrl Shift N` (on a Mac `Cmd Shift N`). `Ctrl 1` to `Ctrl 9` switch between them.

## How to check it worked

- The app is in the list of apps: the Start menu on Windows, Applications on a Mac, the launcher on Linux.
- It opens the office in its own window, with no browser around it.

## Uninstall

- **Windows:** Settings → Apps → «Digital Office» → Uninstall.
- **macOS:** drag «Digital Office» from Applications to the Trash.
- **Linux:** `sudo apt remove dgo-desktop`, or `sudo dnf remove dgo-desktop`. An AppImage is deleted like any file.

## See also

- [Getting to know the centre](/en/use/console)
- [Sign-in and users](/en/use/sign-in)
