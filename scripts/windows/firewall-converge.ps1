# firewall-converge.ps1 - make the Windows firewall MATCH what this office's .env declares.
#
# WHY THIS EXISTS
#   TWO doors are declared in .env, and both are Windows' to open:
#
#   1. THE TUNNEL. An office that another office dials (a paired office that LISTENS -
#      apps/dgo-extend/pair_api.py) declares one UDP port:
#
#       DGO_WG_PUBLISH_BIND=0.0.0.0
#       DGO_WG_PUBLISH_PORT=51830
#
#      compose publishes it for `dgo-net`, and under WSL mirrored networking that port is the
#      machine's own. But Windows drops every inbound packet to WSL until a rule says otherwise (the
#      Hyper-V firewall's default inbound action is Block - measured on hp-laptop 2026-10-04: ICMP
#      from the Mac answered, UDP to the published port was silently dropped). A container cannot
#      open that door, and a command pasted by hand into an admin shell is not a declaration. So the
#      declaration is the .env line, and THIS is what applies it - the same shape as everything else
#      here: desired state in a file, converged by `bbox run`.
#
#   2. THE OFFICE'S OWN DOOR ON THE LOCAL NETWORK (DGO-543). The office's routes live in
#      `platform.state.yaml` (`network.routes`), opened from the console by `apps/office-routes`, and the
#      compiler renders what the machine side has to know into `.generated/network.json`. That is
#      the file read here - never `.env`, which carries the TUNNEL's own address, declared by a
#      detector, and that is a different fact. A route opens a TCP door on the edge's `web`
#      entrypoint and needs the same two rules. Scope: the machine's OWN subnets (never `any` - a
#      private address is reachable from its own network and nowhere else), and the gate behind it
#      is the office's sign-in, exactly as on every `*.localhost` host.
#      WHAT IS OPENED: TCP 80 only, and only while a route is open. The door is plain http on
#      purpose (an address has no certificate); its https twin would be a door every browser refuses.
#
# WHAT IT OWNS
#   Four rules, all named after the deployment so two offices on one machine never fight:
#     DigitalOffice-WG-<DEPLOYMENT_NAME>          Hyper-V firewall (the one that guards WSL)
#     DigitalOffice-WG-<DEPLOYMENT_NAME>-Host     Windows Defender firewall (the host's own profiles)
#     DigitalOffice-LAN-<DEPLOYMENT_NAME>         (same pair, for the web door)
#     DigitalOffice-LAN-<DEPLOYMENT_NAME>-Host
#   Declared  -> both exist, on that port/protocol, inbound, allow.
#   Not declared (bind empty/loopback, or no port / no open route in .generated/network.json)
#   -> both are REMOVED.
#   A door nobody declares is closed. It never touches a rule it did not name.
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

# ── the office's own LAN door (platform/manager/reconcile.py:office_lan_host, DGO-542) ───────────
# The address the owner's phone opens the console at. The compiler serves the console, its apps'
# passthroughs and the sign-in there; THIS is the half that lets a packet in. TCP 80, and nothing
# else: the door is plain http on purpose (a local address has no certificate), so there is no 443
# that could carry it.
$lanRuleName = "DigitalOffice-LAN-$deployment"
$lanHostRuleName = "$lanRuleName-Host"
$lanDisplay = "Digital Office LAN door ($deployment)"

# THE DECLARATION IS COMPILED, NOT GUESSED. `.generated/network.json` is rendered by
# platform/manager/reconcile.py from `platform.state.yaml`'s `network.routes` - the block the
# console writes through `apps/office-routes` - so the machine side of a route and the edge side of it are
# one declaration read twice, never two facts that can disagree. A missing file means "this checkout
# has not compiled yet": that is no route, not an error.
function Read-NetworkFacts {
    $file = Join-Path $RepoRoot ".generated\network.json"
    if (-not (Test-Path -LiteralPath $file)) { return $null }
    try { return (Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

$lanFacts = Read-NetworkFacts
$lanAddress = if ($lanFacts -and $lanFacts.lan) { [string]($lanFacts.lan.address) } else { "" }
$lanPort = if ($lanFacts -and $lanFacts.lan -and $lanFacts.lan.port) { [int]$lanFacts.lan.port } else { 80 }
$lanDeclared = [bool]($lanFacts -and $lanFacts.lan -and $lanFacts.lan.enabled -and $lanAddress `
                         -and $lanAddress -notmatch '^(127\.|localhost$|::1$)')

function Get-LocalSubnets {
    # The networks THIS MACHINE is on, as `network/length` — the widest scope this door may have. A
    # private address is reachable from its own network and nowhere else, so "the machine's own
    # networks" is the whole of what the door means; `Any` would open it on whatever network the
    # machine joins next (a cafe, a hotel, a customer's), which is a different decision.
    # Read from the routing table, not computed from an address: the prefix Windows itself installed
    # is what a packet from that network arrives under.
    $subnets = @()
    try {
        $subnets = @(Get-NetRoute -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.DestinationPrefix -match '^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$' } |
            Where-Object { $_.DestinationPrefix -notmatch '^(0\.0\.0\.0|127\.|169\.254\.|22[4-9]\.|2[3-5][0-9]\.)' } |
            ForEach-Object { $_.DestinationPrefix } |
            Sort-Object -Unique)
    } catch { $subnets = @() }
    return $subnets
}

$script:hvSupported = $true

function Get-Door {
    # ONE door, as the two rules that carry it: the port each of them is on, or $null when the rule
    # is not there. Both doors read the same way, and only the rules this script names are read —
    # a rule somebody made by hand must not look like one of ours.
    param([string]$HvRule, [string]$HostRule)
    $door = @{ hv = $null; host = $null }
    try {
        $door.hv = [string](Get-NetFirewallHyperVRule -Name $HvRule -ErrorAction Stop).LocalPorts
    } catch [Microsoft.PowerShell.Cmdletization.Cim.CimJobException] {
        $door.hv = $null
    } catch [System.Management.Automation.CommandNotFoundException] {
        # an older Windows without the Hyper-V firewall cmdlets: WSL there is NAT'd, not mirrored,
        # and the rule has no meaning. Say so instead of failing the run.
        $script:hvSupported = $false
    } catch {
        $door.hv = $null
    }
    try {
        $h = Get-NetFirewallRule -Name $HostRule -ErrorAction Stop
        $door.host = [string]($h | Get-NetFirewallPortFilter).LocalPort
    } catch { $door.host = $null }
    return $door
}

function Test-Door {
    # "Is this door exactly what .env declares": both rules on the wanted port, or both absent when
    # nothing is declared — a door nobody declares is closed.
    param($Door, [bool]$Wanted, [string]$WantPort)
    if ($Wanted) {
        $hvOk = (-not $script:hvSupported) -or ($Door.hv -eq $WantPort)
        return ($hvOk -and ($Door.host -eq $WantPort))
    }
    return ($null -eq $Door.hv -and $null -eq $Door.host)
}

# THE DECLARED ADDRESS MUST STILL BE THIS MACHINE'S. A listening office tells the office that dials it
# where to dial (DGO_WG_ENDPOINT), and on a home network that address is a DHCP lease: the day the
# router hands the machine another one, the other office dials an address nobody answers, and nothing
# here says so (hp-laptop was 192.168.16.104 and then .102 within a week, 2026-10). Read-only: this
# only reports, on every run, so the drift is seen the next time anybody runs `bbox run`.
# The LAN route's own address (network.routes) is the same lease and the same failure, so it is
# checked by the same rule — and there the address is not a hint to another office but the thing the
# owner types on his phone.
$mine = @()
try {
    $mine = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
              Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } |
              ForEach-Object { $_.IPAddress })
} catch { $mine = @() }

function Test-IsMine([string]$address) {
    # True when this machine holds that address — and when it cannot be told at all (not an IPv4
    # literal, or no address answered): a check that fails must not be able to take a door down.
    if ($address -notmatch '^\d{1,3}(\.\d{1,3}){3}$' -or $mine.Count -eq 0) { return $true }
    return ($mine -contains $address)
}

$endpoint = Read-EnvValue "DGO_WG_ENDPOINT"
if ($declared -and -not (Test-IsMine $endpoint)) {
    Write-Output "[tunnel] WARNING: this office tells other offices to dial $endpoint, and that is not an address of this machine now (it has: $($mine -join ', '))."
    Write-Output "[tunnel]          An office paired with this one cannot reach it until DGO_WG_ENDPOINT in .env is this machine's address again - reserve the address in the router (DHCP reservation), or set the new one and pair again."
}
# FAIL CLOSED, not warned-and-opened. The rule this script would create opens THIS machine's port 80
# to its own networks, and a declaration naming an address the machine does not hold is a door that
# dials nobody — a lease that moved, a typo, or a device that is not this one. So it is not opened,
# and the line says why: this is the authoritative check of "is that address mine", because it is the
# only half of the office that can see the machine's interfaces (a container's /proc is its own).
if ($lanDeclared -and -not (Test-IsMine ($lanAddress -replace ':\d+$', ''))) {
    Write-Output "[lan]     WARNING: the open route's address is $lanAddress, and that is not an address of this machine now (it has: $($mine -join ', '))."
    Write-Output "[lan]     NOT opening the rule: a phone opening $lanAddress reaches nobody. Open the route again from «ניהול רשת» with this machine's own address (or reserve the lease in the router)."
    $lanDeclared = $false
}

$tunnel = Get-Door $ruleName $hostRuleName
$lan = Get-Door $lanRuleName $lanHostRuleName
$wantTunnel = if ($declared) { "UDP $port inbound allowed (declared in .env)" } else { "no tunnel port declared - no rule" }
$wantLan = if ($lanDeclared) { "TCP $lanPort inbound from this machine's own networks ($lanAddress)" } else { "no route is open - no rule" }
$tunnelOk = Test-Door $tunnel $declared "$port"
$lanOk = Test-Door $lan $lanDeclared "$lanPort"

if ($tunnelOk -and $lanOk) {
    Write-Output "[firewall] ok: $wantTunnel"
    Write-Output "[lan]      ok: $wantLan"
    exit 0
}

if ($Check) {
    if (-not $tunnelOk) { Write-Output "[firewall] DRIFT: wanted: $wantTunnel; found: hyper-v=$($tunnel.hv) host=$($tunnel.host)" }
    if (-not $lanOk) { Write-Output "[lan] DRIFT: wanted: $wantLan; found: hyper-v=$($lan.hv) host=$($lan.host)" }
    exit 1
}

if (-not $Apply) {
    # Not elevated, and something must change: ask once. -Wait so `bbox run` proceeds with the door
    # already open; the elevated child gets the SAME repo root, never a guess.
    Write-Output "[firewall] a declared door is not allowed by Windows yet - asking for administrator consent (one prompt)..."
    try {
        $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Apply", "-RepoRoot", "`"$RepoRoot`"")
        $p = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Verb RunAs -Wait -PassThru -WindowStyle Hidden
        if ($p.ExitCode -ne 0) { throw "the elevated step exited $($p.ExitCode)" }
    } catch {
        Write-Output "[firewall] NOT applied ($($_.Exception.Message))."
        if ($declared) {
            Write-Output "[firewall] this office declares it listens on UDP $port, and Windows still drops it: an office that dials this one will not connect until the rule exists. Re-run 'bbox run' and accept the prompt."
        }
        if ($lanDeclared) {
            Write-Output "[lan] this office declares a LAN door at $lanAddress, and Windows still drops it: the phone reaches nothing until the rule exists. Re-run 'bbox run' and accept the prompt."
        }
        exit 2
    }
    $tunnel = Get-Door $ruleName $hostRuleName
    $lan = Get-Door $lanRuleName $lanHostRuleName
    if ((Test-Door $tunnel $declared "$port") -and (Test-Door $lan $lanDeclared "$lanPort")) {
        Write-Output "[firewall] applied: $wantTunnel"
        Write-Output "[lan]      applied: $wantLan"
        exit 0
    }
    Write-Output "[firewall] the elevated step ran but the rules still do not match - run with -Check to see what is there."
    exit 2
}

# ── elevated from here: replace, never edit in place (a rule on an old port is a door on a guess) ──
if ($script:hvSupported) {
    foreach ($n in @($ruleName, $lanRuleName)) {
        Get-NetFirewallHyperVRule -Name $n -ErrorAction SilentlyContinue | Remove-NetFirewallHyperVRule -ErrorAction SilentlyContinue
    }
}
foreach ($n in @($hostRuleName, $lanHostRuleName)) {
    Get-NetFirewallRule -Name $n -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
}
if ($declared) {
    if ($script:hvSupported) {
        New-NetFirewallHyperVRule -Name $ruleName -DisplayName $display -Direction Inbound `
            -VMCreatorId $WslCreator -Protocol UDP -LocalPorts $port -Action Allow | Out-Null
    }
    New-NetFirewallRule -Name $hostRuleName -DisplayName $display -Direction Inbound `
        -Protocol UDP -LocalPort $port -Action Allow -Profile Any | Out-Null
}
if ($lanDeclared) {
    # A rule with no scope is a door to anywhere, so an empty answer from the routing table leaves
    # the door CLOSED and says so — never a rule that happens to be wider than the declaration.
    $subnets = Get-LocalSubnets
    if ($subnets.Count -eq 0) {
        Write-Output "[lan] this machine reports no network of its own, so the LAN door is left CLOSED (a rule with no scope would be a door to anywhere)."
    } else {
        if ($script:hvSupported) {
            New-NetFirewallHyperVRule -Name $lanRuleName -DisplayName $lanDisplay -Direction Inbound `
                -VMCreatorId $WslCreator -Protocol TCP -LocalPorts $lanPort `
                -RemoteAddresses $subnets -Action Allow | Out-Null
        }
        New-NetFirewallRule -Name $lanHostRuleName -DisplayName $lanDisplay -Direction Inbound `
            -Protocol TCP -LocalPort $lanPort -RemoteAddress $subnets -Action Allow -Profile Any | Out-Null
        Write-Output "[lan] opened TCP $lanPort from $($subnets -join ', ') — the console, its apps' passthroughs and the sign-in, all behind the office's own sign-in."
    }
}
exit 0
