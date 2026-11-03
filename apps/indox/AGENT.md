# Operating «מסמכים» (the `indox` app, INDOX)

The business's incoming financial documents, end to end:

- n8n's sync brings files in from Drive and Gmail;
- apitools reads them (OCR);
- a state machine files each one;
- this app's screen and API (`incoming-documents`) browse and operate the result.

Everything is per **instance** (מופע): one client's documents in their own schema `indox_<id>`,
listed in `public.indox_instances`. `test` is the permanent test instance; every other is a real
client's books.

## From inside the office network (`http://incoming-documents:8080/incomingDocuments`)

**Always pass `?instance=<id>`.** A call without it is NOT refused. It acts on schema `public`, whose
views are the first production instance (hacohen).

```bash
GET  /instances · /repos · /repos/<repo>/stats              # what exists, and its numbers
POST /repos/<repo>/documents/query      {filters…}          # search documents (read)
POST /repos/<repo>/documents/month-index · /export          # month view, an export (read)
GET  /repos/<repo>/documents/<id> · …/<id>/history          # one document and its state history
GET  /sync/registry · /sync/registry/<name>/items           # the syncs and what they hold
GET  /pipeline/status · /dashboard/stats · /dashboard/actions   # the drain, the work, the actions
GET  /config/settings · /tests/suites · /openapi.json       # the settings, the suites, the full contract
```

The screen is `/a/incoming/` (`/i/<instance>/dashboard|documents|sync|actions|settings|tests|extraction`).

## From the server's shell

```bash
./bbox indox sync state --instance=<id>          # the syncs, read (note the =)
./bbox indox doc-trace <id> …                    # one document's whole path (read)
./bbox indox ui-qa                               # the screens, read-only
./bbox indox test [suite] [--junit]              # the suites, always against instance `test`
./bbox indox apply-schema <id>|--all --dry-run   # schema, dry run first
```

**`sync state` and `sync reset` do not require an instance:** with none named they pick the sole
production instance. Name it every time.

## Rules

- **Only the state machine changes a document.** Never write a document row yourself.
  - `…/documents/bulk` changes STATUS only.
  - Re-running a document goes through its restart action, not by editing it.
- **The drain stays on and B stays 500** (the owner's standing rule).
  - Never turn off `indoxDrainOn` (the drainer) or `indoxOn` (THE master switch: no sync, no
    drain). `indoxSyncOn` gates the sync.
  - Never change `indox.statemachine.driver.batch` (B). A missing row reads 2000, not 500.
  - `PUT /config/settings/<key>` on these keys is the owner's.
- **Never call `POST /config/stop-all`.** It switches the drain, the sync and INDOX off, stops EVERY
  n8n execution in the office (not only INDOX's), and flushes the shared queue.
- `indoxSourceFeedbackOn` (moves Drive files, labels mail) and `activePrioritySync` (posts to the
  client's ERP) reach outside the office. Both are off by default; only the owner turns them on.
- **Destructive, the owner's words only, for an instance he named:**
  - `POST /dashboard/actions/purge` and `DELETE /repos/<repo>`;
  - `DELETE /sync/registry/<name>`, which deletes the pipe and purges its rows;
  - `DELETE /config/companies/<id>` and `POST /account/remove`;
  - `bbox indox reset --instance <id>`, which clears the instance. The hook supplies its own
    `RESET-INSTANCE:<id>` confirmation, so nothing else stops it.
  - `sync reset` (with no `--sync-name` it re-drives every pipe) and `sync-reset --purge`;
  - `demo run … [--reset]`: `--reset` truncates that instance's documents and clears the office's
    document locks in Redis. Demos go to `--instance test` only.
  - `trigger-wf <workflowId>`, which runs any workflow, the reset one included;
  - `fixture-sweep`.
- `sync_ledger` has one writer, the n8n workflow `syncLedgerApi01`: never write it by hand.

## Traps

- The flag is spelled two ways: `--instance=<id>` for `sync-state`/`sync-reset`, `--instance <id>`
  for `reset` and `demo`.
- The settings table's `instance` column is something else, not the instance a call is about.
- The declared `upload` op has no route here. `POST /extraction/upload` feeds the extraction tool
  only.
- The BFF has no sign-in of its own; the edge's SSO is the only gate.

Gates: G29 (the drawn engine equals the built one) and G37, G41, G42, G44, G45, G48, G49, G56, G64,
which read its workflows and writers; G27; its own tests.
