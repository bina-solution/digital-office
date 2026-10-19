' hidden-run.vbs - run a command with NO window at all, and wait for it.
'
' WHY THIS EXISTS
' Task Scheduler with an Interactive principal shows a console window for console applications.
' wsl.exe and powershell.exe are both console applications, so the platform keepalive popped a
' visible terminal every 2 minutes and the health check every 5. Reported twice by the owner on
' 2026-08-12 while trying to work on the machine.
'
' -WindowStyle Hidden on powershell.exe is NOT sufficient: the process still creates its console
' and then hides it, which is a visible flash. That was the failed first attempt.
'
' WScript.Shell.Run with intWindowStyle=0 never creates a visible window in the first place, and
' wscript.exe itself is a GUI-subsystem binary so it has no console of its own. This is the only
' approach that is genuinely silent.
'
' bWaitOnReturn=True is load-bearing. It makes wscript block for the child's whole lifetime, so
' Task Scheduler keeps the task in the Running state - which is what makes
' MultipleInstances=IgnoreNew work as the duplicate guard for the long-lived WSL anchor. With
' False the task would "complete" instantly and every trigger would start another anchor.
'
' Usage:  wscript.exe //B //Nologo hidden-run.vbs <program> [args...]
' Arguments containing spaces are re-quoted, because WScript.Arguments strips the quoting that
' Task Scheduler passed in and the .ps1 path contains spaces.

Option Explicit

Dim sh, cmd, i, a
Set sh = CreateObject("WScript.Shell")

cmd = ""
For i = 0 To WScript.Arguments.Count - 1
    a = WScript.Arguments(i)
    If InStr(a, " ") > 0 And Left(a, 1) <> """" Then
        a = """" & a & """"
    End If
    If i > 0 Then cmd = cmd & " "
    cmd = cmd & a
Next

If Len(cmd) = 0 Then
    WScript.Quit 2
End If

WScript.Quit sh.Run(cmd, 0, True)
