---
id: tv.status
title: Is Telegram TV connected and working — its films and its sync
title_he: מצב טלגרם TV
when:
  - הטלגרם TV עובד
  - מה מצב הטלגרם
  - כמה סרטים יש בטלגרם
  - מה מצב הסנכרון של הטלגרם
  - telegram tv status
inputs: {}
reaches_people: false
check: 'one line: connected or not (with the reason as it is), the films and chats, the last sync and a running one'
---
1. The library's state (it can take a few seconds: it asks Telegram who the account is):
   - here: `curl -sS --max-time 60 http://telegram-tv:8982/api/status`
   - linked: `./bbox remote <office> <alias> /api/status --timeout 60`
2. Over a link, name the office; an HTTP status of 400 or more is a failure. Here, a curl error or an empty answer means telegram-tv did not answer. Either way say so, never "no films".
3. If `ok` is not true, Telegram does not work there: say `reason` exactly. With no `instance`, no account is connected — connecting is the owner's, in the app (QR, or phone and code): never ask for a code.
4. Otherwise one line: the account's `label`, `counts.movies` films in `counts.chats_enabled` of `counts.chats` chats, whether a sync ever ran (`last_sync` null = never; do not work out its time), and when `job.state` is `running` its `phase` and `index`/`total`; a `job.error` is said as it is.
5. This only reads. A refresh (a sync of every chat) and connecting an account are not part of it.
