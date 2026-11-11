# DGO-1640 — autofill from «חיבורים ומפתחות»

Research item from the product review of Exampleu's office (`bina-261109-vjlwcr`, MEET-28, 2026-11-09),
lane handed over by the MacBook's coordinator. **Nothing here was installed, enabled or changed on a
live office.** Every claim about our own code names the file it was read in; the three numbers marked
«measured» were measured today on the HP's own vault and browser.

**Recommendation: finish DGO-1031 rather than design something new — the bridge exists and is 767
lines deep, and what is missing is a first-class LOGIN row (address + user name + password + "fill in
the office browser"), one generic `task login` path instead of one site's, an audit line per fill, and
a written proof of the vault's encryption.** The rest of this document is the argument, the design,
and — the part that matters most — what the security model does and does not hold.

---

## 1. What the owner asked, in his words

> «יש לנו פה סיסמה ל-n8n … אני רוצה שזה פשוט יופיע השלמה אוטומטית ברגע שאתה פותח אפליקציה בתוך
> הלשכה … וכבר … דיברתי על זה פעם, ומוזר מאוד שזה לא בוצע» [49:03–49:49]
>
> «תוודא שזה באמת מוצפן בפנים … לפי הסטנדרטים הכי גבוהים שיש לאחסון של סודות» [1:05:06–1:05:21];
> «כל פעם שמישהו … הקיש סיסמה … שהיה שימוש בחיבורים ומפתחות» — ב«כל מקביל» [1:05:52–1:06:02]
>
> «… את הסיסמה שלי לפייסבוק … לגוגל … לאוסטינגר ולקלוד … ואז אני יכול לדבר עם הסוכן … תיכנס לפייסבוק
> ותייצר פוסט, והוא לא צריך את הסיסמה … נכנס לדפדפן הלשכה» [1:06:12–1:06:49]
>
> «צריך שיהיה לי … הקישור, באיזה דף זה מופעל (accounts.google.com) … השם משתמש … הסיסמה … ואז כל פעם
> שאני נכנס בדפדפן … זה פשוט אמור להציע לי את זה … או שזה פשוט ישלים אוטומטית» [1:07:43–1:09:30]

The acceptance on the item: **a new secret has an address, a user name and a password; in the office
browser (b42) and in an app of the office, a login page at that address gets an offer or a fill; the
agent performs such a sign-in without the password passing through it; every fill is recorded in «כל
מקביל»; the vault's encryption is checked and written down.** Measured on InterNIC and on Exampleu's n8n.

Note «מוזר מאוד שזה לא בוצע» — and he is half right and half wrong, and knowing which half is the whole
item: **the bridge was built (DGO-1031, `apps/browser42/logins.py`), the CARD was not.**

---

## 2. What exists today, measured

### 2.1 The vault — `platform-base/connections`

| | |
|---|---|
| at rest | `/app/data/vault.enc`, **60,280 bytes**, mode `0600`, a single Fernet token (`gAAAAAB…`), and **zero occurrences of the string `password`** in it — measured 2026-11-09 on the HP |
| crypto | `cryptography.fernet.MultiFernet` — AES-128-CBC + HMAC-SHA256, key = `sha256(CONNECTIONS_ROOT_KEY)` (`app.py:47`); rotation with `CONNECTIONS_ROOT_KEY_OLD`, `rekey()` re-encrypts in place; `VaultUnreadable` is raised rather than reading an unopenable vault as `{}` (`test_vault_keys.py` exists for exactly that) |
| the key | `CONNECTIONS_ROOT_KEY` **is set** in this office's `.env` and is **not** the code's public `DEV_ROOT_KEY` (`app.py:42`) — checked without printing it. A vault still on the public key is warned about at every start |
| who may read a value | `POST /api/reveal/<cid>` — deliberate, rate-limit-free, **audit-logged** (`_audit("reveal", …)`); `GET /api/broker/lease` for another container, under its own identity, with a grant log |
| the broker | `broker.py` — caller named from OUTSIDE the request (docker socket → container id → compose service), a caller gets only the connections its own `app.json` declares, single-use short-lived tokens, every grant in `grants.jsonl`. Modes `warn|enforce|off` |
| measured | `grants.jsonl` is **3.9 MB** with an **8.3 MB** rotated predecessor — the log is real and busy. `CONN_BROKER_MODE` is **unset** on this office, i.e. `warn`: an *identified* caller is already held to the full policy, an *unidentified* one is still served and logged as such |
| one finding | `grants.jsonl` is mode **`0644`** (world-readable) while `vault.enc` is `0600`. The grant log names connection ids and callers, never values — but a file that is only ever appended by one process has no reason to be world-readable |

### 2.2 What a "secret" is on the screen today

The add-a-secret form (`ui.html:1352`, `addSecret()`) asks for **four things**: `id`, a title, a
category (אימות / סיסמת אפליקציה / סודות מערכת) and **the value**. There is no address, no user name,
no "suggest this in the browser" checkbox. That is the owner's sentence, exactly: «צריך שיהיה לי …
הקישור … השם משתמש … הסיסמה».

The DATA model behind it is richer than the form: a catalog row (`connections/providers/*.yaml`) may
carry an `app:` block — `{name, url, url_env, user, user_env}` — which `_resolve_app()` resolves live
from the environment (`app.py:351`) and which the screen already renders as "open app" + a login hint.
`kind: app-password` even maps to protocol `basic-auth` (`_KIND_PROTOCOL`). So **the shape
`{address, user, password}` already exists in the catalog; what does not exist is a row a person
creates that way, or a checkbox on it.**

Ten kinds exist: `text-secret`, `password`, `derived`, `config`, `oauth-client`, `oauth-grant`,
`qr-session`, `sa-key`, `cert`, `app-password`, `totp`. A multi-field credential is created
programmatically today by the browser bridge itself (`plane_create_custom()`,
`apps/browser42/logins.py:334`) as `<PREFIX>_PASSWORD` + `_USER` + `_URL` companion fields — i.e. the
bridge already builds exactly the card the owner wants, from the wrong end (harvest) and with no
checkbox.

### 2.3 The office browser — `apps/browser42`

`logins.py` (767 lines) is the two-store bridge, and its header is the design:

* **the plane is the source of truth, Chrome's manager is a MIRROR** kept for the human — disposable,
  rebuildable, never the only copy;
* the key that ties them is the **origin**; discovery is by metadata (`app.url` or a `*_URL` field + a
  password field), so a new site is a new credential and not a code change;
* **MATERIALIZE** (plane → Chrome) and **HARVEST** (Chrome → plane) both run on every sync, conflicts
  resolved by "which side moved", fingerprinted by HMAC (never a value) in `/data/browser-logins.json`;
* **deletion is asymmetric on purpose**: removing a credential removes the Chrome rows *this bridge
  wrote*, and a browser-side spring-clean can never delete an office credential;
* the crypto is the container's keyring-less **basic** store: PBKDF2-HMAC-SHA1(`peanuts`, `saltysalt`,
  1, 16) → AES-128-CBC, and the module refuses to write when `os_crypt.encrypted_key` says a real
  keyring is in use;
* two traits were measured and are written in the code because they cost a day each: a login filed
  under `:8080` is never offered (Chromium matches by origin *including port*), and a `signon_realm`
  without the trailing slash is stored, listed and never offered.

`start-browser.sh` calls `logins run-queued` at boot, so the mirror is refreshed when the browser
starts. `bbox b42 logins list|sources|sync|materialize|harvest|export|sessions|await` is the whole
surface.

**The agent's own sign-in** is already the right shape and is the model to generalise:

```python
# apps/browser42/group-manager.py:1135  lease_connection(cid)
POST http://connections:8990/api/broker/lease   {"service": "browser42-task-runner", "connections": [cid]}
X-Conn-Container: <our own container id>
```

`bbox b42 task login <slug> <site>` takes **the site, never the credential** (the arity guard in
`task-runner.py` is exactly 3 for that reason), leases the value under the container's own identity,
types it through CDP, and returns which selectors matched and whether the login form is gone — never a
value. A second factor is minted, not disclosed: `GET /api/totp/<id>` returns a live code and the
secret never arrives (`LOGIN_TOTP_PREFIX`). And `logins sessions` / `logins await` answer the honest
question — "is this browser SIGNED IN" — from cookie names and expiries only.

**And here is the gap, in one number: `LOGIN_FLOWS` has exactly ONE entry.** `facebook`
(`group-manager.py:1096`). Every other site answers `unknown_login_site`. So the agent can sign in
without a password to one site out of the owner's four (Facebook, Google, Ostrander, Claude).

### 2.4 The app inside the office — why "autofill in the tile" is not the same problem

`platform-base/console/app.py:536` states the constraint in its own words: each app is its own
SSO-gated service on its own `*.localhost`, which **cannot be iframed cross-origin**; the shell
therefore frames it at `/a/<alias>/…` — **on the console's own origin**.

Consequence, and it is the crux of this item: inside the tile, Chrome's password manager sees the page
as `console.localhost`, not as the app's own host. Native autofill therefore can never distinguish
"this app's login" from any other app's inside the shell — a row filed for `n8n.localhost` is a row for
a different site. **Native autofill is structurally the wrong tool for the tile.** The tile has two
honest answers instead: the office's sign-in (which is what n8n and Plane already do today — the owner's
«כמו שקורה עכשיו»), and, for an app that has only its own login form, a sign-in performed for him on
the server side (§4.3).

Outside the tile — the browser's own tab at the app's real address, `http://n8n.localhost/` via
`localhost-forward.py` — native autofill works, and it is what the bridge already feeds.

### 2.5 The extension that makes a suggestion UI possible

`apps/browser42/extension/` is a Manifest V3 extension already loaded in the office browser:
`browser42-groups`, **`<all_urls>` host permission**, a content script at `document_start` (`cursor.js`,
75 lines), a service worker (415 lines) and an offscreen document talking to the container over
`ws://127.0.0.1:8765`. Everything a password-manager extension needs — a page hook at load, a channel
to the trusted side, a per-origin context — **is already in place and is used today only to draw a
cursor.**

---

## 3. So what is actually missing

1. **The card.** A row that is a login: address, user name, password, and a checkbox «להציע בדפדפן
   הלשכה». Today: four fields with none of the three the owner named, and no checkbox anywhere.
2. **The checkbox has nothing to gate.** `logins sync` materializes *every* credential it can resolve —
   so "save it but do not offer it" is not expressible.
3. **One site's login flow.** `LOGIN_FLOWS` = `{facebook}`. The agent path works for the site we built
   it for.
4. **No audit of a fill.** «חיבורים ומפתחות» audits `reveal/edit/rotate/connect/revoke` and the broker
   logs every grant — but a *fill* (the person's own autofill in the browser) writes nothing anywhere.
   Chrome's own `Login Data` carries `times_used` and `date_last_used` per row and the bridge already
   opens that table; nothing reads them.
5. **The encryption is true but unwritten.** The vault is a Fernet file; nothing states it where the
   owner reads it, and nothing checks it after the fact.
6. **No ticket when there is no credential** (DGO-1031's second half): the agent should open a card
   with a link to a "add this login" form that already names the site.

---

## 4. The design

### 4.1 The login card (one row, four facts)

A first-class **kind `login`** (protocol `basic-auth`, so the existing protocol machinery and the
`app:` hint keep working) with:

```
{id, title, kind: "login", address, username, password, autofill: true, totp_id?}
```

`address` and `username` are **clear** fields (a URL and a user name are not secrets, and both the
screen and the bridge need to read them without a reveal); `password` is the row's primary secret
(the only encrypted one); `autofill` is **metadata on the row, not a secret** — a "prefs" object in the
vault entry with one route, `PUT /api/cred/<cid>/prefs`, so a checkbox never costs a key rotation and
never shows up as a field.

The form becomes what he asked for: «הוספת סיסמה» → כתובת, שם משתמש, סיסמה, ☑ להציע בדפדפן,
אימות דו-שלבי (optional, a `totp` row beside it). «הוספת סוד» stays where it is for the other nine
kinds; the two are different acts and get different buttons.

`logins.py` learns three things from that row: the origin comes from `address`, the user name from
`username`, and **`autofill: false` means "keep it in the vault, never put it in Chrome"** — which is
the checkbox's whole meaning.

### 4.2 The fill, in the browser's own tab (the common path)

Unchanged in principle, and that is the point — it already works:

```
connections (vault)  --lease-->  logins.py  --materialize-->  Chrome Login Data  -->  native autofill
                                        \--fingerprints---> /data/browser-logins.json
```

On a page at the address's origin, Chromium offers the login itself; the person presses «התחבר». The
plaintext exists in exactly two places: the vault (encrypted) and Chromium's own password store (the
container-local basic store). **The agent is never in this path**, which is the property the owner
asked for.

**The audit** (missing gap 4) is a read the bridge is already able to make: a `logins watch` pass —
every 60 s, or at the browser's next boot — reads `times_used`/`date_last_used` from `Login Data`,
compares them with the previous pass's copy (which the state file already keeps), and for each change
posts

* one `connections.fill` event on `dgo:flow:connections` (`{origin, username_len, at}` — a length, never
  a value, exactly as `logins list` reports), and
* one span to «כל מקביל» (`POST http://any-concurrency:8080/ingest/span`, which exists and is always on).

That is «כל מקביל» showing every use of a password, which is what he asked for — and it needs no new
mechanism, only a reader.

### 4.3 The app inside the office — the tile

Two modes, chosen by what the app is, never by a heuristic:

**(a) The app has an SSO door** (n8n, Plane, drive, every office app that declares `auth: "sso"`):
nothing to do. That is the behaviour he praised.

**(b) The app has only its own login form** (a hosting panel, a router, a supplier's site inside the
office's world). Native autofill cannot help (§2.4) — the frame is the console's origin. The honest
design is a **server-side sign-in the console performs for the declared app**, and it is a
DECLARATION, not a guess:

```json
"routing": [{ "module": {
  "login": { "credential": "browser42-login-<site>", "form": {
      "post": "/login", "user_field": "username", "pass_field": "password", "extra": {"remember": "1"} } } } }]
```

The console's proxy — which already holds the app's origin, sees the form, and is already the thing the
browser talks to — asks the broker for that one credential (a lease under the console's own identity,
logged), POSTs the form on the server side, and hands the app's session cookie to the browser. The
password never enters the browser, the page's JS, or the agent's context. The declaration is per app
and per form, so nothing guesses; and an app with no `login` block is never attempted.

This is a **later slice** (§6), because it touches the console — but it is the only design that answers
«אפליקציה בתוך הלשכה» honestly, and saying so now is cheaper than a person discovering it later.

### 4.4 The agent's sign-in, generalised

`bbox b42 task login <slug> <site>` keeps its shape (the site, never the value) and gains a **generic
flow** for a site that has no hand-written one:

1. `address`, `username` and the password come from the leased `login` row — so a new site needs **no
   code**, only a card;
2. field discovery is by the HTML standard's own vocabulary first — `input[autocomplete=username]`,
   `input[autocomplete=current-password]`, `input[type=password]` — then the heuristics the code
   already uses (`input[type=email]`, `input[name*=user]`), and **a page where none resolves fails
   loudly with the list it tried**, which is the existing rule and the reason `facebook`'s hand-written
   selectors stay: a hand-written flow still wins when it exists;
3. the one-time code, if the card names a `totp` row, is minted (`/api/totp/<id>`) and typed and
   forgotten;
4. the answer is what it already is: which selectors matched, and whether the login form is gone.
   `logins sessions <site>` then proves the session with a cookie's name and expiry.

Measured on the four the owner named, this is the difference between 1/4 and 4/4 — with Google
expected to need §5's caveat (it may refuse a browser it does not trust) and Claude's «Continue with
Google» already having its own hand-off (DGO-1336).

### 4.5 When there is no credential

The agent, finding a login page for a site the vault does not hold, opens a card (a Plane work item
labelled `בעלים`, DGO-1031's own wording) with **a link to the add-login form, pre-filled with the
address it saw**: `/a/connections/#new-login?address=https://internic.co.il/login`. The owner types
three things once; the next visit offers it. Never a password in chat, never a password on a command
line.

### 4.6 The encryption, written down and checkable

One verb, `./bbox connections vault-check` (read-only), prints the facts a person needs:

```
vault.enc 60280 bytes  mode 0600  fernet: yes  opened by: CONNECTIONS_ROOT_KEY (not the public default)
rekey: CONNECTIONS_ROOT_KEY_OLD unset  entries: N  audit entries: N  grant log: 3.9 MB, mode 0644 (should be 0600)
```

and a test (`test_vault_keys.py` already covers rotation and `VaultUnreadable`) that proves the file on
disk is ciphertext. The app's AGENT.md gets the plain sentence: **the vault is AES-128-CBC + HMAC under
one root key from `.env`; a copy of the vault file without that key is useless, and a copy WITH it —
`.env` — is everything.** That is the honest statement of the ceiling, and it belongs in the docs the
owner reads, not only in a module docstring.

---

## 5. The security model, plainly

**What holds.**

* At rest the vault is ciphertext under one root key that is not in the repository
  (`CONNECTIONS_ROOT_KEY`, verified set on this office and not the public fallback), rotation is a
  two-key step with a re-encrypt, and an unopenable vault raises instead of reading as empty.
* A container can only lease what its own `app.json` declares, it is named from outside the request
  (docker socket → container id), the grant is short-lived and single-use, and every grant is an
  append-only line. In `enforce` mode an unidentified caller is refused outright.
* **The agent never holds a value**: `task login` takes a site name, the value is leased at the moment
  of typing and goes straight into the page through CDP, `fill` is documented as the verb that DOES
  leak and must never carry a secret, `logins list/sources/sessions` report lengths, names and
  expiries. A one-time code is minted, never disclosed.
* Deletion is asymmetric: a browser-side clean-up cannot destroy the office's copy.
* Inside a tile the browser sees the console's origin, so a fill for that app has to be done by the
  office (§4.3) — which is strictly better for the owner than a password in a frame.

**What does not hold, and must be said in those words.**

1. **Chromium's basic store is not encryption.** In a container with no keyring the key is
   `PBKDF2("peanuts", "saltysalt", 1)` — public. Anything that can read the profile volume, or run in
   that container, can read every mirrored password. The vault is the protected copy; the mirror is a
   convenience, and the profile volume is therefore treated as a credential store (backed up, dumped
   encrypted).
2. **A fill puts the value in the page.** No design changes that: the field the person presses «התחבר»
   in holds the password. "The agent never sees it" is achievable and is what we guarantee; "the value
   never exists in the browser process" is not, and no password manager claims it.
3. **A password in a command line is in `ps`, the shell history and the task journal.** That is why
   `fill` is documented as never-a-secret, why `task login`'s arity is exactly 3, and why the
   generalised flow (§4.4) leases rather than accepts.
4. **The broker is in `warn` on this office (measured: `CONN_BROKER_MODE` unset).** An identified caller
   is already held to the full policy; an unidentified one is served and logged. Moving to `enforce` is
   a decision with a real chance of stranding a consumer that boots anonymously — it is the owner's, and
   it belongs in this item as a measured state, not as a quiet change.
5. **`.env` is the root of everything.** Whoever holds it can open any vault copy. The security of this
   feature is the security of that file, which is why the answer to «האם זה מוצפן» is "yes, and here is
   the one file that would break it".
6. **A session is not a password.** `logins sessions` answers "signed in" from cookie names — it does
   not, and cannot, prove the person is who the site thinks.

---

## 6. The work, in slices (the plan is `apps/project-pln/plans/credentials-autofill.yaml`)

1. **autofill-001 — research and this document** (done).
2. **autofill-002 — the login card**: kind `login`, the four fields, `PUT /api/cred/<cid>/prefs`, the
   add-login form, and `logins.py` honouring `autofill: false`. Proof: a card created in the screen
   appears in `logins sources` with the right origin, and with the box off it never appears in Chrome.
3. **autofill-003 — the audit**: `logins watch` → `connections.fill` on the flow + a span in «כל מקביל».
   Proof: a real autofill on InterNIC moves `times_used` and a span is on the timeline.
4. **autofill-004 — the generic agent login** (§4.4), measured on the four sites he named.
5. **autofill-005 — no credential → a card with a pre-filled link** (§4.5).
6. **autofill-006 — the vault check verb and the written statement** (§4.6), plus the `grants.jsonl`
   mode.
7. **autofill-007 — the tile: the console's declared server-side sign-in** (§4.3) — a console change,
   so it is its own item with its own gates.
8. **autofill-008 — enforce?** the broker's mode, its consumers and the order to flip them: an owner
   decision with the list in front of him.

---

## 7. Recommendation, in one paragraph (Hebrew, for the item)

מומלץ **לסיים את DGO-1031 ולא לתכנן מחדש**: הגשר בין «חיבורים ומפתחות» לדפדפן הלשכה כבר קיים ועמוק
(`apps/browser42/logins.py`, 767 שורות — הכספת היא מקור האמת, כרום הוא מראה, סתירות נפתרות לפי מי שזז,
טביעות אצבע ב-HMAC ולא ערכים), והסוכן כבר נכנס בלי לדעת סיסמה — אבל **לאתר אחד בלבד** (`LOGIN_FLOWS`
מכיל רק את פייסבוק), **אין כרטיס**: הטופס ב«חיבורים ומפתחות» מבקש מזהה, כותרת, קטגוריה וערך — ואין בו
כתובת, שם משתמש, סיסמה ותיבת «להציע בדפדפן», בדיוק מה שביקש. העבודה היא אפוא ארבעה דברים קטנים: כרטיס
כניסה מן השורה הראשונה (כתובת/משתמש/סיסמה + תיבת סימון שמגודרת את הסנכרון), מסלול התחברות גנרי לסוכן
במקום זה של פייסבוק, שורת ביקורת לכל מילוי שתירשם ב«כל מקביל» (מ-`times_used` של כרום — הנתון כבר שם),
והוכחה כתובה להצפנה. שתי אמיתות נאמרות פה בקול: **כניסה בתוך אריח של הלשכה היא בעיה אחרת** — התוכן
נטען מאותו origin של הקונסול (`console/app.py:536`), ולכן מילוי נייטיבי לא יכול להבדיל בין אפליקציה
לאפליקציה, והפתרון הוא כניסה שהקונסול מבצע בצד השרת לפי הצהרת האפליקציה (פריט נפרד); ו**חנות הסיסמאות
של כרום בקונטיינר אינה הצפנה** — המפתח הציבורי `peanuts`, ולכן הכספת היא המוגנת והמראה היא נוחות.
מומלץ גם למדוד ולסגור את מה שנמדד היום: `grants.jsonl` בקובץ `0644`, וה-broker במצב `warn`.
