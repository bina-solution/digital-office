# INDOX — product state and next steps

Written as the INDOX product owner, 2026-07-29. Every claim below was checked against the code, not
against a previous summary.

## The shape of the product

INDOX is **one app per company instance**. An *instance* is a fully duplicated INDOX — its own target
table, its own settings, its own companies and tag rules, its own sync registry. Exactly one is active
at a time, and every no-parameter endpoint (`/config/settings`, `/sync/registry`, `/sync/status`)
resolves against it. That is what makes switching feel like changing companies rather than picking a
folder.

Three surfaces, and only three:

| Tab | Owns |
|---|---|
| **לוח בקרה** | the dashboard — counts, recent documents |
| **מסמכים** | the table. One click, no screens in front of it |
| **סנכרון** | everything about getting documents in: sources, their live state, and the items |

Instance selection is a **top-bar switcher**, exactly like Drive and Mail. It is not a screen.

## What is done

**מסמכים reaches the table in one click.** `RepoListPage`, `RepoDetailPage`, `RepoCreatePage` and
`KafkaTailPage` are deleted. They were pure navigation — "pick a מאגר" then "open the table" — and
the switcher replaced the only thing they carried. `/repos` and `/repos/:repo` redirect rather than
404 so old links still land on the table.

**Sync is one screen.** Settings no longer holds a registry grid; it links to `/sync`. The sync screen
carries config *and* live state together, which is the whole point: they were two read-only tabs a
reader had to join in their head.

**The sync screen does all of it** — verified call-by-call against the source:

| Capability | Where |
|---|---|
| list connections (the picker comes FIRST) | `SyncStatePage` → `api.listConnections` |
| browse that connection's real labels/folders | `api.listLocations` |
| **create** a new label/folder inline | `api.createLocation` |
| add / modify / delete a source | `createSyncEntry` / `patchSyncEntry` / `deleteSyncEntry` |
| pause a source | `patchSyncEntry {enabled:false}` |
| run one / run all | `runSyncEntry` / `runAllSyncs` |
| live counts, failures grouped by cause | `getSyncRegistry` (config + state in one read) |
| move items between states | `SyncBoard` → `moveSyncItems`, gated by `LEGAL_MOVES` |
| re-queue by the pipe's own type | `SyncBoard` → `applyFallbackType` |

The order matters and is enforced by the UI: **connection first, then its pairs.** You cannot pick a
label before saying which mailbox it belongs to, because the label list is fetched from that account.

**The backend exists.** All eleven endpoints the UI calls are implemented, `LEGAL_MOVES` is enforced
server-side (a rule only the client knows is not a rule), and every read degrades to
`{reachable:false}` rather than 500 when supabase is down.

**Instances are creatable.** The switcher carries a three-step wizard: identity → target table →
confirm. The default table name is deliberately ASCII-slugged, because a Hebrew label must not become
a Hebrew SQL identifier.

## What is NOT done — the honest list

1. **The creation wizard does not yet let you pick sync registries during creation.** It creates the
   instance with an empty registry and tells you to add sources in `/sync`. The full pipe editor —
   connection picker, live label/folder browse, create-new — already exists there, so this is a
   sequencing gap rather than a missing capability. Closing it properly means either embedding that
   editor as step 3 or, better, sending the user into `/sync` with the new instance already active.
2. **Selecting an instance scopes the TABLE, not yet the settings.** `/config/settings`,
   `/sync/registry` and `/sync/status` still read single global supabase tables with no instance
   column. Multi-company is therefore real for documents and not yet real for configuration. This is
   a database tenancy change, not routing, and it is the single biggest remaining piece.
3. **`stuck` / `claimed_at` are always null.** Nothing records *when* an item was claimed, so the
   board cannot honestly show abandoned work. Deriving it from file mtime would mark healthy work as
   stuck. The fix is one `claimed_at` column written at CLAIM time.
4. **Failure codes are mapped from the recorded `STATUS` vocabulary**, not the enumerated processor
   codes the design calls for. An item with no row reports "cause not recorded" rather than a guess.

## Where live still differs from the simulation, and why

`api.ts`, `main.tsx`, `SettingsPage.tsx`, `SyncStatePage.tsx` and `SyncBoard.tsx` are byte-identical
to the sim. The remaining differences are all deliberate:

| File | Difference | Why it stays |
|---|---|---|
| `index.css` | live's `--font` includes `"Assistant"` | **Required by gate G21.** `CANONICAL_FONT` in `theme-token-lint.py` includes it and the lint covers this exact file. Porting the sim's font turns CI red. The sim is behind here, not live. |
| `InstanceSwitcher.tsx` | live-only | In the sim the chip is drawn by `overlay/switcher.js`, which its own header marks *"Sim-only; edits no real source."* The live console has no switcher for any app, so a shell-only chip would leave the instances surface in the API and nowhere in the UI. |
| `SyncStatePage.tsx` | degraded-save check | The sim's mock never degrades, so it cannot have this. Live's store can be down, and a save that silently did nothing used to close the drawer as if it had worked. |
| `App.tsx` | switcher mount, `activeResolved` | `activeResolved` disambiguates "not fetched yet" from "no instances" — a redirect must not fire on the first. |
| `DashboardPage.tsx` | links `/documents` not `/repos` | Same destination; `/documents` is the instance-agnostic route and does not depend on `/repos` still existing. |
| `BinaTable.tsx` | comment wording | Comment only; no rendered difference. |

**Panels 30/31/32 of the pixel diff will never match**, and that is correct: they render
`overlay/switcher.js`, sim-only scaffolding the platform deliberately replaced. `sim-live-parity.py`
already excludes its `dosw-*` tokens for the same reason.

## Next steps, in the order I would do them

1. **Instance-scope the configuration** (item 2 above). Until this lands, "multiple companies" is
   true for documents and false for settings — the most misleading state the product can be in.
2. **Finish the creation flow** so a new instance lands in `/sync` with its first source being added,
   instead of an empty registry and an instruction.
3. **Record `claimed_at`** so the board can tell stuck work from healthy work.
4. **Enumerate processor failure codes** so failures group by cause rather than by recorded status.
