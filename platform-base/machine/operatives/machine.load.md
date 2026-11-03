---
id: machine.load
title: How loaded is the machine — CPU, memory, disk
title_he: עומס המכונה
when:
  - כמה עמוס המחשב
  - מה העומס על המכונה
  - יש מקום בדיסק
  - כמה זיכרון פנוי
  - machine load
inputs: {}
reaches_people: false
check: 'one line, naming the office when it was read over a link: load on cores, CPU, memory, disk'
---
1. The machine now, as one line:
   - here: `curl -s --max-time 120 http://machine:8080/api/overview | python3 platform-base/machine/operatives/load.py`
   - linked: `./bbox remote <office> <alias> /api/overview --timeout 120 | python3 platform-base/machine/operatives/load.py`
2. Answer with that line as it is. When it was read over a link it starts with the office's name: say whose machine it is, never as this office's. If it prints something else (exit 1), the machine did not answer: say so, never "idle".
3. Before a build: if it says busy, memory above 90%, disk above 90%, or the host under the VM is short of memory, say the build should wait, and why. This only reads: a cleanup or a power change is the owner's.
