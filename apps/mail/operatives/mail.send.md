---
id: mail.send
title: Send an e-mail
title_he: שליחת מייל
when:
  - שלח מייל ל
  - תשלח מייל ל
  - תכתוב מייל ל
  - תשלח לו במייל
  - send an email to
inputs: {to: "a full e-mail address the person wrote — for a name with no address, ask for the address; never guess one", subject: "a short subject", body: "the text, in the person's language"}
reaches_people: true
acts: true
check: 'the answer carries "id" or "ok": true'
---
1. Write valid JSON with the file tool to the file /tmp/mail.json: `{"to": "<to>", "subject": "<subject>", "body": "<body>"}` — a line break in the body is `\n`, a double quote is `\"`.
2. Send that file, with bash:
   - here: `if [ -n "$(find /tmp/mail.json -mmin -5 2>/dev/null)" ]; then curl -s -X POST http://mailview:8976/api/send -H 'content-type: application/json' -d @/tmp/mail.json; else echo "NOT SENT: /tmp/mail.json was not written just now"; fi; rm -f /tmp/mail.json`
   - linked: `if [ -n "$(find /tmp/mail.json -mmin -5 2>/dev/null)" ]; then ./bbox remote <office> <alias> /api/send -d @/tmp/mail.json; else echo "NOT SENT: /tmp/mail.json was not written just now"; fi; rm -f /tmp/mail.json`
3. Say it was sent, with the id it returned — or the answer exactly as it came. If writing the file failed, nothing is sent.
