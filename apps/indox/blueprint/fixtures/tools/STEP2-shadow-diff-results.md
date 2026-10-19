# Step 2 — kwExtract shadow-diff results (INVOICE)

The shadow-diff harness (`shadow_diff.py`) proves whether `fixture_INVOICE.kw_extract` reproduces
the LIVE KW columns by calling real apitools with the fixture's queries + normalizing via the shared
registry, then diffing vs `incoming_documents`. **No live pipeline is touched.** Empty diff → the
generic `kwExtract01` engine can cut over for that field.

Run: `python production/n8n/fixtures/tools/shadow_diff.py INVOICE gdx_inv1,gdx_inv2,gdx_inv3,gdx_inv4,gdx_inv5`

## Current parity: **20/25** (5 invoice docs × 5 fields)

Converged 17 → 18 → 20 by correcting normalizers (the fixture had used *selection-time* normalizers,
but KW columns are written by *query-time* normalizers):

| fix | field | change |
|---|---|---|
| ✅ applied | PURCHASE_ID | `trim` → `id_clean` (strip garbage) — `*$1256000443*`→`1256000443` matches live |
| ✅ applied | SHIPMENT_DOC_ID | `id_clean` → `trim` — live shipment col is **raw** (`742.50`, `[ms125032502`) |
| ✅ applied | (registry) | added `id_clean` normalizer to `lib/normalizers.js` |

## Remaining 5 diffs — classified

**A. Amount comma-format (2: inv2, inv3)** — normalizer choice.
`3403.00` (engine `amount_2dp`) vs `3,403.00` (live). The live query normalizer ("Normalize Format"
in `indoxV2QueryTotalAmt01`) keeps thousands-commas; the shared `amount_2dp` (from Selection) strips them.
→ **Decision needed:** add an `amount_commas` normalizer to match live exactly, OR ratify the clean
no-comma form as an intentional improvement and update the live column at cutover. (Clean is better for
a numeric column; commas are display formatting leaking into data.)

**B. Amount empty-vs-found (2: inv1, inv5)** — QUERY DRIFT (§J risk #2).
Live `""` (query found nothing that passed validation) vs engine `310126.00`/`26000835.00` (a wrong
region). The fixture's inlined amount query differs from the live authoritative node.
→ **Fix:** re-extract the amount `query_after`/`query_below` (incl. exact `value_validations` + anchor
order) FROM the live `indoxV2QueryTotalAmt01` SET nodes, not from the `q_*` settings.

**C. Shipment inv3 (1)** — QUERY DRIFT.
Engine `02-6507801,` vs live `1256001661` (different values). The fixture's shipment query lacks the
live node's `match_index` + per-doc `not_ends_with` (COMPANY_DOC_ID last-5) validation.
→ **Fix:** re-extract shipment query from live `indoxV2QueryShipmentId01` with its dynamic validation.

## Takeaway

The harness **works and does its job**: it proved the fixture-driven extraction path (apitools →
`result.result` → normalize) reproduces live for doc-id + date + purchase, and precisely isolated the
2 remaining classes — a **normalizer-format decision** (amount) and **3 query-drift cases** that
confirm §J correction #7: fixtures must be extracted FROM the live query nodes, not the orphaned `q_*`
rows. Next iteration: fix B/C by re-extracting those 3 queries from the live nodes and re-run to empty
diff, then build the `kwExtract01` n8n workflow (the validated logic: seeded fixture → bounded-2
apitools loop → shared normalizer → `*_SHADOW` write).
