<#
    platform-disk-trim.ps1 - give C: back the blocks the distro's ext4 has freed (DGO-1393).

    ASCII ONLY, DELIBERATELY - same reason as platform-keepalive.ps1: PowerShell 5.1 reads a file without a BOM as
    ANSI, and a non-ASCII character shifts bytes and breaks quote pairing.

    WHY THIS EXISTS
    ---------------
    The distro's ext4.vhdx is a SPARSE file and its ext4 is mounted with discard, so what is deleted inside the VM goes
    back to C: as it is freed - but only what the guest tells the disk. Measured 2026-11-05 on the HP: C: at 100% (3.7 GB
    free), the file holding 166 GB of C: for 99 GB of data, and the distro's own fstrim.timer never fired (enabled, no
    stamp: it does not run under WSL). One `fstrim -av` gave 24.3 GB back to C: (13:03 UTC). It needs no administrator
    and stops nothing: it runs INSIDE the distro, as root, the way every check of the health tick already reaches it
    (wsl.exe -u root).

    WHEN (platform-keepalive.ps1 -HealthCheck asks, every 5 minutes): when the office asks for one
    (<checkout>\data\power\fstrim.request), after every start of the WSL VM (the discard limit below lives only until
    it restarts), by itself once a day, and every hour while C: is under -MinFreeGB. Never
    two at once. The tick only decides; the trim runs in a hidden PowerShell of its own (-Run, started the way the power
    hold starts its holder), so a long one never holds the tick. <checkout>\data\power\fstrim.json says when the last
    one started, why, C:'s free bytes before and after, the exit code and fstrim's own words.
#>
[CmdletBinding()]
param([string]$Distro = 'Ubuntu', [int]$MinFreeGB = 20, [switch]$Run, [string]$Why = '')

$ErrorActionPreference = 'Stop'
$Power = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'data\power'
if (-not (Test-Path -LiteralPath $Power)) { return }
$state = Join-Path $Power 'fstrim.json'
$req   = Join-Path $Power 'fstrim.request'

function Get-CFree { try { return [int64](Get-PSDrive -Name C).Free } catch { return [int64]-1 } }

function Get-VmKey {
    # which start of the WSL VM this is: its process's creation time, as UTC ticks - a name, not a clock reading, so a
    # clock that moves cannot make an old VM look new. vmmemWSL first (plain vmmem also names other VMs on older
    # builds). Empty when there is no VM or WMI does not answer in time.
    try {
        foreach ($n in @('vmmemWSL', 'vmmem')) {
            $vm = @(Get-CimInstance Win32_Process -Filter ("Name='" + $n + "'") -OperationTimeoutSec 15 -ErrorAction Stop |
                    Sort-Object CreationDate | Select-Object -Last 1)
            if ($vm.Count -gt 0 -and $vm[0].CreationDate) { return [string]$vm[0].CreationDate.ToUniversalTime().Ticks }
        }
    } catch { }
    return ''
}

function Write-State {
    param([hashtable]$S)
    $tmp = $state + '.tmp'
    [System.IO.File]::WriteAllText($tmp, (ConvertTo-Json -Compress -InputObject $S), (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination $state -Force
}

if ($Run) {
    # the trim itself: wsl.exe's own exit code and words are kept, so a trim that could not start is seen, not guessed
    $ErrorActionPreference = 'Continue'      # from here nothing may stop the trim: wsl.exe's stderr is an answer, not an exception
    $env:WSL_UTF8 = '1'                      # wsl.exe's own messages in UTF-8, not UTF-16, so fstrim.json can carry them
    $s = @{ last_started = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); why = $Why; c_free_before = (Get-CFree); running = $true }
    try { Write-State $s } catch { }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    # First, each discard kept within one 1 MiB block of the .vhdx: a longer one that crosses a block the file never
    # allocated is dropped by the host for good (microsoft/WSL#42179 - about a quarter of every delete, measured there),
    # which is how the HP's file came to hold 43 GB that no later trim recovers. The limit lives until the VM restarts,
    # so every run sets it again. No double quote inside: PowerShell 5.1 hands those to wsl.exe unescaped.
    $sh = 'd=$(basename $(findmnt -n -o SOURCE /)); echo 1048576 > /sys/block/$d/queue/discard_max_bytes; ' +
          'echo discard_max_bytes of $d: $(cat /sys/block/$d/queue/discard_max_bytes); fstrim -av'
    $o = & wsl.exe -d $Distro -u root -e sh -c $sh 2>&1 | Out-String
    $s['exit'] = $LASTEXITCODE
    $s['output'] = $o.Trim()
    $s['seconds'] = [int]$sw.Elapsed.TotalSeconds
    $s['c_free_after'] = (Get-CFree)
    $s['running'] = $false
    # the VM this trim reached, kept only when it worked: a trim that failed right after a VM start is tried again
    if ($s['exit'] -eq 0) { $s['vm_started'] = Get-VmKey }
    try { Write-State $s } catch { }
    return
}

$last = [int64]0
$seen = ''
try {
    $st0  = Get-Content -LiteralPath $state -Raw | ConvertFrom-Json
    $last = [int64]$st0.last_started
    if ($st0.vm_started) { $seen = [string]$st0.vm_started }
} catch { }
$now   = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$free  = Get-CFree
$low   = ($free -ge 0) -and ($free -lt ([int64]$MinFreeGB * 1GB))
$asked = Test-Path -LiteralPath $req
# A VM that no trim has reached yet has lost the discard limit (it lives until the VM restarts): the WSL restart of
# 2026-11-05 15:00 UTC left it off until the next daily run. A successful trim records the VM it reached (vm_started);
# a VM whose start is not that one is due - at most every 10 minutes, so a trim that keeps failing is not a storm.
$vmKey = Get-VmKey
$boot  = ($vmKey -ne '') -and ($vmKey -ne $seen) -and (($now - $last) -ge 600)
if (-not ($asked -or $boot -or (($now - $last) -ge 86400) -or ($low -and (($now - $last) -ge 3600)))) { return }

# never two at once: a trim still running (its PowerShell, or a wsl.exe running fstrim) is left to finish
$running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -and (
             ($_.Name -eq 'powershell.exe' -and $_.CommandLine -like '*platform-disk-trim.ps1*' -and $_.CommandLine -like '*-Run*') -or
             ($_.Name -eq 'wsl.exe' -and $_.CommandLine -like '*fstrim*')) }).Count
if ($running -gt 0) { return }

if ($asked) { Remove-Item -LiteralPath $req -Force -ErrorAction SilentlyContinue }
$why = if ($asked) { 'asked' } elseif ($boot) { 'boot' } elseif ($low) { 'low' } else { 'daily' }
# the path quoted: PowerShell 5.1 joins these with spaces and quotes nothing
Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
    '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', ('"' + $PSCommandPath + '"'), '-Run', '-Distro', $Distro, '-Why', $why) | Out-Null
