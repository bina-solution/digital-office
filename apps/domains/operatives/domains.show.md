---
id: domains.show
title: One domain — its registrar, expiry and nameservers
title_he: פרטי דומיין
when:
  - מתי פג הדומיין
  - פרטי הדומיין
  - איפה רשום הדומיין
  - מה השרתים של הדומיין
  - domain details
inputs: {domain: "the domain the person named, lower case, no quotes or spaces, e.g. example.co.il"}
reaches_people: false
check: 'the registrar, expiry date and nameservers from data.registry — or why there are none'
---
1. The domain, as the office knows it:
   - here: `curl -s --max-time 180 -X POST http://domains:8980/getDomain -H 'content-type: application/json' -d '{"domain": "<domain>"}'`
   - linked: `./bbox remote <office> <alias> /getDomain --timeout 180 -H 'content-type: application/json' -d '{"domain": "<domain>"}'` (a registrar's panel can take two minutes on a cold read)
2. If the answer has a top-level `error` (an HTTP status of 400 or more — 502 when the vault cannot be reached), the read failed: say so with that `error`, never "not watched". Otherwise read `data.registry`: answer with its registrar, `expiry_date` (and `days_left`), `nameservers` and `status`, one line each.
   - If `data.watched` is false or `data.registry` is empty, say the office does not watch that domain, with its `note`.
   - If `data` carries `status_code` and `body`, the read FAILED even though the answer says ok: say it failed and give the `body`.
3. This writes nothing, but for a browser account (a registrar with no API) it reads the registrar's panel in the office browser the owner watches: run it once, never in a loop. A DNS change goes through the domains screen, where a person approves it.
