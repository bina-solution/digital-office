---
id: mail.find
title: Find mail by sender, label or words
title_he: חיפוש מייל לפי שולח, תווית או מילים
when:
  - תמצא את המייל מ
  - חפש במייל את
  - מיילים עם התווית
  - find the email from
inputs: {q: "the words the person asked for, e.g. חשבונית — or from:dana@example.org, label:חשבוניות, newer_than:7d; several joined by +"}
reaches_people: false
check: one line per match — date | from | subject | id
---
1. The query is the person's own words: «חפש במייל חשבונית» → `q=חשבונית`; «מיילים מדנה מהשבוע» → `q=from:dana+newer_than:7d`.
2. Search, one line per match:
   - here: `curl -s "http://mailview:8976/api/messages?q=<q>&limit=5" | python3 apps/mail/operatives/lines.py`
   - linked: `./bbox remote <office> <alias> "/api/messages?q=<q>&limit=5" | python3 apps/mail/operatives/lines.py`
3. Answer with those lines, nothing added. "0 messages" is "nothing matched"; a failed answer (exit 1) is said as it is.
