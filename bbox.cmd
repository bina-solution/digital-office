@echo off
REM bbox.cmd - the Windows entry point. Clone anywhere on C:, open CMD, cd here, run: bbox run
REM
REM bbox itself is a bash script and the stack's engine is Docker CE inside the WSL distro
REM `Ubuntu`, so this hands the command to that distro against THIS directory. There is no second
REM checkout and no second engine: the repo you cloned is the repo that runs.
REM
REM Docker Desktop is never used. bbox pins itself to the project engine's own socket
REM (/run/bbox-docker.sock), so Docker Desktop may be installed, running, or absent - it makes no
REM difference. See ai/context/running-on-wsl.md.
setlocal enabledelayedexpansion

REM %~dp0 always ends in a backslash. Passing "C:\path\" to wsl.exe makes the final \" read as an
REM ESCAPED QUOTE, which swallows the closing quote, shifts every following argument, and surfaces
REM as `/bin/bash: -c: unexpected EOF while looking for matching '` from the second call - a quoting
REM error that says nothing about the real cause. Strip the trailing backslash first.
set "BBOX_DIR=%~dp0"
if "%BBOX_DIR:~-1%"=="\" set "BBOX_DIR=%BBOX_DIR:~0,-1%"

REM ---------------------------------------------------------------------------------------------
REM `bbox dialable` - whether another office can DIAL this one is a fact of the MACHINE: WSL's
REM networking mode, which is one line in %UserProfile%\.wslconfig and a restart of WSL. Neither can
REM be reached from inside the distro, so this verb is answered here and never handed over. It
REM changes nothing without a typed YES (scripts\windows\wsl-mirrored.ps1 says why it is not part of
REM `bbox run`): -Check reports only, -Undo puts the file back.
if /i "%~1"=="dialable" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%BBOX_DIR%\scripts\windows\wsl-mirrored.ps1" %2 %3 %4
  exit /b !errorlevel!
)

for /f "usebackq delims=" %%p in (`wsl.exe -d Ubuntu -e wslpath -a "!BBOX_DIR!"`) do set "BBOX_REPO=%%p"
if not defined BBOX_REPO goto :no_wsl
if "%BBOX_REPO%"=="" goto :no_wsl

REM ---------------------------------------------------------------------------------------------
REM Keep the stack alive across reboots. WSL2 is ON-DEMAND: nothing starts it at boot, and it tears
REM the distro down once the last client detaches. So a machine that has run `bbox run` will still
REM lose the whole stack on the next restart, sleep or update reboot - measured 2026-08-12, when a
REM Windows Update reboot at 06:38 left this host down for 4h37m with Windows up the entire time.
REM
REM Docker restart policies do NOT cover this: they only apply once dockerd is running, and dockerd
REM cannot run if the distro is not up. The missing link is above Docker, on the Windows side.
REM
REM Installing here (not in ./bbox) is deliberate: it is a Windows Task Scheduler task, so it cannot
REM be created from inside the distro. Idempotent, quiet, and never fails the run - if it cannot
REM register, `bbox run` still proceeds and the operator simply does not get reboot survival.
REM Runs BEFORE the handoff so the anchor also holds the distro open during a long first build.
if /i "%~1"=="run" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%BBOX_DIR%\scripts\windows\platform-keepalive.ps1" -Install >nul 2>&1
  if errorlevel 1 echo [bbox] note: reboot-survival keepalive could not be registered; the stack will still run, but will not come back on its own after a restart.
  REM The Windows firewall is converged onto what .env DECLARES (the one UDP port a listening office
  REM publishes for its tunnel - DGO_WG_PUBLISH_BIND/PORT). Here and not in ./bbox for the same reason
  REM as the keepalive: it is a Windows object, unreachable from inside the distro. Costs nothing when
  REM the state already matches; asks for administrator consent ONCE when a rule must change; never
  REM fails the run - an office with a closed door is still an office, and the note says which link waits.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%BBOX_DIR%\scripts\windows\firewall-converge.ps1"
)

wsl.exe -d Ubuntu -u root -- bash -lc "cd '%BBOX_REPO%' && ./bbox %*"
set "BBOX_RC=%errorlevel%"
REM AGAIN, after the run: a fresh office DECLARES its tunnel address during its first run (the
REM app's own prepare step writes it to .env), which is after the pass above read the file. Without
REM this second look the office said it was dialable while Windows still dropped the packets, until
REM somebody ran `bbox run` a second time. Costs nothing when the state already matches.
if /i "%~1"=="run" powershell -NoProfile -ExecutionPolicy Bypass -File "%BBOX_DIR%\scripts\windows\firewall-converge.ps1"
exit /b %BBOX_RC%

:no_wsl
echo [bbox] could not resolve this directory inside the WSL distro 'Ubuntu'.
echo [bbox] Is WSL installed and the distro present?  Check: wsl -l -v
exit /b 1
