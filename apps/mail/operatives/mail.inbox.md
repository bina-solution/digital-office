---
id: mail.inbox
title: The latest mail in the inbox
title_he: המיילים האחרונים בתיבה
when:
  - מה הגיע במייל
  - יש מיילים חדשים
  - תראה לי את המיילים האחרונים
  - check my inbox
inputs: {unread: "put `view=unread&` before `limit` for unread only"}
reaches_people: false
check: one line per message — date | from | subject | id
---
1. The latest five, one line each:
   - here: `curl -s "http://mailview:8976/api/messages?limit=5" | python3 apps/mail/operatives/lines.py`
   - linked: `./bbox remote <office> <alias> "/api/messages?limit=5" | python3 apps/mail/operatives/lines.py`
2. Answer with those lines, newest first, nothing added. A failed answer (exit 1) is said as it is, never as "no new mail".
