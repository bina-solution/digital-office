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

From the shell, reads through the same formatter the operatives use:
- `./bbox mail connections`, `./bbox mail inbox [N]`, `./bbox mail find "<query>" [N]`,
  `./bbox mail read <id>`.
- Each takes `--connection <id>`. Without it, the mailbox used is named on stderr.
- `./bbox mail test` runs the label engine's suite against a LOCAL test mailbox only.
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

Gates: G27, G36 (pagination), G62 (the mail connection), G71, G89; its own tests (`bbox mail test`).
