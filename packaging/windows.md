# Windows — implementable spec

Target: a signed `.exe` that imports an embedded Linux rootfs as a WSL2 distro, runs dockerd inside
it, and brings the stack up. Windows is sequenced **first**: `wsl --import` is the cheapest runtime
path of the three, and Windows is the only platform with no privileged-port problem.

Findings below marked **[TESTED]** were executed live on Windows 11 25H2 build 26200.8894 with
WSL 2.1.5, from a confirmed **non-elevated** shell.

## The shape

```
[elevated, once, only if VMP is off]   DISM enable WSL + VirtualMachinePlatform → reboot
                                       write the hosts block
[non-elevated, everything after]       wsl --import  →  dockerd  →  compose up
```

**[TESTED] `wsl --import` needs no elevation**, and **does not touch the default distro** — after
importing four test distros, `HKCU\…\Lxss\DefaultDistribution` still pointed at Ubuntu and
`wsl -l -v` still starred it. Non-default is free; never call `--set-default`. Address the distro
explicitly with `-d BinaOS` everywhere.

## Building the rootfs

`docker export` is sufficient and is what Microsoft's own doc prescribes. Use `docker create` +
`docker export`, not `docker run`, so nothing executes:

```bash
cid=$(docker create bina-rootfs); docker export "$cid" -o raw.tar; docker rm "$cid"
mkdir rootfs && tar -C rootfs -xf raw.tar
rm -f rootfs/.dockerenv rootfs/etc/resolv.conf rootfs/etc/hostname
: > rootfs/etc/machine-id     # empty, not absent — systemd regenerates per install
tar --numeric-owner --sort=name --mtime='@0' --owner=0 --group=0 --xattrs \
    -C rootfs -c . | gzip -n --best > install.tar.gz
```

`--sort=name --mtime=@0` plus `gzip -n` give byte-reproducible output, which matters because the
installer is signed. WSL extracts with `bsdtar -x -p --xattrs --numeric-owner`, so match those flags.

Must include: a uid-0 root in `/etc/passwd`, and `/etc/wsl.conf` (`root:root`, `0644`). Must **not**
include `/etc/resolv.conf`, password hashes, a kernel, or an initramfs. No `init` binary is needed —
WSL injects its own PID 1.

`/etc/wsl.conf` needs `[boot] systemd=true`, plus masking the units Microsoft lists as breaking
under WSL: `systemd-resolved`, `systemd-networkd`, `NetworkManager`, `systemd-tmpfiles-*`,
`tmp.mount`.

**Format: ship `.tar.gz`.** **[TESTED]** `.tar`, `.tar.gz`, `.tar.xz` and `.tar.zst` all imported
successfully on 2.1.5 — WSL's importer is libarchive, which sniffs compression. But `wsl --export
--format` only advertises `tar, tar.gz, tar.xz`, so zstd on the import side is
empirically-working-but-undocumented and could regress silently. Keep zstd for the *image* payload,
where `docker load` handles it natively.

## Pre-bake the images — do not `docker load` at first run

Same correction as macOS ([macos.md](macos.md)): build the rootfs in CI with every pinned image
already pulled into `/var/lib/docker`. First run becomes a boot, not a 25-minute import, and peak
disk drops accordingly.

## Two failure modes that will bite

**1. WSL kills an idle instance ~15 s after the last user process exits — and a daemon started from
`[boot] command` does not count as a user process.** ([WSL#8661](https://github.com/microsoft/WSL/issues/8661),
still open.) Symptom: the stack starts, then the whole distro dies seconds later. Microsoft's own
systemd doc says it plainly: *"systemd services will NOT keep your WSL instance alive."*

The fix is a **Windows-side keepalive** — one long-lived `wsl.exe -d BinaOS -e sleep infinity` held
by a hidden tray process or a logon Scheduled Task. Per-distro, disturbs nothing else.

Do **not** reach for `.wslconfig` `[general] instanceIdleTimeout=-1`. It is a real parsed key in
WSL's source but is absent from Microsoft's documented `.wslconfig` table, and — decisively — it is
**per-user global**, so it would also stop the user's existing Ubuntu and `docker-desktop` from ever
idling out. That violates the "don't disturb what's already there" constraint.

**2. Never set `"userland-proxy": false`.** WSL's localhost forwarding works by polling `sock_diag`
netlink every second for sockets in `TCP_LISTEN` and starting a Windows-side relay per socket.
Docker's default `docker-proxy` creates such a socket; with `userland-proxy: false` there is only
iptables DNAT and no listening socket, so **forwarding goes silently dead**. Verified absent from
this repo — keep it that way.

Consequences of that mechanism, all load-bearing: **TCP only** (published UDP ports are never
relayed), and up to ~1 s lag between container start and reachability.

Traefik on `:80/:443` is therefore reachable at `http://localhost/` from Windows with zero config.
Windows has no privileged-port restriction.

## `*.localhost` does not resolve on Windows

**[TESTED]** `[System.Net.Dns]::GetHostAddresses('traefik.localhost')` → *"No such host is known"*,
while plain `localhost` resolves. Windows' resolver does not implement the RFC 6761 `*.localhost`
rule. Chromium and Firefox resolve it internally so **browsers work unaided**, but `curl`, Node,
.NET, PowerShell and every health-check script fail.

**[TESTED]** a non-elevated append to `%WINDIR%\System32\drivers\etc\hosts` is denied, and the file
has no wildcard support. So the hosts block goes in the one elevated step we already need, as a
delimited idempotent region:

```
# BEGIN BINA
127.0.0.1 traefik.localhost
…
# END BINA
```

Use `127.0.0.1` explicitly — this also dodges `localhost → ::1`-first ordering, which can otherwise
miss an IPv4-only publish.

> **Derive the list from the compiler, not from `.env`.** The compiled config currently yields 38
> `*.localhost` names, and several — `chess`, `librechat`, `rocketchat`, `chatbase`, `autopilot`,
> `ktivayehudit-clone2` — are stale `*_BASE_URL` entries in `.env` for apps that no longer exist.
> An installer that writes its hosts block from `.env` would write entries for services that were
> never installed. `reconcile.py` knows the real routing set; use it.

## Preflight, without elevation

```powershell
$build = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber
$vmp   = (Get-CimInstance Win32_OptionalFeature -Filter "Name='VirtualMachinePlatform'").InstallState -eq 1
$hv    = (Get-CimInstance Win32_ComputerSystem).HypervisorPresent
```

**[TESTED]** all three run non-elevated. The key distinction: `Get-WindowsOptionalFeature -Online`
(the DISM module) **requires elevation**; the `Win32_OptionalFeature` WMI class does not.
`InstallState` 1 = Enabled, 2 = Disabled.

Two traps hit live:
- **`ProductName` lies** — it reads `"Windows 10 Pro"` on this Windows 11 build 26200 box. Gate on
  `CurrentBuildNumber >= 19041`, never on the product name.
- **`Win32_Processor.VirtualizationFirmwareEnabled` returned `False`** on a machine where
  virtualization demonstrably works. Once a hypervisor is loaded it is unreliable — gating on it
  produces false negatives. Use `HypervisorPresent = True` as the positive signal.

If elevation is needed: `wsl.exe --install --no-distribution`, or the two explicit DISM calls. **A
reboot is strictly required** — VMP loads a boot-time hypervisor component; `/norestart` only defers
it. Detect via DISM exit **3010**, then schedule a `RunOnce` resume.

⚠️ Do the `--import` **strictly non-elevated**. On machines with Windows Admin Protection enabled,
running it from an elevated context can register the distro under a different profile.

## Packaging the installer

| | Verdict |
|---|---|
| **NSIS** | ❌ **Disqualified** — official docs cap installers at 2 GB. |
| **Inno Setup** | ✅ **Recommended** — disk spanning is required only above ~4.2 GB, so a 3–3.5 GB single `.exe` is fine. Has `SignTool` and `SignedUninstaller`. |
| **WiX / MSI** | ⚠️ Poor fit — the transactional file-copy model buys nothing here, and `%WINDIR%\Installer` caching risks doubling peak disk. |
| **7-Zip SFX** | ⚠️ Stages to `%TEMP%` — precisely the failure being avoided. |

**The finding that solves the disk problem: [TESTED] `wsl --import <Name> <Dir> - --version 2` reads
the tarball from stdin**, and WSL streams it over a socket straight into `bsdtar` inside the VM. The
rootfs never has to exist as a file. Combined with extracting the payload to the *destination*
directory rather than `{tmp}`, peak extra disk is **≈1× payload, not 2×**, and nothing lands on
`%TEMP%`.

Set `Compression=none` / `Flags: nocompression` — the payload is already gzip/zstd, so recompressing
costs build time and gains ~0%.

**[TESTED] You cannot append a payload to an already-signed stub.** Copying a signed `notepad.exe`
(`Get-AuthenticodeSignature` → `Valid`) and appending 1 MB flipped it to **`NotSigned`**: appending
after the PE overlay moves the certificate table and voids the signature. Concatenating payload +
stub and *then* signing is how every SFX works, but the ordering is mandatory — **build fully, sign,
never touch the bytes again.**

## Uninstall — and the trap in it

`wsl --unregister` deletes `ext4.vhdx` and the `HKCU\…\Lxss\{GUID}` key. **[TESTED]** it leaves the
install directory behind (empty), and removes none of: `.wslconfig`, the WSL optional components,
hosts entries, shortcuts, or firewall rules.

**Docker volumes live inside the distro**, at `/var/lib/docker/volumes` inside `ext4.vhdx`. There is
no Windows-side location. **So `wsl --unregister` destroys every volume in the stack.** Offer an
explicit "keep my data / delete everything" choice; the default must not silently destroy 40
services' worth of state. Preserve with `wsl --export BinaOS backup.tar.gz` before unregistering.

## Signing

**Azure Trusted Signing is now "Azure Artifact Signing"**, GA January 2026 — docs moved to
`/azure/artifact-signing/`. Basic tier **$9.99/mo** (5,000 signatures); requires a
pay-as-you-go/EA subscription. Certificates are 72-hour and renewed daily in Microsoft-managed HSMs,
so **timestamping is mandatory** (`/tr http://timestamp.acs.microsoft.com /td SHA256`) — with a
valid RFC 3161 countersignature the signature stays valid indefinitely.

**EV certificates no longer bypass SmartScreen, and Microsoft now says so explicitly:** *"EV
certificates no longer bypass SmartScreen. … Paying a premium for EV solely to avoid SmartScreen
warnings is no longer justified."* OV and EV sit in the same row — warning shown until reputation
accrues per-hash and per-publisher, with no published threshold and no submission path. What signing
still buys is the **verified publisher name in the dialog**.

Since June 2023 the CA/Browser Forum requires private keys on FIPS 140-2 L2 hardware for OV as well
as EV, which makes a USB token unusable in CI — hence Artifact Signing (~$120/yr) versus ~$700/yr OV
or ~$970/yr EV.

## Open questions

- `userland-proxy: false` breaking localhost forwarding is a strong inference from WSL's
  `sock_diag`-based relay, not a documented Microsoft statement. Worth a 10-minute empirical check.
- `.tar.zst` import works empirically but is officially unsupported; could regress.
- `instanceIdleTimeout` is real in WSL's source but undocumented — do not build the only keepalive on it.
- Live tests ran on WSL **2.1.5**. `--manage --set-default-user`, `--install --from-file` and
  `instanceIdleTimeout` need 2.4.4–2.5+. The installer should check `wsl --version` and branch; a
  stale WSL is a realistic field condition.
