<#
    platform-power-hold.ps1 - the Windows half of the office's power policy.

    ASCII ONLY, DELIBERATELY - same reason as platform-keepalive.ps1: PowerShell 5.1 reads a file
    without a BOM as ANSI, and a non-ASCII character shifts bytes and breaks quote pairing.

    WHY THIS EXISTS
    ---------------
    The office runs inside a VM on this laptop, and a sleeping laptop freezes the VM and every agent
    in it (measured 2026-09-29: 28 of 43 agent-hours spent frozen). The platform already DECLARES what
    should happen - the machine app's /api/power, data\power\policy.json, defaults lid=run lock=run -
    and on macOS packaging/macos/power-agent.py enforces it. On Windows nothing did: /api/power read
    "agent": "absent" on 2026-10-09 while the owner was about to leave the office running unattended
    over Shabbat.

    WHAT IT DOES, on every tick of the Platform-OS-Health task (every 5 minutes):
      1. reads the office's declared policy (data\power\policy.json; absent = the defaults, run);
      2. best effort asks Windows to stay awake: the AC standby/hibernate timeouts and the AC lid
         action. powercfg needs elevation - when it is not there, the exit code says so and it is
         reported, never hidden;
      3. keeps ONE holder process alive (this same script with -Hold). The holder calls
         SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED) every 15 seconds and refreshes
         data\power\status.json, which the machine service reads: that is what turns /api/power's
         "agent" from absent into running. No elevation is needed for the holder.
      4. writes what it did to data\power\power-hold.log - the durable record, readable from the
         office's own checkout.

    A FACT, NEVER A FAILURE. Every step is wrapped: whatever goes wrong here must never break
    platform-keepalive.ps1, which is the thing that brings the stack back after a reboot.
#>
[CmdletBinding()]
param(
    [string]$Repo = '',
    [switch]$Hold
)

$ErrorActionPreference = 'Continue'

function Resolve-Repo {
    param([string]$Given)
    if ($Given -and (Test-Path $Given)) { return $Given }
    # scripts\windows\platform-power-hold.ps1 -> scripts\windows -> scripts -> <repo>
    try { return (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) } catch { return '' }
}

function Write-Atomic {
    param([string]$Path, [string]$Text)
    try {
        $tmp = $Path + '.tmp'
        [System.IO.File]::WriteAllText($tmp, $Text, (New-Object System.Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $tmp -Destination $Path -Force -ErrorAction Stop
        return $true
    } catch { return $false }
}

function Write-HoldLog {
    param([string]$Dir, [string]$Line)
    try {
        $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        Add-Content -LiteralPath (Join-Path $Dir 'power-hold.log') -Value ($stamp + ' ' + $Line) -Encoding utf8
    } catch { }
}

function Get-Holders {
    # @() around the whole thing, ALWAYS: a function that returns an empty array unwraps to nothing,
    # and `$null.Count` is $null - which is how the first cut wrote `"holders":}` and made
    # status.json invalid JSON, so the machine service read it as absent while the holder ran.
    try {
        return @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction Stop |
                 Where-Object { $_.CommandLine -and $_.CommandLine -like '*platform-power-hold.ps1*' -and $_.CommandLine -like '*-Hold*' })
    } catch { return @() }
}

function Test-Admin {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}

$repo = Resolve-Repo -Given $Repo
if (-not $repo) { return }
$dir = Join-Path $repo 'data\power'
if (-not (Test-Path $dir)) { return }

# ---------------------------------------------------------------- holder mode
if ($Hold) {
    $pid_ = $PID
    try {
        Add-Type -Namespace DgoPower -Name Native -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern uint SetThreadExecutionState(uint esFlags);
'@ -ErrorAction Stop
    } catch { Write-HoldLog -Dir $dir "holder: SetThreadExecutionState unavailable ($_)" }
    Write-HoldLog -Dir $dir "holder starting (pid $pid_)"
    # A HOLDER THAT LEAVES WHEN ITS OWN FILE CHANGES. PowerShell reads a script once, at start: a
    # holder kept running would go on writing whatever the old text said, and an edit here would
    # never reach the file it writes (measured 2026-10-09: the first cut wrote invalid JSON and the
    # running holder would have kept doing it). So the file's own LastWriteTime is the version, and
    # a change ends this process - the next 5-minute tick starts a fresh one.
    $scriptAt = (Get-Item -LiteralPath $PSCommandPath).LastWriteTime
    # ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001), as a decimal literal on purpose:
    # PowerShell 5.1 reads a hex literal that fills 32 bits as a NEGATIVE Int32 (0x80000001 -> -2147483647),
    # which then refuses to convert to the UInt32 the API wants.
    $flags = [uint32]2147483649
    while ($true) {
        try { $null = [DgoPower.Native]::SetThreadExecutionState($flags) } catch { }
        $doc = '{"updated_at":' + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() +
               ',"os":"windows","hold":true,"holder_pid":' + $pid_ +
               ',"holders":' + @(Get-Holders).Count + '}'
        $null = Write-Atomic -Path (Join-Path $dir 'status.json') -Text $doc
        try { if ((Get-Item -LiteralPath $PSCommandPath).LastWriteTime -ne $scriptAt) {
                Write-HoldLog -Dir $dir "holder exiting (pid $pid_): its own file changed on disk"
                return } } catch { }
        Start-Sleep -Seconds 15
    }
    return
}

# ---------------------------------------------------------------- policy mode (one tick)
$lidRun  = $true
$lockRun = $true
$batteryFloor = 20
try {
    $policy = Get-Content -LiteralPath (Join-Path $dir 'policy.json') -Raw | ConvertFrom-Json
    if ($policy.lid  -and $policy.lid.ac)  { $lidRun  = ($policy.lid.ac  -eq 'run') }
    if ($policy.lock) {
        if ($policy.lock.ac)      { $lockRun = ($policy.lock.ac -eq 'run') }
        elseif ($policy.lock.battery) { $lockRun = $false }
    }
    if ($policy.battery_floor) { $batteryFloor = [int]$policy.battery_floor }
} catch { }

$admin   = Test-Admin
$applied = @()

if ($lidRun -or $lockRun) {
    # SUB_BUTTONS / LIDACTION, value 0 = "do nothing". Guards are GUIDs, not names - the names are
    # localized on a Hebrew Windows and cannot be passed here.
    $subButtons = '4f971e89-eebd-4455-a8de-9e59040e7347'
    $lidAction  = '5ca83367-6e45-459f-a27b-476b1d01c936'
    $steps = @(
        @{ name = 'standby-timeout-ac=0';   args = @('/change', 'standby-timeout-ac', '0') },
        @{ name = 'hibernate-timeout-ac=0'; args = @('/change', 'hibernate-timeout-ac', '0') },
        @{ name = 'lid-ac=do-nothing';      args = @('/setacvalueindex', 'SCHEME_CURRENT', $subButtons, $lidAction, '0') }
    )
    foreach ($s in $steps) {
        try {
            $null = & powercfg.exe @($s.args) 2>&1
            if ($LASTEXITCODE -eq 0) { $applied += $s.name } else { $applied += ($s.name + ':rc=' + $LASTEXITCODE) }
        } catch { $applied += ($s.name + ':threw') }
    }
    if ($applied -contains 'lid-ac=do-nothing') {
        $null = & powercfg.exe /setactive SCHEME_CURRENT 2>&1
    }
}

# A HOLDER OLDER THAN THIS FILE IS STALE, and is stopped. PowerShell reads a script once, at start, so
# a holder that began before the last edit is enforcing the text that was there then - it would never
# pick up a fix, and it would keep writing the file it was told to write. Measured 2026-10-09: the
# first cut wrote invalid JSON every 15s, and editing the file changed nothing about it.
$scriptAt = (Get-Item -LiteralPath $PSCommandPath).LastWriteTime
$stopped  = 0
foreach ($h in @(Get-Holders)) {
    try {
        if ($h.CreationDate -and ($h.CreationDate -lt $scriptAt)) {
            Stop-Process -Id $h.ProcessId -Force -ErrorAction SilentlyContinue
            $stopped++
        }
    } catch { }
}
if ($stopped -gt 0) { Write-HoldLog -Dir $dir ("stopped " + $stopped + " holder(s) older than this file") }

$holders = @(Get-Holders).Count
$started = $false
if ($lidRun -and $holders -eq 0) {
    try {
        Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', $PSCommandPath, '-Hold', '-Repo', $repo) -ErrorAction Stop | Out-Null
        $started = $true
    } catch { }
}

$status = '{"updated_at":' + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() +
          ',"os":"windows","hold":' + $(if ($lidRun) { 'true' } else { 'false' }) +
          ',"admin":' + $(if ($admin) { 'true' } else { 'false' }) +
          ',"applied":[' + (($applied | ForEach-Object { '"' + $_ + '"' }) -join ',') + ']' +
          ',"holders":' + ($holders + $(if ($started) { 1 } else { 0 })) +
          ',"policy":{"lock":"' + $(if ($lockRun) { 'run' } else { 'sleep' }) +
          '","lid":"' + $(if ($lidRun) { 'run' } else { 'sleep' }) + '"}' +
          ',"battery_floor":' + $batteryFloor + '}'
$null = Write-Atomic -Path (Join-Path $dir 'status.json') -Text $status
Write-HoldLog -Dir $dir ("tick: admin=" + $admin + " holders=" + $holders + " started=" + $started +
                         " stopped=" + $stopped + " applied=" + ($applied -join ','))
