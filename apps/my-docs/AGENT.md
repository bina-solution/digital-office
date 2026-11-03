# Operating «מסמכים שלי» (the `my-docs` app)

The business's own documents: quotes, invoices, receipts, credit notes, numbered the way the tax
authority expects, with their customers and items. This app is the screen and a thin pass-through.
The documents themselves live in apitools' ledger (Postgres), which numbers, renders and audits
them. Anything under `/api/…` here is forwarded as-is to `http://apitools:8080/…`.

## From inside the office network (`http://my-docs:8000/api/…`, or apitools directly)

```bash
GET   /api/documents?type=&status=&customer_id=&limit=   # list / search
GET   /api/documents/<id>                                # one document
GET   /api/documents/<id>/download?format=pdf|png        # the rendered file — a write, see Rules
GET   /api/documents/<id>/events                         # its audit trail
GET   /api/documents/verify                              # numbering continuity + tamper chain
POST  /api/documents                                     # a DRAFT (`?issue=1` issues at once)
PATCH /api/documents/<id>                                # edit a draft
POST  /api/documents/<id>/issue | send {to} | pay | cancel {reason} | allocation {allocation_number,status}
GET|POST /api/customers · /api/items · /api/business     # PATCH|DELETE /api/customers/<id>, /api/items/<id>
GET   /api/me                                            # who the edge signed in
```

A POST that creates something takes an `Idempotency-Key` header. The same key within 15 minutes
returns the first answer and does not create twice: use one per intent, and retry with the same one.
The screen is `/a/my-docs/` (`#/m/my-docs/<view>` or `doc/<id>`). From the shell, reads only:
`./bbox my-docs documents|show <id>|events <id>|customers|items|integrity`.

## Rules

- **Read freely, except the download.** The first download of an issued document uses up its
  «מקור» (original): every later copy, the owner's own included, is «העתק». Download an issued
  document only on the owner's words. A draft is yours to prepare when asked.
- **Issue is final.** It takes the next number in the series, and a number is never reused. To undo
  an issued document you **cancel** it, which creates a credit document beside it. Issue, cancel and
  allocation only on the owner's words for that document.
- **`send {to}` e-mails nothing.** It only marks the document sent and records the address in its
  audit trail. Never tell the owner a customer was e-mailed because of it: delivering the file is a
  separate act (a mail, with his go-ahead).
- `pay` marks money as received: only from evidence the owner pointed at.
- Deleting a customer or an item is his to ask for.

## Traps

- The pass-through forwards every path and method, and apitools has no sign-in of its own. The
  edge's SSO is the only gate, so never expose apitools' port.
- The idempotency memory is per process (one worker by design). A restart forgets keys still inside
  their 15 minutes.

Gates: G27 (the shared screen blocks).
