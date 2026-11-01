# wsl-mirrored.ps1 - make this Windows machine able to RECEIVE a tunnel: WSL in mirrored networking.
#
# WHY THIS EXISTS
#   An office that another office dials must be reachable on one UDP port. Under WSL's default (NAT)
#   networking nothing on the network reaches the distro at all, so a Windows office can only DIAL -
#   and two offices that only dial cannot be paired (apps/dgo-extend/pair_api.py, DIAL_ONLY_HE).
#   WSL's `mirrored` networking mode shares the machine's interfaces and ports with the distro. With
#   it, `bbox run` declares the LAN address by itself (apps/dgo-extend/hooks/prepare) and opens the
#   port (firewall-converge.ps1). Without it the office says, on its own screen, that it only dials.
#
# WHY IT IS A VERB AND NOT PART OF `bbox run`
#   The mode is one line in %UserProfile%\.wslconfig - a file that belongs to the USER, not to this
#   project, and governs EVERY WSL distro on the machine - and it takes effect only when WSL restarts,
#   which stops everything running in WSL: this stack, other distros, Docker Desktop's backend. That
#   is a decision. So it is asked for by name, says exactly what it will do, and does nothing without
#   a typed YES. `bbox run` only reports the state; it never changes it.
#
#       bbox dialable             # say what is and what would change, ask, do it
#       bbox dialable -Check      # report only; exit 1 when this machine cannot be dialed
#       bbox dialable -Yes        # the YES was already given (an installer, a script)
#       bbox dialable -NoRestart  # write the line, leave WSL running: it applies at WSL's next start
#       bbox dialable -Undo       # put .wslconfig back as it was before this script, restart WSL
#       bbox dialable -SelfTest   # the file-editing rules against fixtures; touches nothing
#
# WHAT IT OWNS
#   One key, `networkingMode`, in the `[wsl2]` section. Every other line of the file - the memory cap,
#   the comments above it - is written back byte for byte, in the file's own encoding and line ending.
#   The file as it was before the FIRST change is kept beside it (.wslconfig.bbox-backup) and is what
#   -Undo restores.
#
# WHAT WAS AND WAS NOT MEASURED (2026-10-05)
#   The editing rules run as a self-test; -Check and a full apply/undo against a scratch file ran on a
#   machine that is already mirrored. The restart itself (`wsl --shutdown`) was NOT executed there:
#   that machine hosts other stacks in the same WSL. It is the one line below marked as such.
param(
    [switch]$Check,
    [switch]$Yes,
    [switch]$NoRestart,
    [switch]$Undo,
    [switch]$SelfTest,
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"
$MinBuild = 22621            # Windows 11 22H2 - the first build whose WSL can mirror
$Key = "networkingMode"
$Want = "mirrored"

# -- the file, as lines: read one key, write one key, change nothing else --------------------------
function Get-Section([string]$line) {
    if ($line -match '^\s*\[([^\]]+)\]\s*$') { return $Matches[1].Trim().ToLowerInvariant() }
    return $null
}

function Get-Mode([string[]]$lines) {
    # The LAST uncommented assignment inside [wsl2] wins; "" = not set (WSL's default: NAT).
    $section = ""; $mode = ""
    foreach ($line in $lines) {
        $s = Get-Section $line
        if ($null -ne $s) { $section = $s; continue }
        if ($section -eq "wsl2" -and $line -match "^\s*$Key\s*=\s*(.*?)\s*$") {
            $mode = $Matches[1].Trim().ToLowerInvariant()
        }
    }
    return $mode
}

function Set-Mode([string[]]$lines, [string]$mode) {
    # Every assignment of the key inside [wsl2] is replaced by ONE; none there -> one line right under
    # the section's header; no section -> the section is added at the end. Nothing else moves.
    $out = New-Object System.Collections.Generic.List[string]
    $section = ""; $written = $false; $seen = $false
    foreach ($line in $lines) {
        $s = Get-Section $line
        if ($null -ne $s) {
            $section = $s
            $out.Add($line)
            if ($s -eq "wsl2" -and -not $written) { $out.Add("$Key=$mode"); $written = $true; $seen = $true }
            continue
        }
        if ($section -eq "wsl2" -and $line -match "^\s*$Key\s*=") { continue }   # replaced by the line above
        $out.Add($line)
    }
    if (-not $seen) {
        if ($out.Count -gt 0 -and $out[$out.Count - 1].Trim() -ne "") { $out.Add("") }
        $out.Add("[wsl2]")
        $out.Add("$Key=$mode")
    }
    return ,$out.ToArray()
}

# -- the file, as bytes: its own encoding and its own line ending survive the round trip -----------
function Read-Config([string]$path) {
    $doc = @{ exists = $false; lines = @(); newline = "`r`n"; bom = "none"; final = $true }
    if (-not (Test-Path -LiteralPath $path)) { return $doc }
    $doc.exists = $true
    $bytes = [IO.File]::ReadAllBytes($path)
    $text = ""
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $doc.bom = "utf8"; $text = [Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    } elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        $doc.bom = "utf16"; $text = [Text.Encoding]::Unicode.GetString($bytes, 2, $bytes.Length - 2)
    } else {
        $text = [Text.Encoding]::UTF8.GetString($bytes)
    }
    if ($text -notmatch "`r`n" -and $text -match "`n") { $doc.newline = "`n" }
    $doc.final = ($text.Length -eq 0) -or $text.EndsWith("`n")
    $body = $text -replace "`r`n", "`n"
    if ($body.EndsWith("`n")) { $body = $body.Substring(0, $body.Length - 1) }
    if ($body.Length -gt 0) { $doc.lines = @($body -split "`n") } else { $doc.lines = @() }
    return $doc
}

function Write-Config([string]$path, $doc, [string[]]$lines) {
    $text = ($lines -join $doc.newline)
    if ($doc.final -or -not $doc.exists) { $text += $doc.newline }
    $body = $null
    if ($doc.bom -eq "utf16") {
        $body = [Text.Encoding]::Unicode.GetPreamble() + [Text.Encoding]::Unicode.GetBytes($text)
    } elseif ($doc.bom -eq "utf8") {
        $body = [Text.Encoding]::UTF8.GetPreamble() + [Text.Encoding]::UTF8.GetBytes($text)
    } else {
        $body = (New-Object Text.UTF8Encoding($false)).GetBytes($text)
    }
    [IO.File]::WriteAllBytes($path, [byte[]]$body)
}

# -- -SelfTest: the rules above, against the shapes a real .wslconfig takes ------------------------
if ($SelfTest) {
    $bad = 0
    function Expect([string]$name, [bool]$ok, $detail = "") {
        if ($ok) { Write-Output "  ok    $name" } else { Write-Output "  FAIL  $name $detail"; $script:bad++ }
    }
    Expect "an empty file has no mode" ((Get-Mode @()) -eq "")
    Expect "a file with no [wsl2] has no mode" ((Get-Mode @("[experimental]", "sparseVhd=true")) -eq "")
    Expect "the mode is read from [wsl2]" ((Get-Mode @("[wsl2]", "memory=10GB", "networkingMode=mirrored")) -eq "mirrored")
    Expect "key and section are read whatever their case and spacing" ((Get-Mode @("[WSL2]", "  NetworkingMode = NAT  ")) -eq "nat")
    Expect "a commented line is not a setting" ((Get-Mode @("[wsl2]", "# networkingMode=mirrored", ";networkingMode=mirrored")) -eq "")
    Expect "the same key in another section is not this one" ((Get-Mode @("[experimental]", "networkingMode=mirrored", "[wsl2]", "memory=4GB")) -eq "")
    Expect "the last assignment wins" ((Get-Mode @("[wsl2]", "networkingMode=nat", "networkingMode=mirrored")) -eq "mirrored")

    $r = Set-Mode @() "mirrored"
    Expect "an empty file gets the section and the line" (($r -join "|") -eq "[wsl2]|networkingMode=mirrored") ($r -join "|")
    $r = Set-Mode @("# my notes", "[wsl2]", "memory=10GB", "swap=6GB") "mirrored"
    Expect "the line goes right under the header; every other line stays" (($r -join "|") -eq "# my notes|[wsl2]|networkingMode=mirrored|memory=10GB|swap=6GB") ($r -join "|")
    $r = Set-Mode @("[wsl2]", "memory=10GB", "networkingMode=nat", "swap=6GB") "mirrored"
    Expect "an existing assignment is replaced, not duplicated" (($r -join "|") -eq "[wsl2]|networkingMode=mirrored|memory=10GB|swap=6GB") ($r -join "|")
    $r = Set-Mode @("[experimental]", "sparseVhd=true") "mirrored"
    Expect "a file with other sections gets [wsl2] at the end, after a blank line" (($r -join "|") -eq "[experimental]|sparseVhd=true||[wsl2]|networkingMode=mirrored") ($r -join "|")
    $r = Set-Mode @("[experimental]", "networkingMode=mirrored", "[wsl2]", "memory=4GB") "mirrored"
    Expect "the same key in another section is left alone" (($r -join "|") -eq "[experimental]|networkingMode=mirrored|[wsl2]|networkingMode=mirrored|memory=4GB") ($r -join "|")
    $r = Set-Mode @("[wsl2]", "# networkingMode=nat (the default)", "memory=4GB") "mirrored"
    Expect "a comment that mentions the key survives" (($r -join "|") -eq "[wsl2]|networkingMode=mirrored|# networkingMode=nat (the default)|memory=4GB") ($r -join "|")
    $once = Set-Mode @("[wsl2]", "memory=10GB") "mirrored"
    Expect "setting it twice changes nothing the second time" (((Set-Mode $once "mirrored") -join "|") -eq ($once -join "|"))
    Expect "what was set is what is read back" ((Get-Mode $once) -eq "mirrored")

    # the bytes: encoding, line ending and the final newline survive a write
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("wslcfg-selftest-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        # a Hebrew word, from code points: Windows PowerShell reads a script without a BOM in the
        # machine's ANSI codepage, so a non-ASCII character typed into a string here would not be
        # the character the test means
        $hebrew = -join ([char[]](0x05D6, 0x05D9, 0x05DB, 0x05E8, 0x05D5, 0x05DF))
        $cases = @(
            @{ name = "CRLF, no BOM"; bytes = (New-Object Text.UTF8Encoding($false)).GetBytes("[wsl2]`r`nmemory=10GB`r`n") },
            @{ name = "LF, no BOM, a Hebrew comment"; bytes = (New-Object Text.UTF8Encoding($false)).GetBytes("# $hebrew`n[wsl2]`nmemory=10GB`n") },
            @{ name = "UTF-8 with BOM"; bytes = [Text.Encoding]::UTF8.GetPreamble() + [Text.Encoding]::UTF8.GetBytes("[wsl2]`r`nmemory=10GB`r`n") },
            @{ name = "UTF-16 with BOM"; bytes = [Text.Encoding]::Unicode.GetPreamble() + [Text.Encoding]::Unicode.GetBytes("[wsl2]`r`nmemory=10GB`r`n") },
            @{ name = "no final newline"; bytes = (New-Object Text.UTF8Encoding($false)).GetBytes("[wsl2]`r`nmemory=10GB") }
        )
        foreach ($c in $cases) {
            $f = Join-Path $tmp "cfg"
            [IO.File]::WriteAllBytes($f, [byte[]]$c.bytes)
            $d = Read-Config $f
            Write-Config $f $d $d.lines
            $same = [Convert]::ToBase64String([IO.File]::ReadAllBytes($f)) -eq [Convert]::ToBase64String([byte[]]$c.bytes)
            Expect "an unchanged file is written back byte for byte ($($c.name))" $same
            Write-Config $f $d (Set-Mode $d.lines "mirrored")
            $d2 = Read-Config $f
            Expect "...and after the change it reads mirrored, in the same encoding and line ending ($($c.name))" `
                ((Get-Mode $d2.lines) -eq "mirrored" -and $d2.bom -eq $d.bom -and $d2.newline -eq $d.newline -and $d2.final -eq $d.final)
        }
    } finally { Remove-Item -Recurse -Force -LiteralPath $tmp -ErrorAction SilentlyContinue }
    if ($bad) { Write-Output "wsl-mirrored selftest: $bad FAILED"; exit 1 }
    Write-Output "wsl-mirrored selftest: PASS"
    exit 0
}

# -- what is true on this machine ------------------------------------------------------------------
# A scratch -ConfigPath is for measuring this script: WSL is then never asked and never restarted.
$scratch = [bool]$ConfigPath
if (-not $ConfigPath) { $ConfigPath = Join-Path $env:USERPROFILE ".wslconfig" }
$backup = "$ConfigPath.bbox-backup"
$backupNone = "$ConfigPath.bbox-backup.none"      # "there was no file before": -Undo removes ours

function Invoke-Wsl([string[]]$arguments) {
    # wsl.exe answers its own questions in UTF-16, which arrives here as text laced with NULs. The
    # NULs are dropped rather than the console's encoding changed: what is read is digits and ASCII
    # words, and a host with no console attached must not make this report "no WSL".
    try {
        $out = & wsl.exe @arguments 2>$null
        return @{ code = $LASTEXITCODE; text = (($out | Out-String) -replace "`0", "").Trim() }
    } catch {
        return @{ code = 1; text = "" }
    }
}

function Get-LiveMode {
    # what the RUNNING distro says (this starts it if it is stopped); "" when it cannot be asked
    if ($scratch) { return "" }
    $r = Invoke-Wsl @("-d", "Ubuntu", "-e", "wslinfo", "--networking-mode")
    if ($r.code -ne 0) { return "" }
    return $r.text.ToLowerInvariant()
}

function Restart-Wsl {
    if ($scratch -or $NoRestart) { return $false }
    # THE ONE LINE THAT WAS NOT EXECUTED WHERE THIS WAS WRITTEN (see the header).
    & wsl.exe --shutdown
    return $true
}

$doc = Read-Config $ConfigPath
$configured = Get-Mode $doc.lines
$build = [Environment]::OSVersion.Version.Build
$wslVersion = $null
if (-not $scratch) {
    $v = Invoke-Wsl @("--version")
    if ($v.code -eq 0 -and $v.text -match '(\d+)\.(\d+)\.(\d+)') { $wslVersion = [Version]"$($Matches[1]).$($Matches[2]).$($Matches[3])" }
}

# -- -Undo -----------------------------------------------------------------------------------------
if ($Undo) {
    if (Test-Path -LiteralPath $backup) {
        Copy-Item -LiteralPath $backup -Destination $ConfigPath -Force
        Remove-Item -LiteralPath $backup -Force
        Write-Output "[wsl] $ConfigPath is back as it was before 'bbox dialable'."
    } elseif (Test-Path -LiteralPath $backupNone) {
        Remove-Item -LiteralPath $ConfigPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $backupNone -Force
        Write-Output "[wsl] $ConfigPath did not exist before 'bbox dialable' - removed."
    } else {
        Write-Output "[wsl] nothing to undo: this script made no change it remembers ($backup is not there)."
        exit 0
    }
    if (Restart-Wsl) { Write-Output "[wsl] WSL was restarted. Run 'bbox run' to start the stack again." }
    else { Write-Output "[wsl] the change applies when WSL next starts (wsl --shutdown)." }
    exit 0
}

# -- the state, in one line ------------------------------------------------------------------------
$live = ""
if ($configured -eq $Want) { $live = Get-LiveMode }
if ($configured -eq $Want -and ($live -eq $Want -or $live -eq "")) {
    if ($live -eq $Want) {
        Write-Output "[wsl] ok: WSL runs in mirrored networking - this office can be dialed ('bbox run' declares the address and opens the port)."
    } else {
        Write-Output "[wsl] ok: $ConfigPath sets mirrored networking$(if ($scratch) { '' } else { ' (the running distro could not be asked)' })."
    }
    exit 0
}
if ($configured -eq $Want) {
    Write-Output "[wsl] $ConfigPath sets mirrored networking, but the running WSL is still in '$live': the line applies when WSL restarts."
    if ($Check) { exit 1 }
} else {
    $now = "NAT (WSL's default; nothing is set)"
    if ($configured) { $now = "'$configured'" }
    Write-Output "[wsl] other offices on your network cannot dial this one: WSL networking is $now."
}

# -- can this Windows mirror at all? ---------------------------------------------------------------
$blocked = @()
if ($build -lt $MinBuild) { $blocked += "this Windows is build $build; mirrored networking needs Windows 11 22H2 (build $MinBuild) or later" }
if (-not $scratch) {
    if ($null -eq $wslVersion) { $blocked += "this WSL does not report a version (the in-box WSL); run 'wsl --update' first" }
    elseif ($wslVersion -lt [Version]"2.0.0") { $blocked += "this WSL is $wslVersion; mirrored networking needs 2.0.0 or later - run 'wsl --update'" }
}
if ($blocked.Count -gt 0) {
    foreach ($b in $blocked) { Write-Output "[wsl] cannot change that here: $b." }
    Write-Output "[wsl] the office still works and still pairs with any office that CAN be dialed (it dials them)."
    exit 1
}
if ($Check) {
    Write-Output "[wsl] 'bbox dialable' would set $Key=$Want under [wsl2] in $ConfigPath and restart WSL."
    exit 1
}

# -- say exactly what will happen ------------------------------------------------------------------
$needsWrite = ($configured -ne $Want)
Write-Output "[wsl] to make this office dialable, WSL has to run in 'mirrored' networking:"
if ($needsWrite) {
    Write-Output "[wsl]   1. $ConfigPath gets one line, $Key=$Want, under [wsl2]. Nothing else in the file changes;"
    Write-Output "[wsl]      the file as it is now is kept as $backup ('bbox dialable -Undo' restores it)."
} else {
    Write-Output "[wsl]   1. (the line is already in $ConfigPath)"
}
if ($scratch -or $NoRestart) {
    Write-Output "[wsl]   2. WSL is NOT restarted now: the line applies the next time WSL starts ('wsl --shutdown')."
} else {
    Write-Output "[wsl]   2. WSL restarts. EVERYTHING running in WSL stops now: this stack, any other distro, and"
    Write-Output "[wsl]      Docker Desktop if it runs on WSL. Nothing is deleted; 'bbox run' starts the stack again."
}
Write-Output "[wsl]   3. you run 'bbox run': it declares this machine's address and opens the tunnel's UDP port in the"
Write-Output "[wsl]      Windows firewall (one consent prompt)."
# In mirrored mode the distro's ports ARE the machine's: a Windows program already listening on a port
# the stack publishes keeps that service from starting. Said before, not discovered after.
if (-not $scratch) {
    try {
        $taken = @(Get-NetTCPConnection -State Listen -LocalPort 80, 443 -ErrorAction SilentlyContinue |
            ForEach-Object {
                $name = ""
                try { $name = (Get-Process -Id $_.OwningProcess -ErrorAction Stop).ProcessName } catch { $name = "pid $($_.OwningProcess)" }
                if ($name -notmatch '^(wslrelay|wslhost)$') { "$($_.LocalPort) ($name)" }
            } | Sort-Object -Unique)
        if ($taken.Count -gt 0) {
            Write-Output "[wsl]   NOTE: in mirrored networking WSL shares this machine's ports, and a Windows program is listening on"
            Write-Output "[wsl]         $($taken -join ', '). The stack's web edge uses 80 and 443: stop that program, or the edge will not start."
        }
    } catch { }
}

if (-not $Yes) {
    $interactive = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected
    if (-not $interactive) {
        Write-Output "[wsl] nothing was changed: this needs a YES, and nobody is at the keyboard. Run it yourself, or pass -Yes."
        exit 2
    }
    $answer = Read-Host "[wsl] type YES to do it now (anything else changes nothing)"
    if ($answer -cne "YES") {
        Write-Output "[wsl] nothing was changed."
        exit 2
    }
}

# -- do it -----------------------------------------------------------------------------------------
if ($needsWrite) {
    if (-not (Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $backupNone)) {
        if ($doc.exists) { Copy-Item -LiteralPath $ConfigPath -Destination $backup }
        else { [IO.File]::WriteAllText($backupNone, "there was no .wslconfig before 'bbox dialable'`r`n") }
    }
    Write-Config $ConfigPath $doc (Set-Mode $doc.lines $Want)
    # (not `$check`: PowerShell names are case-blind, and that IS the -Check switch - the first run of
    # this script against a scratch file wrote the line and then died here, assigning a string to it)
    $readBack = Get-Mode (Read-Config $ConfigPath).lines
    if ($readBack -ne $Want) {
        Write-Output "[wsl] the file was written but does not read back as mirrored ('$readBack') - nothing was restarted."
        exit 1
    }
    Write-Output "[wsl] written: $Key=$Want under [wsl2] in $ConfigPath."
}
if (Restart-Wsl) {
    Write-Output "[wsl] WSL was restarted. Now run 'bbox run' - it brings the stack up in mirrored networking, and the"
    Write-Output "[wsl] office's screen (linked offices) will show the address other offices dial."
} else {
    Write-Output "[wsl] WSL was not restarted: the line applies the next time WSL starts ('wsl --shutdown'), then 'bbox run'."
}
exit 0
