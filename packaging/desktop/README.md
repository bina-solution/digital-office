# The Digital Office desktop app (DGO-1972)

An app a person downloads and installs, which then sits in the computer's list of apps — the Start menu,
Applications and Launchpad, a Linux launcher — and opens the office in its own window, without a browser.
The decision and the research: `.claude/notes/DGO-1972*.md` (Electron, for Meet's camera and screen sharing on every
OS and for `*.localhost`; Tauri is the runner-up, to revisit with Tauri 3's CEF runtime).

What it is: a thin shell. Every screen inside the window is the office's own console; the app adds what a tab cannot.

- **The first run** (`src/ui/welcome.html`) has two ways in:
  - **connect to an office:** an address → `https://console.<domain>/`. A person may type the domain alone; the app
    tries its console first.
  - **the office on this computer:** open it if it runs, start it with the platform's own `dgo run` if it is
    installed, else the installer's page.
- **Several offices**, each in its own session (cookies and storage never mix), with **a rail** of them
  (`src/ui/rail.html`) once there are two. «This computer» comes first, with a dot lit while its office runs.
  Ctrl+1…9 switches; Ctrl+Shift+N adds one.
- **A tray icon:** the window closes to it, and the office's notices keep coming; Quit is in its menu.
- **Links** `dgo://open?office=<host>&path=/#/m/indox` open an office of the app at a screen.

## Security (Electron's checklist, as set in the research)

- Every renderer is sandboxed, with context isolation and no Node. The app's own screens get `preload-shell.js`.
- An office's page gets `preload-office.js`:
  - five functions: badge, notify, open-external, switch office, engine status;
  - answered only for the top frame of a page inside that office (`main.js` `fromOffice`).
- **Navigation** stays inside the office: its console and `*.<domain>`, on the office's own scheme. Anything else goes
  to the system's browser — `https`, `http`, `mailto` and `tel` only, never a file or a program (`src/offices.js`).
- **Permissions:**
  - camera, microphone and screen sharing: only the office's meetings (`meet.<domain>`);
  - notifications, the clipboard and full screen: the office's pages;
  - nothing else, ever.
- **Fuses** (`electron-builder.yml`): no run-as-Node, no `NODE_OPTIONS`, no `--inspect`, code only from the app's
  archive, and the archive's integrity checked.
- **http** is accepted only for this computer (`*.localhost`, loopback) and an office's LAN door (a private address);
  every other office is https.

## Run, test, build

```bash
cd packaging/desktop
npm ci
npm test                 # the rules of src/offices.js and the icons (node --test, no Electron)
npm start                # the app, unpackaged
npx electron-builder --linux deb rpm AppImage --publish never   # or --mac dmg --universal (on a Mac), --win nsis
```

A Windows installer built on Linux needs Wine (electron-builder's `electronuserland/builder:wine` image has it).

The icons are `build/icons/`, rendered from the office's mark by `scripts/app_icons.py`; every system's icon is made
from the 512.

The simulation of its screens, driving the same `src/ui/` files with a stand-in for the app's bridge:
`sim/index.html` (how to serve it is in its header).

## How it ships

`.github/workflows/desktop-app.yml` builds the installers on every version tag, on GitHub's own machines in the public
copy, and attaches them to that version's release:

| system | the file | installs to |
|---|---|---|
| Windows 10/11 x64 | `dgo-desktop-win-x64.exe` | this user's programs, no administrator; the Start menu and the desktop |
| macOS 13+ (Electron 45's floor), Apple silicon and Intel | `dgo-desktop-mac-universal.dmg` | Applications (dragged there) |
| Debian, Ubuntu | `dgo-desktop-linux-amd64.deb` | the launcher's list of apps |
| Fedora, RHEL | `dgo-desktop-linux-x86_64.rpm` | the launcher's list of apps |
| any Linux | `dgo-desktop-linux-x86_64.AppImage` | wherever it is put |

The names never carry the version, so `https://github.com/bina-solution/digital-office/releases/latest/download/<name>`
is always the newest. The docs' download page, with each system's first-run warning, is
`docs/src/content/docs/{he,en}/use/desktop-app.md`.

## Not yet — the owner's accounts (DGO-1980, «בעלים»)

- **Signing.** The builds are unsigned (macOS: ad-hoc), so Windows shows SmartScreen («More info → Run anyway») and
  macOS refuses the first open until «Open Anyway» in Privacy & Security. Waiting on:
  - Apple's Developer ID, the hardened runtime and notarization;
  - a Windows code-signing certificate, and the Microsoft Store.
- **Updates** (electron-updater, stable and beta channels) need signed builds and the download's own domain.
- **The ≤5 MB `dgo-install`** stays the download, and its signed manifest installs this app (the research, §5.1).
