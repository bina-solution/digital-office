# «מסמכים» (`documents`) — one list over the business's documents

What it is FOR: the owner asked for ONE documents app instead of «מסמכים נכנסים» and «המסמכים שלי» (DGO-1630). This
service is that app's store of record INDEX: every document the business issued (apitools' ledger, provider `local`)
and every document that came in by mail or Drive (INDOX, provider `indox`), in one list with one search. Words: a
document is issued (`out`, «יוצא») or incoming (`in`, «נכנס»); a provider is where the document really lives.

## The door

```bash
./bbox documents list [out|in] [N]     # the newest documents, both directions
./bbox documents search חשמל            # one search over both
./bbox documents show indox:main:1234   # one document: the index row + the provider's own record
./bbox documents providers              # which providers this office reads, and each one's last sync
./bbox documents sync                   # read the providers now
```

On the office network: `GET http://documents:8080/api/documents?direction=in&q=…` →
`{"ok":true,"op":"list","data":{"rows":[…],"status":[…]}}`.

A third provider, `drive` (DGO-2029), lists the office's files in «קבצים» — `/מסמכים`, `/לקוחות/<client>/`,
`/מחקרים` (`DOCUMENTS_DRIVE_ROOTS`) — as rows of direction `file`: the name, the folder, the client, the date.
It reads the folder tree once, then each folder a thousand files a page, and writes nothing; a root the office
lacks is skipped. `DOCUMENTS_DRIVE_PROFILE` pins the drive's account; empty, the drive's active connection
answers — whichever account its connection bar was last set to.

The search reads Hebrew (DGO-2029). Every word must be there, at the start of a word, past up to two prefix
letters (ו/ה/ב/כ/ל/מ/ש). Final letters match plain ones, and niqqud and ׳ ״ are ignored. «לחברת החשמל», «חשבון»
and «מעמ» find «חברת החשמל», «חשבונות» and «מע״מ»; «מחיר» does not find «בחירה». A row's searchable words
are written once, when it is synced (`folded`).

## Traps

- It READS. Issuing, cancelling and sending stay the ledger's (`./bbox my-docs …`, the owner's words only), and
  filing, extraction and its automations stay INDOX's (`./bbox indox …`). This app never writes into another app; a
  write attempt is blocked in code (`ReadOnlyViolation`).
- The list is an index. A provider that does not answer keeps its last rows and says «לא סונכרן מאז …» by name. Read
  `providers` before you say a document is missing: an empty half can mean "INDOX is down", not "no documents".
- A provider — or one INDOX instance, a whole client — that suddenly lists half its documents or fewer is REFUSED and
  its rows are kept (a short answer is far likelier than half the book gone). If the shrink is real,
  `./bbox documents sync <provider> --accept-shrink` (that sync tells nothing on the flow: ids that flipped are not news).
- INDOX's `/instances` answers 200 with an empty list and a `reason` when its registry fails; that is read as "INDOX did
  not answer", never as "no instances". The `test` instance is INDOX's own and is not in the business's list.
- The flow tells each document once per kind, never on a provider's first sync: `document.issued` when a ledger
  document leaves draft; `document.intake.filed` when INDOX marks it COMPLETED; `document.intake.needs_review` when it
  needs a hand (REQUIRED_ACTION, MISSING_*, *_FAILED, MAX_ITERATIONS, NEEDS_REVIEW). Rows in flight (TO_EXTRACT,
  IN_PROGRESS) and OLD/GARBAGE/DOUBLE/MERGED are not news. At most 20 per sync, the newest; a bigger burst is counted
  in `documents.sync.changed`. A failure is told when it starts (`documents.sync.failed`) and its end once
  (`documents.sync.recovered`) — not every round.
- An `id` names its provider: `local:<id>` is the ledger's document, `indox:<instance>:<ID>` is INDOX's row in that
  instance (מופע). For operator work on an incoming document (extraction, sync state) use INDOX's own screen.
- No tile yet: the screen waits for the owner's pick of the mock on DGO-1630.
