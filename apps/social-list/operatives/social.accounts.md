---
id: social.accounts
title: The office's social accounts — which networks are connected, and how each was last found
title_he: מצב החיבור לרשתות החברתיות של הלשכה
when:
  - אילו רשתות חברתיות מחוברות
  - מה מחובר ברשתות החברתיות
  - האם הפייסבוק של הלשכה מחובר
  - social accounts
inputs: {}
reaches_people: false
check: 'one line per account: network, label, API or browser, and its last check — or that the vault did not answer'
---
1. Every account, from the credential plane (no network and no browser is asked):
   - here: `./bbox social-list accounts`
   - linked: `./bbox remote <office> <alias> /listAccounts -H 'content-type: application/json' -d '{}'`
2. If it failed (exit 1, or over a link an HTTP status of 400 or more — 502 when the vault cannot be reached), say so with its `error` and `how`: never "no accounts". When the person named one network, keep its lines; none for it is "no account on that network".
3. One line per entry of `accounts`: `platform_name`, `label`, `kind` (api or browser), "primary" when `primary` is true, and "the test network" when `test` is true. Its `probe` is the LAST check since the app started, however old: null is "not checked since the app started", never "connected"; otherwise say its `state` as the last check's — ok, `needs_action` with its `reason` and `how`, `unsupported` (no check exists for it), or error.
4. This only reads. Checking an account (for a browser account a check drives the office browser), connecting one, posting and replying are the owner's, on the screen.
