# signin-log.awk — what became of the desktop's last «Continue with Google» (DGO-1506), read from
# /config/.claude-open-url.log, which desktop/signin-browser and desktop/claude-desktop write. Prints one line,
# "<UTC time> <state>", or nothing when no sign-in was opened through this desktop's browser:
#   opened     the sign-in window is open, waiting for Google
#   delivered  claude.ai's answer reached the running app
#   failed     the answer came back but the app did not take it
#   dropped    the answer came back while the app was not running
#   closed     the window closed (by the person, or its time ran out) before Google answered
# Each window is named (window=<id>): a second press closes the first press's window, and that window's
# "closed" line arrives AFTER the second "opened" — it belongs to the earlier attempt, not the open one.
# hooks/signed-in passes this file to the desktop container; test_signin_browser.sh feeds it lines.
/ opened sign-in / { s = "opened"; t = $1; w = $NF; next }
/ delivered sign-in answer / { if (s != "") { s = "delivered"; t = $1 } next }
/ failed to deliver sign-in answer / { if (s == "opened") { s = "failed"; t = $1 } next }
/ dropped sign-in answer / { if (s == "opened") { s = "dropped"; t = $1 } next }
/ closed sign-in window=/ { if (s == "opened" && $4 == w) { s = "closed"; t = $1 } next }
END { if (s != "") print t, s }
