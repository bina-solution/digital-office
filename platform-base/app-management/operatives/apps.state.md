---
id: apps.state
title: Which apps run as declared — and why one does not
title_he: מצב האפליקציות בלשכה
when:
  - מה מצב האפליקציות
  - איזה אפליקציות רצות
  - מה מצב האפליקציה
  - איזה אפליקציות מופעלות
  - apps state
inputs: {app: "an app id, e.g. meet — when the person named one app"}
reaches_people: false
check: 'the ready line, then one line per app that is broken, failing, or waiting on another app — or the one app asked for'
---
1. Every app, as lines:
   - here: `./bbox app-management apps | python3 platform-base/app-management/operatives/apps.py`
   - linked: `./bbox remote <office> <alias> /api/apps --timeout 120 | python3 platform-base/app-management/operatives/apps.py`
2. Instead, when the person named one app — the same command with the app's id last, `… apps.py '<app>'`:
   - here: `./bbox app-management apps | python3 platform-base/app-management/operatives/apps.py '<app>'`
   - linked: `./bbox remote <office> <alias> /api/apps --timeout 120 | python3 platform-base/app-management/operatives/apps.py '<app>'`
3. Answer with those lines as they are; over a link they start with the office's name. A line that says "waits on X" is not that app's own failure: the root is X, and the line says what X is (disabled, stopped). If it prints something else (exit 1), the control plane did not answer or could not see docker: say so, never "all running".
4. This only reads. Enabling, disabling, restarting or removing an app starts or stops services and can delete data: it is the owner's, on the apps screen.
