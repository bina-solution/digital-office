# NOTE: ASCII ONLY. Windows PowerShell 5.1 reads a BOM-less .ps1 as the system ANSI codepage,
# so a UTF-8 em dash or arrow becomes mojibake and can break parsing outright.
#
# uninstall.ps1 - remove BinaOS. Runs NON-ELEVATED, as the installing user.
#
# THE TRAP THIS EXISTS TO AVOID
# Docker volumes live INSIDE the distro, at /var/lib/docker/volumes within ext4.vhdx. There is no
# separate Windows-side location. So `wsl --unregister` destroys every volume in the stack - all
# 40 services' worth of state - and it does so silently. The default here therefore OFFERS to keep
# the data, and only destroys it when explicitly told to.
param(
  [Parameter(Mandatory=$true)][string]$AppDir,
  [string]$Distro = 'BinaOS',
  [switch]$Purge,
  [string]$BackupTo = ''
)
$ErrorActionPreference = 'Continue'
function Say($m) { Write-Host "==> $m" }

# The keepalive is a scheduled task, not part of the distro, so it outlives an unregister.
Say "removing the keepalive task"
Unregister-ScheduledTask -TaskName 'BinaOS-keepalive' -Confirm:$false -ErrorAction SilentlyContinue

$present = @(wsl.exe -l -q 2>$null) -replace ([char]0), '' | Where-Object { $_.Trim() -eq $Distro }

if ($present) {
  if ($BackupTo) {
    Say "exporting $Distro to $BackupTo (this includes every docker volume)"
    wsl.exe --export $Distro $BackupTo
    if ($LASTEXITCODE -ne 0) { Write-Warning "export failed - NOT unregistering, your data is untouched"; exit 1 }
  }

  if (-not $Purge -and -not $BackupTo) {
    Write-Warning "Unregistering $Distro will permanently delete every docker volume in the stack."
    Write-Warning "Re-run with -BackupTo <path.tar.gz> to snapshot first, or -Purge to confirm deletion."
    Write-Warning "Leaving the distribution in place. Nothing was deleted."
    exit 2
  }

  Say "stopping and unregistering $Distro"
  wsl.exe --terminate $Distro 2>$null | Out-Null
  wsl.exe --unregister $Distro
} else {
  Say "$Distro is not registered - nothing to unregister"
}

# `wsl --unregister` deletes ext4.vhdx and the HKCU Lxss key but leaves the install directory
# behind (empty), so clean it up explicitly.
$installDir = Join-Path $AppDir 'distro'
if (Test-Path $installDir) {
  Say "removing $installDir"
  Remove-Item -LiteralPath $installDir -Recurse -Force -ErrorAction SilentlyContinue
}

# The hosts block, if the optional admin step ever wrote one. Sentinel-delimited so it can be
# removed surgically without touching anything else in the file. Needs admin, so it is offered
# rather than attempted.
$hosts = Join-Path $env:WINDIR 'System32\drivers\etc\hosts'
if ((Test-Path $hosts) -and (Select-String -Path $hosts -Pattern '^# BEGIN BINA' -Quiet -ErrorAction SilentlyContinue)) {
  Write-Host ""
  Write-Warning "A BinaOS block remains in $hosts. Removing it needs administrator rights:"
  Write-Warning "  Start an elevated PowerShell and run:"
  Write-Warning "    `$h = Get-Content '$hosts'; `$k = `$true; `$h | Where-Object { if (`$_ -match '^# BEGIN BINA') { `$k = `$false }; `$keep = `$k; if (`$_ -match '^# END BINA') { `$k = `$true }; `$keep } | Set-Content '$hosts'"
}

Say "BinaOS removed."
