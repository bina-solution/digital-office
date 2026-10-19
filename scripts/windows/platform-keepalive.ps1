<#
    platform-keepalive.ps1 - keep the WSL-hosted stack running across reboots, sleep and logoff.

    ASCII ONLY, DELIBERATELY. An earlier version of this file used em-dashes in its comments and
    PowerShell parsed it as ANSI, which shifted bytes and broke quote pairing across the whole
    script. Do not reintroduce non-ASCII characters here.

    WHY THIS EXISTS
    ---------------
    On 2026-08-12 Windows Update rebooted this laptop twice (06:35 MoUsoCoreWorker, 06:38
    TrustedInstaller). Windows came back at 06:39. The stack did not - it stayed down for
    4 hours 25 minutes, until an agent happened to run a `wsl` command at 11:03.

    Every link in the chain was already correct EXCEPT the first one:

        Windows boots            OK
        WSL distro starts        <-- MISSING. Nothing invokes it. WSL is on-demand.
        systemd (PID 1)          OK   (systemd enabled in /etc/wsl.conf)
        docker.service           OK   (systemctl is-enabled docker -> enabled)
        containers               OK   (RestartPolicy = unless-stopped on all 47)

    WSL2 only starts a distro when something asks for it. No login, no `wsl` command, no stack.
    .wslconfig already sets vmIdleTimeout=86400000, so this is NOT idle-shutdown - the distro
    simply never started.

    WHAT THIS DOES
    --------------
    Idempotent. Safe to run every few minutes. `wsl -d <distro> -e true` starts a stopped distro
    and is a no-op on a running one, so there is no "is it running" parse to get wrong (the
    `wsl -l -v` output is UTF-16 and painful to parse reliably).

    Then it verifies the two things that can still be wrong once the distro is up:
      - docker.service actually active (not merely enabled)
      - a plausible number of containers running

    INSTALL
    -------
        powershell -ExecutionPolicy Bypass -File platform-keepalive.ps1 -Install

    Registers a scheduled task with three triggers: at startup, at logon, and every 5 minutes.
    The recurring trigger is the workhorse - it self-heals regardless of whether any single
    trigger fires, and covers resume-from-sleep, which has no reliable trigger of its own on
    all Windows builds.

    LIMITATION worth knowing: a task that must run with NOBODY LOGGED IN needs stored
    credentials. -Install registers it to run as the current user, which needs no password but
    means an unattended overnight reboot leaves the stack down until someone logs in.
#>

[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Status,
    [switch]$Elevated,
    [switch]$Shutdown,
    [switch]$HealthCheck,
    [switch]$HostFacts,
    [string]$Distro   = 'Ubuntu',
    [string]$TaskName = 'Platform-OS-Keepalive',
    [int]$MinContainers = 20
)

$ErrorActionPreference = 'Stop'
$LogDir  = Join-Path $env:LOCALAPPDATA 'platform-os'
$LogFile = Join-Path $LogDir 'keepalive.log'

function Write-Log {
    param([string]$Message)
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -Path $LogFile -Value $line -Encoding utf8
    Write-Output $line
}

function Get-ContainerCount {
    $out = & wsl.exe -d $Distro -u root -e docker -H unix:///run/bbox-docker.sock ps -q 2>&1
    return (@($out | Where-Object { $_ -match '^[0-9a-f]{6,}$' })).Count
}

function Invoke-Keepalive {
    # 1. Start the distro. Idempotent: no-op if running, boots it if stopped.
    #    -u root so it does not depend on the login user's shell profile succeeding.
    $recovered = $false
    try {
        & wsl.exe -d $Distro -u root -e /bin/true 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "wsl exited $LASTEXITCODE" }
    } catch {
        Write-Log "FAIL  could not start distro '$Distro': $_"
        return
    }

    # 2. docker enabled is not the same as docker active. A freshly booted distro may still
    #    be activating.
    $state = (& wsl.exe -d $Distro -u root -e systemctl is-active docker 2>&1 | Out-String).Trim()
    if ($state -ne 'active') {
        Write-Log "docker is '$state' - starting it"
        & wsl.exe -d $Distro -u root -e systemctl start docker 2>&1 | Out-Null
        Start-Sleep -Seconds 5
        $state = (& wsl.exe -d $Distro -u root -e systemctl is-active docker 2>&1 | Out-String).Trim()
        $recovered = $true
    }

    # 3. Container census. NOTE the socket is not the default one on this host.
    $count = Get-ContainerCount

    if ($count -lt $MinContainers) {
        Write-Log "WARN  docker=$state but only $count containers running (expected at least $MinContainers)"
        Write-Log "      restart policies are unless-stopped so they should come up on their own."
        Write-Log "      If this persists the stack needs a real bring-up, not a keepalive."
    }
    elseif ($recovered) {
        Write-Log "RECOVERED  distro and docker started, $count containers running"
    }
    # Steady state logs nothing. This runs every 5 minutes and must not fill the disk.
}

function Install-Task {
    # THE ANCHOR. Measured 2026-08-12: WSL tears the distro down as soon as the last client
    # detaches, even with systemd as PID 1 and vmIdleTimeout=86400000 in .wslconfig.
    #   11:16:04  Ubuntu = Stopped   (seconds after commands finished)
    #   11:17:44  Ubuntu = Running   (only because the keepalive poked it)
    # The stack was therefore not running at all - it was being cold-started every few minutes,
    # living for seconds, then dying. Symptoms: dockerd uptime 9s, containers perpetually
    # "Up 14 seconds", n8n logging "Last session crashed" repeatedly, 105 orphaned executions.
    #
    # Poking WSL on a timer does NOT fix this - it just restarts it after each death. The fix is
    # to hold ONE long-lived process inside the distro so the client count never reaches zero.
    # Task Scheduler owns that process; if it ever dies the 5-minute trigger starts a new one,
    # and MultipleInstances=IgnoreNew stops duplicates piling up.
    # WINDOW VISIBILITY: wsl.exe is a CONSOLE application. A scheduled task with an Interactive
    # principal that executes it directly pops a visible terminal window every time it fires -
    # every 2 minutes, forever. Reported by the owner 2026-08-12 ("terminal windows opening by
    # themselves, 3 in the past minutes") and it was entirely self-inflicted.
    #
    # Launching through powershell.exe -WindowStyle Hidden gives the child an already-hidden
    # console to inherit, so nothing appears on screen. PowerShell also stays alive for the
    # lifetime of the child, which keeps the task in the Running state - that is what makes
    # MultipleInstances=IgnoreNew work as the duplicate guard.
    # Launch through hidden-run.vbs. powershell -WindowStyle Hidden was NOT enough - the process
    # still creates its console before hiding it, which is a visible flash every 2 minutes. wscript
    # is a GUI-subsystem binary and WScript.Shell.Run(cmd, 0, True) never creates a window at all.
    # The True makes it block for the child's lifetime, so the task stays Running and
    # MultipleInstances=IgnoreNew still guards against duplicate anchors.
    $vbs = Join-Path (Split-Path $PSCommandPath -Parent) 'hidden-run.vbs'
    $action = New-ScheduledTaskAction -Execute 'wscript.exe' `
        -Argument ('//B //Nologo "' + $vbs + '" wsl.exe -d ' + $Distro + ' -u root -e /bin/sleep infinity')

    # Delays are load-bearing, measured 2026-08-12 on a real reboot:
    #   11:40:27 Windows booted
    #   11:40:38 ARSO signed the user in (11s)
    #   11:40:41 logon trigger fired 3s later -> anchor died 0xC000013A immediately, because
    #            LxssManager/vmcompute were not ready yet. Stack stayed down.
    #   11:45:41 the 5-minute backstop fired -> anchor held, distro up, 47 containers.
    # So it DID self-heal, but cost 5 minutes it did not need to. A 60s logon delay lets WSL's
    # subsystem finish starting, and the 2-minute repeat (was 5) halves the worst case if it
    # still loses the race.
    $tStart = New-ScheduledTaskTrigger -AtStartup
    $tStart.Delay = 'PT90S'
    $tLogon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $tLogon.Delay = 'PT60S'
    $tEvery = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
                -RepetitionInterval (New-TimeSpan -Minutes 2)

    # ExecutionTimeLimit ZERO is load-bearing: the action is a process that never exits by design.
    # Any non-zero limit would have Task Scheduler kill the anchor and drop the stack.
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

    # RunLevel Highest requires an ELEVATED shell to register. The keepalive does not need
    # elevation to do its job - wsl.exe runs fine as the ordinary user - so default to Limited
    # and let the caller opt into Highest with -Elevated when running as admin.
    $level = if ($Elevated) { 'Highest' } else { 'Limited' }
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel $level

    # An AtStartup trigger requires an ELEVATED shell to register - it is a machine-scope trigger,
    # independent of any user session. RunLevel is not what blocks it; the trigger itself is.
    # So: try the full set, and if that is refused, fall back to logon+recurring, which registers
    # fine unelevated. Degrading is better than failing, but SAY which one landed.
    $withBoot = $true
    try {
        Register-ScheduledTask -TaskName $TaskName -Action $action `
            -Trigger @($tStart, $tLogon, $tEvery) -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
    } catch {
        $withBoot = $false
        try {
            Register-ScheduledTask -TaskName $TaskName -Action $action `
                -Trigger @($tLogon, $tEvery) -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
        } catch {
            Write-Output "REGISTRATION FAILED even without the startup trigger: $_"
            return
        }
    }

    # VERIFY rather than assume. The previous version printed INSTALLED after a failed
    # registration, which is exactly the kind of false success this project keeps getting bitten by.
    $check = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $check) {
        Write-Output "REGISTRATION REPORTED OK BUT TASK IS NOT PRESENT - treat as failed."
        return
    }

    Install-CompanionTasks

    $trig = if ($withBoot) { 'startup(+90s) + logon(+60s) + every 2 min' } else { 'logon(+60s) + every 2 min (NO startup trigger)' }
    Write-Log "INSTALLED task '$TaskName' runlevel=$level triggers=$trig distro='$Distro'"
    Write-Output ""
    Write-Output "Verify:  Get-ScheduledTask -TaskName '$TaskName'"
    Write-Output "Run now: Start-ScheduledTask -TaskName '$TaskName'"
    Write-Output "Log:     $LogFile"
    if (-not $withBoot) {
        Write-Output ""
        Write-Output "WITHOUT the startup trigger this recovers the stack when you LOG IN, and"
        Write-Output "self-heals every 5 minutes thereafter - but a reboot with nobody logging in"
        Write-Output "leaves the stack down until someone does. To add the boot trigger, run this"
        Write-Output "once from an Administrator PowerShell:"
        Write-Output ""
        Write-Output "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Install -Elevated"
    }
}

function Install-CompanionTasks {
    $ps = (Get-Command powershell.exe).Source
    $vbs = Join-Path (Split-Path $PSCommandPath -Parent) 'hidden-run.vbs'
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel Limited

    # --- graceful shutdown, triggered by System event 1074 (shutdown/restart initiated) ---
    # There is no -AtShutdown trigger in New-ScheduledTaskTrigger, and Task Scheduler's own
    # shutdown handling does not run actions. An event trigger on 1074 fires the moment something
    # initiates the restart, which is the earliest hook available without Group Policy.
    try {
        $xpath = "<QueryList><Query Id='0' Path='System'><Select Path='System'>*[System[(EventID=1074)]]</Select></Query></QueryList>"
        $cls = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
        $evt = New-CimInstance -CimClass $cls -ClientOnly
        $evt.Subscription = $xpath
        $evt.Enabled = $true

        $act = New-ScheduledTaskAction -Execute 'wscript.exe' `
            -Argument ('//B //Nologo "' + $vbs + '" "' + $ps + '" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Shutdown -Distro ' + $Distro)
        # Short limit: if we have not finished in 60s the machine is going down anyway.
        $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 60)

        Register-ScheduledTask -TaskName 'Platform-OS-Shutdown' -Action $act -Trigger $evt `
            -Settings $set -Principal $principal -Force -ErrorAction Stop | Out-Null
        Write-Output "  registered Platform-OS-Shutdown (event 1074, best effort)"
    } catch {
        Write-Output "  Platform-OS-Shutdown NOT registered: $_"
    }

    # --- health check every 5 minutes, alerts on TRANSITION only ---
    try {
        $act2 = New-ScheduledTaskAction -Execute 'wscript.exe' `
            -Argument ('//B //Nologo "' + $vbs + '" "' + $ps + '" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -HealthCheck -Distro ' + $Distro)
        $t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
                -RepetitionInterval (New-TimeSpan -Minutes 5)
        $set2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)

        Register-ScheduledTask -TaskName 'Platform-OS-Health' -Action $act2 -Trigger $t2 `
            -Settings $set2 -Principal $principal -Force -ErrorAction Stop | Out-Null
        Write-Output "  registered Platform-OS-Health (every 5 min, alerts on transition)"
    } catch {
        Write-Output "  Platform-OS-Health NOT registered: $_"
    }
}

function Uninstall-Task {
    foreach ($n in @($TaskName, 'Platform-OS-Shutdown', 'Platform-OS-Health')) {
        Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue
    }
    Write-Log "REMOVED tasks: $TaskName, Platform-OS-Shutdown, Platform-OS-Health"
}

function Show-Status {
    Write-Output "=== scheduled task ==="
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $t) { Write-Output "  NOT INSTALLED" }
    else {
        Write-Output ("  state: " + $t.State)
        $i = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($i) {
            Write-Output ("  last run:    " + $i.LastRunTime)
            Write-Output ("  last result: " + $i.LastTaskResult)
            Write-Output ("  next run:    " + $i.NextRunTime)
        }
    }

    Write-Output "=== windows uptime ==="
    $b = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
    $up = New-TimeSpan -Start $b -End (Get-Date)
    Write-Output ("  booted " + $b + "   uptime " + $up.ToString('dd\.hh\:mm\:ss'))

    Write-Output "=== stack ==="
    Write-Output ("  containers running: " + (Get-ContainerCount))

    if (Test-Path $LogFile) {
        Write-Output "=== last 10 log lines ==="
        Get-Content $LogFile -Tail 10 | ForEach-Object { Write-Output ("  " + $_) }
    }
}

function Invoke-GracefulShutdown {
    # WHY: Windows kills the WSL VM outright on restart, so Postgres never checkpoints and does
    # CRASH RECOVERY on the way back up. That is not cosmetic - the 2026-08-12 restart left 105
    # orphaned n8n executions, which errorHandler01 then swept into NEEDS_REVIEW, falsely flagging
    # ~3,250 client documents for human attention. A clean stop removes that whole class of damage.
    #
    # HONEST LIMITATION: this is BEST EFFORT. Windows does not wait for Task Scheduler tasks during
    # shutdown the way it waits for Group Policy shutdown scripts. Triggering on System event 1074
    # (shutdown initiated) buys a head start, usually a few seconds, before the axe falls. So the
    # order below matters more than completeness: stop the WRITERS first so the databases stop
    # receiving work, then checkpoint the databases. If we only get through step 1 we have still
    # reduced the damage; if we get through step 2 we have eliminated it.
    Write-Log "SHUTDOWN signal - stopping stack gracefully (best effort)"
    $sw = [Diagnostics.Stopwatch]::StartNew()

    # 1. writers first - n8n main and workers stop enqueueing and executing
    & wsl.exe -d $Distro -u root -e docker -H unix:///run/bbox-docker.sock stop -t 8 `
        n8n-shlomo-laptop n8n-worker-1-shlomo-laptop n8n-worker-2-shlomo-laptop 2>&1 | Out-Null
    Write-Log "  writers stopped at $($sw.Elapsed.TotalSeconds.ToString('0.0'))s"

    # 2. databases - SIGTERM makes postgres do a fast shutdown WITH a checkpoint, which is exactly
    #    what avoids crash recovery. This is the step that actually matters.
    & wsl.exe -d $Distro -u root -e docker -H unix:///run/bbox-docker.sock stop -t 15 `
        n8n-postgres-shlomo-laptop supabase-db-shlomo-laptop 2>&1 | Out-Null
    Write-Log "  databases checkpointed at $($sw.Elapsed.TotalSeconds.ToString('0.0'))s"

    $sw.Stop()
    Write-Log "SHUTDOWN complete in $($sw.Elapsed.TotalSeconds.ToString('0.0'))s"
}

function Write-HostFacts {
    # WHAT THE VM CANNOT SEE: the memory of the machine it runs on. On 2026-10-06 Windows was down
    # to 275 MB free of 16 GB - the WSL VM holding 6.5 GB of it - and WSL stopped answering for two
    # minutes, while the office's own machine screen read "memory 64%": the VM's figure, which is
    # the only one it can measure. This is the one part of the office that runs ON the host, so it
    # writes the host's figure where the office reads it: <checkout>\data\power\host.json, the
    # directory the machine service already shares with a host-side agent.
    #
    # A fact, never a failure: whatever goes wrong here is swallowed, and a file that stops being
    # written simply goes stale - the reader shows nothing rather than an old number.
    try {
        $repo = Split-Path (Split-Path (Split-Path $PSCommandPath -Parent) -Parent) -Parent
        $dir  = Join-Path $repo 'data\power'
        if (-not (Test-Path $dir)) { return }
        $os  = Get-CimInstance Win32_OperatingSystem
        $doc = '{"updated_at":' + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() +
               ',"os":"windows","mem_total":' + ([int64]$os.TotalVisibleMemorySize * 1024) +
               ',"mem_free":' + ([int64]$os.FreePhysicalMemory * 1024) + '}'
        [System.IO.File]::WriteAllText((Join-Path $dir 'host.json'), $doc, (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
}

function Invoke-PowerHold {
    # THE POWER HALF OF THE SAME TICK. The office declares what the host must do when it locks or
    # closes its lid (machine /api/power; defaults: keep running) and on macOS an agent enforces it.
    # On Windows nothing did - /api/power read "agent": "absent" on 2026-10-09, with the owner about
    # to leave the office working unattended over Shabbat. The work lives in its own file so that a
    # fault in it can never break this one; every failure is swallowed here on purpose.
    try {
        $hold = Join-Path $PSScriptRoot 'platform-power-hold.ps1'
        if (Test-Path $hold) {
            $repo = Split-Path (Split-Path (Split-Path $PSCommandPath -Parent) -Parent) -Parent
            & $hold -Repo $repo | Out-Null
        }
    } catch { }
}

function Invoke-HealthCheck {
    Write-HostFacts     # first, and on every tick: it must not depend on anything below succeeding
    Invoke-PowerHold    # second, for the same reason - a host that sleeps takes the office with it
    # WHY: nothing told anyone the platform was down. The 2026-08-12 outage ran 4h37m and was found
    # by chance. This writes to the Windows EVENT LOG (durable, survives the session, greppable)
    # rather than only to a file nobody opens, and raises a desktop notification on transition.
    #
    # Reports on TRANSITION, not on every tick - an alert that fires every 5 minutes is an alert
    # nobody reads.
    $stateFile = Join-Path $LogDir 'health.state'
    $prev = if (Test-Path $stateFile) { (Get-Content $stateFile -Raw).Trim() } else { 'unknown' }

    $count = 0; $execs = 0; $why = ''
    try {
        $count = Get-ContainerCount
        if ($count -lt $MinContainers) { $why = "only $count containers running (expected >= $MinContainers)" }
        else {
            # The column is camelCase, so Postgres REQUIRES double quotes around it - unquoted it
            # folds to "startedat" and errors. Those quotes have to survive PowerShell AND wsl.exe,
            # so they are backslash-escaped here. Measured failure without this:
            #   ERROR: column "startedat" does not exist
            # which the health check then correctly reported as unhealthy - a false alarm caused by
            # the checker, not the stack. Worth keeping the fail-loud behaviour, but not the bug.
            $q = 'select count(*) from execution_entity where \"startedAt\" > now() - interval ''15 minutes'';'
            $r = & wsl.exe -d $Distro -u root -e docker -H unix:///run/bbox-docker.sock `
                    exec -i n8n-postgres-shlomo-laptop psql -U hacohen -d n8n -t -A -c $q 2>&1
            $execs = [int](($r | Where-Object { $_ -match '^\s*\d+\s*$' } | Select-Object -First 1))
            # Zero executions in 15 minutes with a healthy container count means the stack is UP but
            # the pipeline is DEAD - the failure mode that looks fine to every container-level check.
            if ($execs -eq 0) { $why = "stack is up ($count containers) but ZERO executions in 15 min - pipeline stalled" }
        }
    } catch {
        $why = "health check itself failed: $_"
    }

    $now = if ($why) { 'unhealthy' } else { 'healthy' }
    Set-Content -Path $stateFile -Value $now -Encoding utf8

    if ($now -ne $prev) {
        if ($now -eq 'unhealthy') {
            Write-Log "ALERT  $why"
            Write-EventLogEntry -Level Warning -Message "INDOX platform UNHEALTHY: $why"
            Show-Toast -Title 'INDOX platform is DOWN' -Body $why
        } else {
            Write-Log "RECOVERED  $count containers, $execs executions in 15 min"
            Write-EventLogEntry -Level Information -Message "INDOX platform recovered: $count containers, $execs executions/15min"
            Show-Toast -Title 'INDOX platform recovered' -Body "$count containers, $execs executions in 15 min"
        }
    }
}

function Write-EventLogEntry {
    param([string]$Level, [string]$Message)
    try {
        if (-not [Diagnostics.EventLog]::SourceExists('PlatformOS')) {
            New-EventLog -LogName Application -Source 'PlatformOS' -ErrorAction Stop
        }
        Write-EventLog -LogName Application -Source 'PlatformOS' -EntryType $Level -EventId 9001 -Message $Message
    } catch {
        # Creating an event source needs elevation the first time. Non-fatal - the log file and the
        # toast still fire, so a failure here must not swallow the alert.
        Write-Log "  (event log unavailable: $_)"
    }
}

function Show-Toast {
    param([string]$Title, [string]$Body)
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        $n = New-Object System.Windows.Forms.NotifyIcon
        $n.Icon = [System.Drawing.SystemIcons]::Warning
        $n.Visible = $true
        $n.ShowBalloonTip(20000, $Title, $Body, [System.Windows.Forms.ToolTipIcon]::Warning)
        Start-Sleep -Seconds 12
        $n.Dispose()
    } catch {
        Write-Log "  (toast unavailable: $_)"
    }
}

if     ($Install)     { Install-Task }
elseif ($Uninstall)   { Uninstall-Task }
elseif ($Status)      { Show-Status }
elseif ($Shutdown)    { Invoke-GracefulShutdown }
elseif ($HealthCheck) { Invoke-HealthCheck }
elseif ($HostFacts)   { Write-HostFacts }
else                  { Invoke-Keepalive }
