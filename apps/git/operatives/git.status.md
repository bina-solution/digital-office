---
id: git.status
title: The office's git — the forge, the accounts and the mirrors
title_he: מצב ניהול הגרסאות
when:
  - מה מצב הגיט
  - הפורג׳ עובד
  - מה מצב המראות של הגיט
  - כמה מאגרים יש בגיט
  - forge status
inputs: {}
reaches_people: false
check: 'the forge, the repositories, one line per account and per mirror — or which part could not be read'
---
1. The office's git, as lines:
   - here: `./bbox git overview | python3 apps/git/operatives/lines.py` (it can take a minute)
   - linked: `./bbox remote <office> <alias> /api/overview --timeout 120 | python3 apps/git/operatives/lines.py`
2. Answer with those lines as they are; over a link they start with the office's name. A part it says could not be read is unknown, never "none". If it prints something else (exit 1), git did not answer: say so.
3. This only reads. Adding an account or a mirror, and anything that pushes, is the owner's, on the git screen.
