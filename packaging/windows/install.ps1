# NOTE: ASCII ONLY. Windows PowerShell 5.1 reads a BOM-less .ps1 as the system ANSI codepage,
# so a UTF-8 em dash or arrow becomes mojibake and can break parsing outright.
# install.ps1  -  import the BinaOS distro and bring the stack up. Runs NON-ELEVATED.
#
# Everything here is deliberately non-admin. `wsl --import` needs no elevation, and doing it from
# an elevated context can register the distro under a different profile when Windows Admin
# Protection is enabled. The only admin step in the whole product (enabling VirtualMachinePlatform
# and writing the hosts block) happens in the installer's own elevated child, not here.
param(
  [Parameter(Mandatory=$true)][string]$AppDir,
  [Parameter(Mandatory=$true)][string]$Version,
  [string]$Distro = 'BinaOS'
)
$ErrorActionPreference = 'Stop'
function Say($m) { Write-Host "==> $m" }

$installDir = Join-Path $AppDir 'distro'
$rootfs     = Join-Path $AppDir 'binaos-rootfs.tar.gz'
$images     = Join-Path $AppDir 'images.tar.zst'

if (-not (Test-Path $rootfs)) { throw "rootfs missing: $rootfs" }

# A stale WSL is a realistic field condition and several flags below need 2.4.4+.
# NOTE: `wsl --version` does NOT exist on the inbox Windows 10 wsl.exe - it answers
# "Invalid command line option: --version". That is informational here, not a failure.
$wslVer = (wsl.exe --version 2>$null | Select-Object -First 1)
Say "WSL: $wslVer"

# THE WSL2 KERNEL, and this is the one that stops a real Windows 10 machine dead.
#
# Enabling the Microsoft-Windows-Subsystem-Linux and VirtualMachinePlatform features is NOT enough
# on Windows 10: the WSL2 kernel ships as a separate MSI. Without it `wsl --import ... --version 2`
# fails with
#
#     WSL 2 requires an update to its kernel component. https://aka.ms/wsl2kernel
#     The process tried to write to a nonexistent pipe.
#
# and the installer dies at its first real step. Found by installing on a clean Windows 10 guest -
# a developer box always already has this, which is exactly why it went unnoticed.
#
# The MSI travels IN the payload rather than being downloaded here. Fetching it at install time
# would put a network dependency in the middle of a product whose whole premise is that one file is
# enough, and would fail on precisely the air-gapped machines this format exists for.
$kernelMsi = Join-Path $AppDir 'wsl_update_x64.msi'
$kernelPresent = Test-Path "$env:SystemRoot\System32\lxss\tools\kernel"
if (-not $kernelPresent) {
  if (Test-Path $kernelMsi) {
    Say "installing the WSL2 kernel (Windows 10 needs it; the feature flags alone are not enough)"
    $p = Start-Process msiexec.exe -ArgumentList '/i', "`"$kernelMsi`"", '/quiet', '/norestart' -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "the WSL2 kernel package failed to install (msiexec $($p.ExitCode))" }
    wsl.exe --set-default-version 2 2>$null | Out-Null
  } else {
    throw ("This machine has no WSL2 kernel and the installer did not ship one. " +
           "Install it from https://aka.ms/wsl2kernel and run this again.")
  }
}

# Idempotent re-install: unregister only OUR distro, never the user's.
$existing = @(wsl.exe -l -q 2>$null) -replace ([char]0), '' | Where-Object { $_.Trim() -eq $Distro }
if ($existing) {
  Say "existing $Distro found  -  unregistering (its docker volumes will be destroyed)"
  wsl.exe --terminate $Distro 2>$null | Out-Null
  wsl.exe --unregister $Distro | Out-Null
}

New-Item -ItemType Directory -Force -Path $installDir | Out-Null

# STREAM the rootfs from stdin so it never lands on disk a second time. `wsl --import <dir> -`
# reads the tarball from stdin and streams it over a socket straight into bsdtar inside the VM.
# Verified working; this is what keeps peak extra disk at ~1x payload rather than 2x.
Say "importing $Distro (streaming, nothing staged)"
cmd.exe /c "type `"$rootfs`" | wsl.exe --import $Distro `"$installDir`" - --version 2"
if ($LASTEXITCODE -ne 0) { throw "wsl --import failed ($LASTEXITCODE)" }

# NOT --set-default: an imported distro is already non-default, and the user's existing Ubuntu
# must stay their default.
Say "distro imported"

# Give systemd a moment; dockerd is a systemd unit inside the distro.
wsl.exe -d $Distro -e /bin/sh -c 'for i in $(seq 1 60); do systemctl is-system-running --quiet 2>/dev/null && break; sleep 1; done' | Out-Null

if (Test-Path $images) {
  Say "loading images (the long part)"
  # --long=27 must match what build-bundle.sh compressed with; zstd's decompressor defaults to a
  # 128 MiB window and a larger windowLog at compression time would make this fail.
  $wslImages = (wsl.exe -d $Distro -e wslpath -a "$images").Trim()
  wsl.exe -d $Distro -e /bin/sh -c "zstd -dc --long=27 '$wslImages' | docker load"
  if ($LASTEXITCODE -ne 0) { throw "docker load failed ($LASTEXITCODE)" }
}

# Fit the compose to THIS machine before starting anything. Same rule as the Linux installer, and
# the same hard failure without it: deploy.resources.limits.cpus carries production sizing (apitools
# asks for 6) and Docker REFUSES rather than warns when a limit exceeds the host -
#   range of CPUs is from 0.01 to 4.00, as there are only 4 CPUs available
# - so the container never starts and `docker compose up` exits non-zero. The core count that
# matters is the WSL VM's, not the Windows box's, so it is read from inside the distro.
#
# No --socket here, unlike Linux: inside this distro /var/run/docker.sock IS our engine, because
# there is no other Docker in it. On Linux we install alongside the user's own daemon and have to
# say which one we mean.
Say "adapting the compose to this machine"
wsl.exe -d $Distro -e /bin/sh -c 'python3 /opt/binaos/adapt-host.py /opt/binaos/.generated/compose.runtime.yml --cores "$(nproc)"'
if ($LASTEXITCODE -ne 0) { throw "could not adapt the compose to this host ($LASTEXITCODE)" }

Say "starting the stack"
wsl.exe -d $Distro -e systemctl start binaos.service

# THE KEEPALIVE, and it is not optional. WSL terminates an idle instance ~15s after the last USER
# process exits, and a systemd service does not count as one  -  Microsoft's own docs say "systemd
# services will NOT keep your WSL instance alive". Without this the whole stack dies seconds after
# the installer returns. A per-distro scheduled task is used rather than .wslconfig's
# instanceIdleTimeout, which is undocumented AND per-user global  -  it would also stop the user's
# existing Ubuntu and docker-desktop from ever idling out.
#
# RestartCount is 999 rather than a handful. `sleep infinity` should never exit, so a restart budget
# looks academic - but it exits whenever the distro is terminated for any reason (`wsl --shutdown`,
# a memory-pressure reap, a host sleep/resume), and each one burns a restart. With a budget of 3 the
# task retires silently on the fourth, and from then on the whole stack dies ~15s after the user
# closes their last window. That is indistinguishable from the product being broken, and there is
# nothing in any log to point at a scheduled task that stopped being scheduled. There is no cost to
# a high count: each restart is one process that immediately blocks.
Say "registering the keepalive task"
$action  = New-ScheduledTaskAction -Execute 'wsl.exe' -Argument "-d $Distro -e sleep infinity"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$set     = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
             -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "BinaOS-keepalive" -Action $action -Trigger $trigger `
  -Settings $set -Force | Out-Null
Start-ScheduledTask -TaskName "BinaOS-keepalive"

Say "BinaOS $Version installed."
Write-Host ""
Write-Host "  Open http://localhost/ in Chrome or Edge."
Write-Host ""
# *.localhost does NOT resolve on Windows  -  the OS resolver does not implement RFC 6761's rule.
# Chromium and Firefox resolve it internally so browsers work, but curl/Node/.NET/PowerShell do
# not. Fixing that needs hosts entries, which need admin, so it is offered rather than assumed.
Write-Host "  Note: subdomain URLs like http://n8n.localhost/ work in Chrome, Edge and Firefox."
Write-Host "        For curl/scripts, run 'BinaOS: enable hostnames' from the Start menu (needs admin)."
