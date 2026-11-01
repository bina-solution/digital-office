# INDOX — what was built, what is proved, and what is still open

> **Production erratum (2026-08-03):** the completion table below is historical and is not a current
> production-readiness claim. A Console-authored remote Google Drive pipe exposed unresolved gaps in
> remote source observability, projection, thin-mode processing, per-file provenance, and repair.
> See [`indox-gap-audit-2026-08-03.md`](indox-gap-audit-2026-08-03.md) for live evidence and the
> dependency-ordered remaining work.

Companion to [`indox-final-plan.md`](indox-final-plan.md). That document said what should be true;
this one says what *is* true, with the evidence, and is deliberately explicit about the difference.

The plan's own summary of the gap was: **"the run button does not run, nothing is ever in progress,
and a second instance would be written to by nothing."** All three are now false.

---

## 1 · The phases

| # | What it had to do | State | The evidence |
|---|---|---|---|
| 0 | Stop reporting work that did not happen | done | `{success:false}` + Hebrew outcome on screen; capability flag hides surfaces that can only read zero |
| 1 | Implement the SCAN verb | done | the manage webhook runs the registry; `bbox indox test` lanes exercise it |
| 2 | The registry is the whole contract | done | one vocabulary, normalised on write; a save no longer deletes unshown pairs |
| 3 | A real claim, then the fourth state | done | claim planted → `in_progress` holds it → aged past `timeout_min` → `stuck=true` → שחרר returns it; a delivered row refuses release |
| 4 | Reconcile ledger against location | done | `GET /sync/reconcile`; found real divergence on this stack on its first run |
| 5 | Finish the authoring flows | done | `failed_folder` reachable, review step, instance chip |
| 6 | Tenancy | done | additive DDL proved byte-identical; guard at both chokepoints; lint |
| 6b | *Prove* parallel instances | done | `apps/indox/scripts/prove-two-instances.sh` — 16/16 |
| 7 | Connection identity | done | `connection` carried end to end; `GET /sync/origin` resolves instead of recalling |
| 8 | Dashboard drill-down + one document view | done | observations link to a filtered table; `DocumentViewer` shared by both pages |

---

## 2 · The three claims the plan cared most about

### "The run button does not run"

`SCAN` existed as a name and not as an implementation. The manage webhook answered HTTP 200 with
`{ok:false, "…not yet implemented"}`, the BFF called every non-transport reply a success, and the UI
threw the answer away. So the button went green, `last_run` was stamped, and nothing had run.

Fixed at all three layers, because any one of them alone would have left it silent: the verb is
implemented, the server reports the outcome rather than the request, and the page states the failure
in Hebrew with the engine's own words kept underneath.

### "Nothing is ever in progress"

Under the v3 engine an item went `to_sync -> synced|failed` in one hop. `claimed_at` was always
null, `stuck` always false, and the board's `in_progress` column could never hold a card.

The claim is now the `INSERT` itself: two passes racing for one item both insert the same
`(source, platform_id)`, the primary key admits one, and `returning platform_id` answers *what did I
get*. No lock, no window between checking and taking. It is retired on **both** exits — `RECORD`
promotes it, `RELEASE` deletes it — which is what finally gives `stuck` an honest meaning: a claim
still standing past `timeout_min` outlived both of its exits, so the workflow died mid-delivery.

### "A second instance would be written to by nothing"

`settings`, `companies` and `tag_rules` carry an `instance` column; documents stay
table-per-instance. The sharpest constraint was the ledger key: `sync_ledger` is keyed
`(source, platform_id)` where `source` is the pipe name, and duplicating an INDOX gives the second
instance a pipe called `drive-gdoc` too. Un-namespaced, both instances share ledger rows and each
reads the other's deliveries as already-done — one client's documents silently never arrive, with
both boards green.

`source` is now `<instance>/<pipe>`. `prove-two-instances.sh` stands up a second instance with a
deliberately colliding pipe name and checks the collision directly:

```
── 3. THE LEDGER KEY
   PASS  same id + same pipe name in both instances           2
   PASS    ...and A's row is A's                              1
   PASS    ...and B's row is B's                              1
── 4. one scanner pass must FAN OUT to both instances
   after the pass: A ledger rows=5   B ledger rows=1
════════ 16 passed, 0 failed ════════
```

---

## 3 · Bugs found by testing rather than by reading

Listed because each one was invisible in a diff, and several were introduced by this work and caught
by it.

| Bug | Why it was silent |
|---|---|
| Quarantine's `ON CONFLICT DO NOTHING` stranded a claimed row as `claimed` forever | never surfaced as `needs_review`, never returned to the todo — a document quietly ceasing to exist |
| `Release Req` read the wrong entry node | the BFF uses the webhook path, so the node never ran, `sync` came back empty, and every release refused itself while the row sat claimed |
| `Call CLAIM`/`Call RELEASE` lacked `alwaysOutputData` | n8n skips a node with empty input, so a pass with nothing to claim stopped the chain dead and the unit read as *died* |
| `Synced/Failed Label Ops` fell back to `\|\|k` | Gmail creates a label named after the key, the op reports success, and the item never reaches the state the diff looks for |
| A claim whose source item was deleted was invisible | the diff kept subtracting it, the board never drew it, so it could not be released |
| `Ensure Sender Company`'s existence guard was global | the first instance's rows satisfy it forever — every later instance silently never receives its fixture |
| `Cleanup Prior` deleted companies across all instances | a test teardown reaching into another tenant |
| 26 workflow nodes read tenant tables with no `instance` | found by the lint, in two waves; two of them were written by this work in phase 1 |

**A correction worth recording:** `proc-gmail-doc` was twice described as a pre-existing
OCR/company-figuring failure. It was not — it was the Hebrew label keyword overflow, fixed in
`e39bfbf6`. That lane applies labels, and the next `sync_sources` run after the fix was 10/10.

---

## 4 · Tests

```
sync_kernel      6/6     diff · record · deliver · attempts · order · cursor
mail_organizer   2/2
sync_sources    10/10    drive-gdoc, drive-bs, gmail-{doc,bs,link},
                         proc-{gdoc,bs,gmail-bs,gmail-doc,gmail-link}
sync_full        6/6     mixed · history · races · chaos · handoff · registry
doc_base         3/3
bs               4/4
gdoc             5/5
pipeline         3/3
prove-two-instances.sh  16/16
tenancy-lint            OK across apps/ and platform-base/
```

`sync_sources` was **9/10 before any of this work** and is 10/10 now. `races` and `chaos` passing is
the load-bearing evidence that the claim did not break concurrency — they are the lanes that would
show a double delivery.

### What the rename cost, recorded honestly

Namespacing `source` to `<instance>/<pipe>` is a primary-key rename, and it broke six things that
were still speaking the old name — none of them loudly:

| | how it failed |
|---|---|
| `Build Units` | a leftover `reg` reference in the branch that only runs when there are no units |
| `Ensure Schema` | the migration is re-applied every fixture setup, so it kept renaming rows onto twins that already existed |
| lane teardowns | matched nothing, so each run started from the previous run's leftovers — `gate.delivered` read 15 instead of 3 |
| suite assertions | keyed on the bare pipe name, so every lookup came back `undefined` |
| `SYNC_NAME` | was written namespaced onto documents, where the instance is already implied by the table |
| the teardown join | `" where l."+predicate` put the qualifier on a function: `schema "l" does not exist` |

None of these were visible in a diff. All were found by running the suites, which is the argument
for the suites.

---

## 5 · What is deliberately NOT done, and why

Being specific here matters more than the table above.

- **Phase 6.1 — `public.run_sql` provisioning.** Not added. `POST /account/add` still cannot create
  an instance end to end from the UI; `prove-two-instances.sh` provisions its own table directly.
  The tenancy *mechanism* is proved; the *self-service creation flow* is not.
- **Phase 6.6 — routing the documents write path through the BFF.** 53 nodes still write documents
  directly. Correct today (one table per instance, and the table name carries the tenancy), but the
  diff engine remains duplicated in `Build Match Index SQL`.
- **Phase 6.7 — per-user active instance.** `active_instance.json` is still one file per deployment,
  so two SSO operators share one selection and one switching companies re-points the other's screen.
- **Phase 8 quick actions.** Drill-down and the shared document view are done. The multi-select bulk
  actions (add as test document, add company, apply fallback type, retry) are **not** built.
- **Instance pinning in the v1/label tail.** ~14 nodes take `INSTANCE='incoming-documents-main'` as a
  literal, because they have no work item to derive a tenant from. Correct for one instance and
  flagged in place; the label engine moving to the mail app is what unblocks it.
- **Renaming a pipe is still catastrophic.** `name` is a ledger PK component. The review step added
  in phase 5 warns at creation time, but the UI still offers rename freely.

---

## 6 · Where the code is

| Concern | File |
|---|---|
| BFF — claims, reconcile, origin resolver, tenancy resolver | `apps/indox/app/incoming_documents/api/__init__.py` (+784) |
| Tenancy guard (the chokepoint that throws) | `apps/indox/app/incoming_documents/backends/supabase_transport.py` (+53) |
| Ledger kernel — CLAIM / RELEASE / STUCK / PIPE_RUN | `apps/indox/blueprint/n8n/syncLedgerApi01.json` (+315) |
| Claim wiring, release-on-failure | `apps/indox/blueprint/n8n/syncV3Unit0001.json` (+139) |
| Instance fan-out, ledger namespacing, connection | `apps/indox/blueprint/n8n/syncV3Main0001.json` |
| Config-table chokepoints | `apps/indox/blueprint/n8n/indoxApiSupabase01.json` |
| Sync board — stuck, reconcile, instance chip, review step | `apps/indox/app/webapp/src/pages/SyncStatePage.tsx` (+386) |
| The one document view | `apps/indox/app/webapp/src/components/DocumentViewer.tsx` |
| Schema — tenancy, CONNECTION, ledger namespacing | `apps/indox/blueprint/fixtures/schema.sql` |
| Tenancy lint | `scripts/refactor/tenancy-lint.py` |
| Two-instance proof | `apps/indox/scripts/prove-two-instances.sh` |
