---
id: sites.status
title: The office's websites — up or down, and what their scans found
title_he: מצב האתרים
when:
  - מה מצב האתרים
  - האתר למעלה
  - website status
inputs: {}
reaches_people: false
check: 'one line per site — its state, uptime, when it was checked, open findings — naming the office it was read on'
---
1. Every site, as lines:
   - here: `curl -sS --max-time 60 http://sites:8979/api/overview | python3 apps/sites/operatives/lines.py`
   - linked: `./bbox remote <office> <alias> /api/overview --timeout 60 | python3 apps/sites/operatives/lines.py`
2. Answer with those lines as they are; over a link they start with the office's name — say whose sites they are, not every office's. If it prints something else (exit 1), sites did not answer: say so, never "all up".
3. A "(stale)" check or a line saying the scheduler is not running means the state is old: say so with it. Open findings are what the last scan left open, not a fresh scan.
4. This only reads. Deploying, starting, stopping or publishing a site changes it for the public: those are the owner's, on the sites screen.
