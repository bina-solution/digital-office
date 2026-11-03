---
id: chat.accounts
title: The chat's accounts — WhatsApp, Telegram, the local chat — and whether each answers now
title_he: חשבונות הצ׳אט ומצבם
when:
  - האם הוואטסאפ של הלשכה מחובר
  - איזה חשבונות צ׳אט מחוברים
  - האם הבוט של הוואטסאפ מחובר
  - מה מצב הצ׳אט
  - chat accounts
inputs: {}
reaches_people: false
check: 'one line per account: label, provider, whether its live check passed (or why not), the bot attached — or that the accounts could not be read'
---
1. The accounts, from the credential plane:
   - here: `curl -sS --max-time 60 http://chat:3000/api/accounts`
   - linked: `./bbox remote <office> <alias> /api/accounts --timeout 60`
   A curl error, an empty answer, an HTTP status of 400 or more, `reachable` false or an `error` means they could not be read: say so, never "no accounts". Their `status` is what was SAVED, not a check.
2. Then each account's live check — it reads the session's state and changes nothing:
   - here: `curl -sS --max-time 60 'http://chat:3000/api/readyz?connection_id=<id>'`
   - linked: `./bbox remote <office> <alias> '/api/readyz?connection_id=<id>' --timeout 60`
3. One line per account: `label`, `provider`, then from its check — `ready` true is "answers now"; otherwise not, with `reason`, and `qr` true means it waits to be paired again. Add `activeBot` when one is attached, and say which account is `active` (the screen's selection). Leave out `identity` and `self.number` — phone numbers — unless the person asked for them.
4. This only reads. Sending, broadcasting, re-pairing (a QR) and choosing the account reach people or change what others see: they are the owner's, on the chat screen.
