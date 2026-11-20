# Operating «מסמכים שלי» (the `my-docs` app)

The business's own documents, every type, in one house style (DGO-2029): a proposal with its cover, a quote,
a service agreement, an NDA, a work order, an order, a delivery note, a payment request («חשבון עסקה»), a tax
invoice, an invoice-receipt, a receipt, a credit note, a customer statement, a report, a letter. This app is
the screen and a thin pass-through. The documents live in apitools' ledger (Postgres), which numbers, renders
(`src/doc_gen/house/`, README there) and audits them. Anything under `/api/…` is forwarded to `http://apitools:8080/…`.

## From inside the office network (`http://my-docs:8000/api/…`, or apitools directly)

```bash
GET   /api/documents?type=&status=&customer_id=&limit=   # list / search
GET   /api/documents/<id>                                # one document
GET   /api/documents/<id>/preview                        # its page as HTML — a read: uses up no «מקור»
GET   /api/documents/<id>/download?format=pdf|png        # the file — a write for a document of the books, see Rules
GET   /api/documents/<id>/events                         # its audit trail
POST  /api/documents                                     # a DRAFT (`?issue=1` issues at once)
PATCH /api/documents/<id>                                # edit a draft
POST  /api/documents/<id>/issue | send {to} | pay | cancel {reason} | convert {to_type} | allocation {…}
GET   /api/docGen/house/types?tax_status=patur           # the catalogue: which types this business issues
GET   /api/docGen/house/template?type=PROPOSAL           # what a new document of a type starts with
POST  /api/docGen/house?format=html|pdf                  # draw a document from data — nothing numbered or kept
POST  /api/sign/<id> {signer,email?,password?}           # an issued deal document → esign's one link
GET   /api/sign/<id> · /api/sign/envelope/<eid>/download # its envelopes (by the ids its trail recorded); the signed copy
GET|POST /api/customers · /api/items · /api/business     # PATCH|DELETE /api/customers/<id>, /api/items/<id>
```

A POST that creates something takes an `Idempotency-Key` header: the same key within 15 minutes returns the
first answer. The screen is `/a/my-docs/` (`new`, `new/<TYPE>`, `doc/<id>`). Shell, reads only:
`./bbox my-docs documents|show <id>|events <id>|customers|items|integrity`. One write, a migration:
`./bbox my-docs import-history <register.csv> --pdfs <folder> [--apply]` (both in «קבצים»; DGO-2042). It keeps
another system's documents as they were issued: each PDF is the original, its copy is stamped «העתק», and the
type's series continues past them (each type's next number follows its last imported one). Without --apply it changes nothing;
a number already in the ledger is skipped.

## Rules

- **Read freely, except the download of a document of the books.** The first download of an issued invoice,
  invoice-receipt, credit note, receipt or delivery note is its «מקור», printed on the page; every later
  copy prints «העתק». Download one only on the owner's words. The preview is free.
- **Issue is final.** It takes the next number in the type's series, never reused. Cancelling a tax invoice
  issues a credit note naming it, its date and the reason; cancelling anything else only marks it cancelled.
  Issue, cancel and allocation only on the owner's words for that document.
- **An עוסק פטור issues no tax invoice, invoice-receipt or credit note** — the ledger refuses them; its bill
  is «חשבון עסקה» and its proof of payment «קבלה».
- **`send {to}` e-mails nothing**, and **`/api/sign` sends nothing**: the first records the address, the second
  makes the link. Delivering either to the customer is the owner's act, with his go-ahead.
- `pay` marks money as received: only from evidence the owner pointed at. Deleting a customer or an item is
  his to ask for.

## The deal, end to end

Proposal (or quote) → issued → «שליחה לחתימה» (esign: the PDF, a personal link, the audit trail; the signed
copy and its certificate in «קבצים») → «המשך: …» converts it into the next draft: an agreement, a payment
request (only one-time lines: a monthly retainer is billed each month), an invoice → «המשך: קבלה» on payment.

`./bbox my-docs line <data.json>` (DGO-1454, the olive bs101 look) still renders its data files; new client
documents are the ledger's PROPOSAL and SERVICE_AGREEMENT, in the house style.

## Traps

- The pass-through forwards every path and method, and apitools has no sign-in of its own. The edge's SSO
  is the only gate, so never expose apitools' port.
- The idempotency memory is per process (one worker by design). A restart forgets keys inside their 15 minutes.

Gates: G27 (the shared screen blocks), G82 (the screen names no colour; the documents' palette is apitools').
