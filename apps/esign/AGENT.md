# Operating «חתימות» (the `esign` app, DGO-1631)

The office's signing: a document goes out as **one link**, the signer signs it in a minute, and the
signed copy lands in «קבצים». The design, the three engines weighed and the Israeli law:
`ai/context/research/dgo-1631-esign.md`. This file is how to drive it.

Vocabulary: an **envelope** is one document + one signer + one link (its own record and audit trail).
The **token** is the random part of the link (`/s/<token>`). The **signer's page** is the one public
path. The **audit trail** is a hash-chained list of what happened, and the paper that carries it is the
last page of the signed PDF: the signing certificate, drawn in the office's house style by the documents
renderer (`ESIGN_RENDER_URL`, apitools' `POST /docGen/house`, DGO-2029), or as a plain page when it does not
answer. A deal document reaches here from «מסמכים שלי» («שליחה לחתימה», its BFF `/api/sign/<doc>`).

## From the server's shell

```bash
./bbox esign new "/path/to/הסכם.pdf" --to "ישראל ישראלי" --password "סודה"   # prints the link
./bbox esign list                       # what went out, and where it stands
./bbox esign show <id>                  # state, the audit trail, and whether the chain still verifies
./bbox esign link <id>                  # mint the link again — this ROTATES it (the old one dies)
./bbox esign cancel <id>                # close the link; the envelope stays, signed or not
./bbox esign flow                       # the last 10 events of dgo:flow:esign, then live
```

## From inside the office network (`http://esign:8080`)

```bash
POST /api/envelopes                      # multipart: file (PDF), signer, password?, days?, page?, box?
POST /api/envelopes/<id>/send            # draft → sent (a draft link answers a stranger nothing)
POST /api/envelopes/<id>/link            # mint again (rotates the token)
GET  /api/envelopes | /api/envelopes/<id>    # list / one, with its events and the chain's verdict
POST /api/envelopes/<id>/cancel | /retry     # close / retry the drive copy and the notice
GET  /api/envelopes/<id>/download        # the signed PDF
```

Canonical answers are `{"ok":true,"op":…,"data":…}`; a refusal is 4xx with a Hebrew `detail`.

## The signer's side (the public half)

`/s/<token>` — page · `/s/<token>/doc` — that envelope's PDF · `/s/<token>/unlock` (POST) ·
`/s/<token>/sign` (POST) · `/s/<token>/done`. With a password set, the bytes are **not served** until it
is given; five wrong attempts lock the link for 15 minutes and every attempt is an audit event.

## «מילוי וחתימה» — one link for every party (DGO-2139, `fill.py`)

An **event** is one PDF, its sides and places (detected from the words under its lines), one token.
`POST /api/events` (file, hints) → draft · `POST /api/events/<id>/send` (the map) → the link ·
`/link` `/cancel` `/complete` (re-seal) · `GET /api/events?ref=`. Public: `/s/<token>` (the page),
`/s/<token>/f/claim|answers|sign|state|seen` and `page/<n>` `sig/<side>` `final`. A side is claimed
by one browser; the last signature seals ONE copy for all. A personal code is 6–8 digits: five wrong codes
lock that browser (each lock doubles); 100 per link close the side until `/link` mints a new link.
`/complete` re-makes a copy that failed, or re-delivers one «קבצים» refused — taken in the request, so a
second press is refused (409).

## Rules

- **The link is a bearer token, not a session.** It opens one envelope, is refused on every other path,
  and dies at `expires_at` or on `cancel`. Never paste one into a chat other than the signer's own.
- **The password travels apart from the link** — that is the whole point of it. Say it, do not write it
  next to the URL.
- **The signature is the product; the copy and the notice are not.** A drive or notifications outage
  leaves `drive_state`/`notice_state` as `pending:…` and the child returns a signed PDF anyway —
  `POST /api/envelopes/<id>/retry` finishes the delivery, never a second signing.
- **Never rewrite a signed envelope.** Signing twice is two envelopes; drive keeps an existing file and
  names the new one «name (2)».
- The office's signing certificate is generated once in the store, data/esign/state (self-signed, in the office's name:
  `ESIGN_OFFICE_NAME` ← BUSINESS_NAME) or connected as a PKCS#12 (`ESIGN_CERT_P12`/`ESIGN_CERT_PASS`); the
  certificate page names that key's subject. A self-signed signature proves the bytes did not change;
  it does not prove WHO signed — that is the audit trail's job, and for a document that needs it, a
  registered CA's (research §3.3).
- A trusted time (PAdES B-T) only when the office names an RFC 3161 authority (`ESIGN_TSA_URL`; empty
  calls nothing outside); only the signature's hash travels. An authority that does not answer never
  costs the signer the act: the file is signed without the time and the event says `timestamped: false`.

## Traps

- **The public router is the app's own** (`emit_labels: false` in app.json) because the compiler does not
  implement `auth_exclude` on a host it routes. `/s/` is listed there so gate G21 can see the exception;
  a second public prefix would need the same line, and is a decision, not a convenience.
- A draft envelope's link answers 404 until `/send` (or the CLI's flow, which sends on creation).
- `./bbox esign new` copies the PDF into the container to post it; the copy is removed afterwards.
- The signed PDF lives in the store at `<data>/signed/<id>.pdf`; the office's copy is in «קבצים» under
  `/מסמכים/חתימות/<YYYY-MM-DD>/`, which «ארכיון» lists (DGO-2125).
- **Sending to a person outside the office is the owner's act** — this app produces the link, not the
  message.
