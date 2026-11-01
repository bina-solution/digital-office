# firewall-converge.ps1 - make the Windows firewall MATCH what this office's .env declares.
#
# WHY THIS EXISTS
#   An office that another office dials (a paired office that LISTENS - apps/dgo-extend/pair_api.py)
#   declares one UDP port in .env:
#
#       DGO_WG_PUBLISH_BIND=0.0.0.0
#       DGO_WG_PUBLISH_PORT=51830
#
#   compose publishes it for `dgo-net`, and under WSL mirrored networking that port is the machine's
#   own. But Windows drops every inbound packet to WSL until a rule says otherwise (the Hyper-V
#   firewall's default inbound action is Block - measured on hp-laptop 2026-10-04: ICMP from the Mac
#   answered, UDP to the published port was silently dropped). A container cannot open that door, and
#   a command pasted by hand into an admin shell is not a declaration. So the declaration is the .env
#   line, and THIS is what applies it - the same shape as everything else here: desired state in a
#   file, converged by `bbox run`.
#
# WHAT IT OWNS
#   Exactly two rules, both named after the deployment so two offices on one machine never fight:
#     DigitalOffice-WG-<DEPLOYMENT_NAME>      Hyper-V firewall (the one that guards WSL)
#     DigitalOffice-WG-<DEPLOYMENT_NAME>-Host Windows Defender firewall (the host's own profile rules)
#   Declared  -> both exist, UDP, inbound, allow, that one port.
#   Not declared (bind empty/loopback, or no port) -> both are REMOVED. A door nobody declares is closed.
#   It never touches a rule it did not name.
#
# ELEVATION
#   Reading rules needs no rights; changing them needs an administrator, and Windows offers no way
#   around that. So the check runs unprivileged on every `bbox run` and costs nothing when the state
#   already matches; only when something must change does it ask - ONE consent prompt (UAC), for this
#   script with -Apply and nothing else. Declining is not an error: the run continues, and the note
#   says which link will not come up and why.
#
#       powershell -File scripts\windows\firewall-converge.ps1            # converge (prompts if needed)
#       powershell -File scripts\windows\firewall-converge.ps1 -Check     # report only, exit 1 on drift
param(
    [switch]$Check,
    [switch]$Apply,
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
# the WSL VM creator id - the constant the Hyper-V firewall scopes a rule to WSL with
$WslCreator = "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}"

if (-not $RepoRoot) { $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }
$envFile = Join-Path $RepoRoot ".env"

function Read-EnvValue([string]$name) {
    # LAST assignment wins, like compose; quotes and a trailing comment are not part of the value.
    if (-not (Test-Path -LiteralPath $envFile)) { return "" }
    $value = ""
    foreach ($line in [IO.File]::ReadAllLines($envFile)) {
        if ($line -match "^\s*$([regex]::Escape($name))\s*=(.*)$") {
            $value = $Matches[1].Trim()
            if ($value -match '^"(.*)"$' -or $value -match "^'(.*)'$") { $value = $Matches[1] }
        }
    }
    return $value
}

$deployment = Read-EnvValue "DEPLOYMENT_NAME"
if (-not $deployment) { $deployment = "office" }
$ruleName = "DigitalOffice-WG-$deployment"
$hostRuleName = "$ruleName-Host"
$display = "Digital Office tunnel ($deployment)"

$bind = Read-EnvValue "DGO_WG_PUBLISH_BIND"
$portText = Read-EnvValue "DGO_WG_PUBLISH_PORT"
$port = 0
[void][int]::TryParse($portText, [ref]$port)
# DECLARED = published on a non-loopback address, on a real port. Anything else publishes nothing
# reachable (the compose default binds 127.0.0.1), so no door is wanted.
$declared = ($port -ge 1 -and $port -le 65535 -and $bind -and $bind -notmatch '^(127\.|localhost$|::1$)')

function Get-Current {
    # What exists NOW, as the two facts that matter: is the rule there, and on which port.
    $state = @{ hv = $null; host = $null; hvSupported = $true }
    try {
        $r = Get-NetFirewallHyperVRule -Name $ruleName -ErrorAction Stop
        $state.hv = [string]$r.LocalPorts
    } catch [Microsoft.PowerShell.Cmdletization.Cim.CimJobException] {
        $state.hv = $null
    } catch [System.Management.Automation.CommandNotFoundException] {
        # an older Windows without the Hyper-V firewall cmdlets: WSL there is NAT'd, not mirrored, and
        # this rule has no meaning. Say so instead of failing the run.
        $state.hvSupported = $false
    } catch {
        $state.hv = $null
    }
    try {
        $h = Get-NetFirewallRule -Name $hostRuleName -ErrorAction Stop
        $state.host = [string]($h | Get-NetFirewallPortFilter).LocalPort
    } catch { $state.host = $null }
    return $state
}

function Test-Converged($state) {
    if ($declared) {
        $hvOk = (-not $state.hvSupported) -or ($state.hv -eq "$port")
        return ($hvOk -and $state.host -eq "$port")
    }
    return ($null -eq $state.hv -and $null -eq $state.host)
}

# THE DECLARED ADDRESS MUST STILL BE THIS MACHINE'S. A listening office tells the office that dials it
# where to dial (DGO_WG_ENDPOINT), and on a home network that address is a DHCP lease: the day the
# router hands the machine another one, the other office dials an address nobody answers, and nothing
# here says so (hp-laptop was 192.168.16.104 and then .102 within a week, 2026-10). Read-only: this
# only reports, on every run, so the drift is seen the next time anybody runs `bbox run`.
$endpoint = Read-EnvValue "DGO_WG_ENDPOINT"
if ($declared -and $endpoint -match '^\d{1,3}(\.\d{1,3}){3}$') {
    $mine = @()
    try {
        $mine = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
                  Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } |
                  ForEach-Object { $_.IPAddress })
    } catch { $mine = @() }
    if ($mine.Count -gt 0 -and $mine -notcontains $endpoint) {
        Write-Output "[tunnel] WARNING: this office tells other offices to dial $endpoint, and that is not an address of this machine now (it has: $($mine -join ', '))."
        Write-Output "[tunnel]          An office paired with this one cannot reach it until DGO_WG_ENDPOINT in .env is this machine's address again - reserve the address in the router (DHCP reservation), or set the new one and pair again."
    }
}

$state = Get-Current
$want = if ($declared) { "UDP $port inbound allowed (declared in .env)" } else { "no tunnel port declared - no rule" }

if (Test-Converged $state) {
    Write-Output "[firewall] ok: $want"
    exit 0
}

if ($Check) {
    Write-Output "[firewall] DRIFT: wanted: $want; found: hyper-v=$($state.hv) host=$($state.host)"
    exit 1
}

if (-not $Apply) {
    # Not elevated, and something must change: ask once. -Wait so `bbox run` proceeds with the door
    # already open; the elevated child gets the SAME repo root, never a guess.
    Write-Output "[firewall] the declared tunnel port is not allowed by Windows yet - asking for administrator consent (one prompt)..."
    try {
        $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Apply", "-RepoRoot", "`"$RepoRoot`"")
        $p = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Verb RunAs -Wait -PassThru -WindowStyle Hidden
        if ($p.ExitCode -ne 0) { throw "the elevated step exited $($p.ExitCode)" }
    } catch {
        Write-Output "[firewall] NOT applied ($($_.Exception.Message))."
        if ($declared) {
            Write-Output "[firewall] this office declares it listens on UDP $port, and Windows still drops it: an office that dials this one will not connect until the rule exists. Re-run 'bbox run' and accept the prompt."
        }
        exit 2
    }
    if (Test-Converged (Get-Current)) { Write-Output "[firewall] applied: $want"; exit 0 }
    Write-Output "[firewall] the elevated step ran but the rules still do not match - run with -Check to see what is there."
    exit 2
}

# ── elevated from here: replace, never edit in place (a rule on an old port is a door on a guess) ──
if ($state.hvSupported) {
    Get-NetFirewallHyperVRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallHyperVRule -ErrorAction SilentlyContinue
}
Get-NetFirewallRule -Name $hostRuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
if ($declared) {
    if ($state.hvSupported) {
        New-NetFirewallHyperVRule -Name $ruleName -DisplayName $display -Direction Inbound `
            -VMCreatorId $WslCreator -Protocol UDP -LocalPorts $port -Action Allow | Out-Null
    }
    New-NetFirewallRule -Name $hostRuleName -DisplayName $display -Direction Inbound `
        -Protocol UDP -LocalPort $port -Action Allow -Profile Any | Out-Null
}
exit 0
