# Operating «מייל» (the `mail` app)

The office's mail: the client's real mailboxes (Gmail) and the office's own local server (Postfix
and Dovecot), behind one mail API. An n8n workflow labels every reachable mailbox every 15 minutes.
Each mailbox is a **connection**, an account in the credential plane. **Name the mailbox you mean.**

## The doors

- **`mailview` (`http://mailview:8976`)** is the screen's own API. Agents use it, and the operatives
  call it:
  - `GET /api/connections` lists the mailboxes and which one is selected.
  - `GET /api/messages?q=<gmail query>&label=<label>&view=attention&limit=20` lists messages.
  - `GET /api/message/<id>`, `GET /api/thread/<id>` and `GET /api/attachment/<id>/<n>` read them.
  - `GET /api/labels` lists the labels, and `POST /api/labels` creates one.
  - `POST /api/tag` and `POST /api/mark` change a message's labels; archive removes INBOX.
  - `POST /api/send {to, subject, body}` sends.
- **`mailapi` (`http://mailapi:8970`)** is the mail.v1 contract other apps call: `/search`,
  `/message/<uid>`, `/thread/<tid>`, `/labels*`, `/append`, `/send`. `/append` writes messages INTO
  the named mailbox; a test run once left 148 messages in the client's real Gmail this way.
  - Every one of these needs a `connection_id`, and answers 400 without it.
  - It has no sign-in of its own and is not routed outside the office network.
- **`mailboxd`** is the only writer of the local server's accounts.

From any office's shell (`bbox mail …` and `dgo mail …` are the same door), reads through the same
formatter the operatives use:
- `./bbox mail profile list` lists every mailbox and the default (`*`); `connections` is the same as JSON.
- `./bbox mail -p <mailbox> inbox [N]`, `find "<query>" [N]`, `read <id>`, `thread <id>`, `labels`. `-p` (or
  `--connection`) names a mailbox by its address, its name or its id. Without it, the mailbox used is named on
  stderr.
- `mark <id>… starred|important|unread|archived [--off]` and `tag <id> +label -label` change labels through
  the screen's own /api/mark and /api/tag. A write refuses without `-p`. Sending stays with the screen.
- On an office that does not run the mail (the MacBook) the same commands reach the one that does, through
  the link.
- `./bbox mail test` runs the label engine's suite against a LOCAL test mailbox only.

The screen lists every mailbox in its menu («חשבונות») and shows the one chosen in THAT window (`?mailbox=`
in its address, `connection_id` on its calls): looking at another mailbox moves nothing on the server.
«חיבור חשבון» connects Gmail by signing in with Google (one consent: Gmail and Drive; it returns through the
herd's public door, connections `OAUTH_RELAY_URL/oauth/relay`) or by an app password.
Recipes: `./bbox ops find "שלח מייל"` (`mail.inbox`, `mail.find`, `mail.read`, `mail.send`). On a linked
office: `./bbox remote <office> mailview '/api/messages?limit=5'` (quoted: zsh expands a bare `?`).

## Rules

- **Pass `connection_id` on every call** (query string, or the JSON body of a POST). Without it,
  mailview uses the mailbox selected in the account bar. That choice is shared, cached for 30 s, and
  may be a client's real Gmail. Read `GET /api/connections` first.
- **`POST /api/send` reaches a person, from that mailbox.**
  - The server checks only that `to` is not empty, so the guard is yours: send only what the owner
    asked, to an address a person wrote. Never guess an address.
  - Follow `mail.send`: the message goes in a file and the send is one command. Put
    `"connection_id"` in that file beside `to`, `subject` and `body`, because the operative's own
    example omits it.
- Tags and marks change the client's mailbox in Gmail itself. Create a label, or change the
  organizer's settings (`/organizer/*`), only when told to.
- **Never without the owner's words:**
  - `DELETE /api/mailboxes/<address>` or `DELETE /api/connections/<cid>`;
  - `POST /api/connections/select`, which moves the selection every call without a `connection_id`
    falls back to;
  - `/append` into any mailbox but a local test one.

## Traps

- A local send the mail server refuses still answers **HTTP 200**, with `"ok": false` and
  `"delivered": "no"`. Success reads `"queued"`, not delivered, so read the JSON, not the status.
- `label:<a label that does not exist>` in a query is an error, not zero messages.
- The inbox is the INBOX folder, not a search. `view=attention` merges the failure labels.
- `connections.override.yml` is stale: it names a service `inbox` that no longer exists.

## A second domain — a company address whose MX is this machine

`MAIL_DOMAIN` (the deployment's subdomain) stays the default. A COMPANY domain whose MX also points
here (staging serves `hello@digital-office.co.il`) is DECLARED, never assumed:

- `.env` `MAIL_DOMAINS=digital-office.co.il` (comma/space list), read by `mailboxd`, `mailserver-init`
  (an account at a served domain is kept; at an unserved one, deleted as a previous tenant's) and the
  engine reconciler.
- the account is a profile with a `domain` (`app.json` → `engine.profiles`; `POST /connections` refuses
  local logins), brought up only where `MAIL_DOMAINS` names it.
- DKIM: `mailserver-init` keys and signs every served domain (DGO-1389); `mailsetup` names the TXT
  record each needs (`<MAIL_DKIM_SELECTOR>._domainkey.<domain>`). Keys are create-only.
- receiving needs port 25 published: `MAIL_BIND=0.0.0.0`. At the default `127.0.0.1` **no mail from
  the internet arrives**.

Gates: G27, G36 (pagination), G62 (the mail connection), G71, G89; its own tests (`bbox mail test`).
