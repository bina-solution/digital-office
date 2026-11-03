# DGO-55 / DGO-56 — the comparative beauty score: what was measured, and what it says

The protocol is [dgo55-56-proof-protocol.md](dgo55-56-proof-protocol.md); this file is its result.
Every number below came from a real capture; where a half could not be measured, it says so and names
the defect instead of inventing a score. mailview's numbers are from 2026-10-09 (the staging office),
bina-ds's from 2026-10-11 (this office) — the same instrument, `bbox ui-map` → `capture.py` →
`score.py`, on two offices, and §1 says why.

## What was run, and where

| half | where | command | views | result |
|---|---|---|---|---|
| **mailview** | the **staging office on srv000001** (`93.184.216.5`, the office that runs the mail stack: `mailview-staging`, `mailapi-staging`, `mailserver-staging`, `mailboxd-staging`) | `UI55_APPS=mailview bash scripts/ui-coverage/dgo55-score.sh` | **9/9 desktop, 9/9 mobile — all `CAPTURED ok`** | ✅ measured |
| **bina-ds** | this office (hp-dgo), live | `UI55_APPS="bina mailview" bash scripts/ui-coverage/dgo55-score.sh` (2026-10-11) | **1/1 desktop, 1/1 mobile — `CAPTURED ok`** (on 2026-10-09 the same run was 0/1, `embedded app near-empty (20 nodes)`) | ✅ measured — 95.5 / 95.5, with §3's bundle defect still inside the number |
| **mailview** | this office | the same command | 0 views: the app is `disabled` here (`platform.state.yaml`) — no mail container exists to photograph | ⛔ not installed in this office |

Why mail was measured on the VPS and not here: this office has `mail: {state: disabled, by: cli}` in
`platform.state.yaml`, no mail container exists, and its mail images are five weeks old — the mail
window is live on the staging office, so that is where it was photographed. The instrument is
identical (same `bbox ui-map` → `capture.py` → `score.py`), on that office's own checkout.

`score.py`'s seven weighted dimensions: layout 25 · clipping 15 · touch 10 · type 15 · contrast 15 ·
consistency 10 · states 10 = 100.

## mailview — desktop 1440×900

9 views, **platform score 82.2** (per-view mean 83.8, worst 80.6).

| view | score | layout /25 | clipping /15 | touch /10 | type /15 | contrast /15 | consistency /10 | states /10 | weakest |
|---|---|---|---|---|---|---|---|---|---|
| state-reader-doc | 80.6 | 25.0 | 7.1 | 3.7 | 10.0 | 14.8 | 10.0 | 10.0 | touch |
| state-reader | 81.2 | 25.0 | 7.0 | 4.4 | 10.0 | 14.8 | 10.0 | 10.0 | touch |
| inbox | 81.5 | 25.0 | 7.0 | 3.8 | 10.9 | 14.8 | 10.0 | 10.0 | touch |
| state-toast | 81.5 | 25.0 | 7.0 | 3.8 | 10.9 | 14.8 | 10.0 | 10.0 | touch |
| state-tagpicker | 82.2 | 25.0 | 7.4 | 5.1 | 9.9 | 14.8 | 10.0 | 10.0 | clipping |
| label | 82.4 | 25.0 | 3.5 | 6.8 | 12.1 | 15.0 | 10.0 | 10.0 | clipping |
| message | 85.9 | 25.0 | 10.3 | 8.5 | 10.9 | 14.2 | 7.0 | 10.0 | clipping |
| state-search | 88.0 | 25.0 | 6.0 | 7.6 | 14.4 | 15.0 | 10.0 | 10.0 | clipping |
| state-attention | 91.3 | 25.0 | 9.6 | 8.5 | 14.2 | 14.0 | 10.0 | 10.0 | clipping |

**dimension means (desktop):** layout **25.0/25**, clipping **7.2/15 (48 %)**, touch **5.8/10 (58 %)**,
type 11.5/15, contrast 14.7/15, consistency 9.7/10, states 10.0/10.

Raw counters, desktop: `overflow=0` on every view (nothing is painted past the frame), `cut` 2–10
elements per view, `tiny` 0–18 (text under 11px).

## mailview — phone 390×844

9 views, **platform score 74.3** (per-view mean 75.9, worst 72.8).

| view | score | cut elements | tiny texts | weakest |
|---|---|---|---|---|
| state-tagpicker | 72.8 | **137** | 18 | clipping **0.0/15** |
| state-reader-doc | 73.3 | 137 | 18 | clipping 0.0/15 |
| state-reader | 74.2 | **177** | 18 | clipping 0.0/15 |
| inbox | 74.3 | 137 | 18 | clipping 0.0/15 |
| state-toast | 74.3 | 137 | 18 | clipping 0.0/15 |
| message | 76.1 | 112 | 0 | clipping 0.0/15 |
| label | 78.0 | 116 | 3 | clipping 0.0/15 |
| state-attention | 79.9 | 112 | 0 | clipping 0.0/15 |
| state-search | 80.5 | 116 | 0 | clipping 0.0/15 |

**dimension means (mobile):** layout **25.0/25**, clipping **0.0/15**, touch **4.9/10 (49 %)**,
type 11.3/15, contrast 14.7/15, consistency 10.0/10, states 10.0/10.

Every single view loses the whole clipping dimension at 390px: 112–177 elements are cut inside a box
that offers no scrollbar, while `overflow=0` — nothing spills past the page. So this is not a
"too wide" defect, it is the opposite one: content that has nowhere to go inside its own box.

## The verdict against DGO-56's acceptance

| app | profile | overall | ≥85 | every dimension ≥70 % of its own max |
|---|---|---|---|---|
| mailview | desktop | 82.2 | ❌ | ❌ clipping 48 %, touch 58 % |
| mailview | phone 390 | 74.3 | ❌ | ❌ clipping **0 %**, touch 49 % |
| bina-ds | desktop | 95.5 | ✅ | ⚠️ `states` 5.5/10 — the page captured is not yet the agent (§3) |
| bina-ds | phone 390 | 95.5 | ✅ | ⚠️ the same |

So **DGO-56 is not met** for mailview, and it is not a taste question: two dimensions have names and
counts. The smallest fix that moves the number is clipping at phone size (one dimension, 15 of 100,
lost whole), then touch targets at 390 (44px is the coarse-pointer floor, 49 % today). bina-ds already
clears both targets on paper — its one lost dimension is the bundle-loading defect of §3, and its
number is to be re-taken after that build.

## 3 — bina-ds: measurable since 2026-10-11, and what it scores (the defect that remains)

**The auth half is closed.** A fresh capture of the bina tile through the office edge now renders the
agent's own shell (`main CAPTURED ok`, 1/1 views), where on 2026-10-09 the same capture photographed
the console's "no screen" card. The edge signs `X-authentik-username`, the console forwards it to the
app, and `DSH_TRUST_PROXY_AUTH_HEADER` accepts it — the fix the item asked for, and it holds without
a human having opened `dsh web` first.

Today's measurement (2026-10-11, `UI55_APPS="bina mailview" bash scripts/ui-coverage/dgo55-score.sh`):

| profile | app | views | platform score | worst view | dimensions lost |
|---|---|---|---|---|---|
| desktop 1440×900 | bina | 1/1 | **95.5** | 95.5 | `states` 5.5/10 |
| phone 390×844 | bina | 1/1 | **95.5** | 95.5 | `states` 5.5/10 |

Every other dimension is full marks (layout 25/25, clipping 15/15, touch 10/10, type 15/15, contrast
15/15, consistency 10/10). `states` is `10 × elements/120` and the captured page has **66 elements**
— because the agent's client bundles never loaded (below). So 95.5 is the score of a page that is
*not yet the agent*, and the number moves up when the bundles load, not because of styling.

**The defect (measured, with both sides of the evidence).** The harness addresses its lazy client
bundles at the ROOT of the origin it thinks it owns:

```
GET /a/bina/plugins/??@deepseek-ai/dsh-client-modules/client.js&rev=8c97ded2fa2b  → 200, 20876 B, JS
GET    /plugins/??@deepseek-ai/dsh-client-modules/client.js&rev=8c97ded2fa2b     → 200,  6251 B, HTML
      (the console's own SPA fallback — `Content-Disposition: inline; filename=index.html`)
```

A root-absolute URL ignores the injected `<base href="/a/bina/">`, so a `<script>` received the
console's index page and the tile said **"Failed to load plugins"**, listing every entry
(`ci-artifacts/screenshots-ui/bina__main.png`). The console's proxy is not at fault: the URL it
serves carries the prefix — the *boot manifest inside the page* (`window.__DSH_BOOT__`, rows with
`"url":"/plugins/??…"`) does not.

**The fix** is in the app, where the contract is (`platform-base/console/app.py`: "apps must use
RELATIVE URLs; root-absolute ones would otherwise escape"): the load hook resolves a bundle URL
against the page's own base path — `/` whatsoever when the harness is the origin, so it is a no-op
outside a frame. Patched by `apps/bina-ds/harness/customize.sh` (commit `cf221da1`, exactly-once
anchor like the other three customizations). Proven as far as it can be before a rebuild: the anchor
matches once, the bundle passes `node --check`, and the helper from the patched file resolves all
four URL shapes in a real Chromium. **The live tile keeps the old bundle until the next bina-ds
image build** (the composed bundle is held in memory; HMR does not recompose in this deployment), so
that is where the two numbers above are to be re-measured — and where the `states` dimension is
expected to stop being the only one lost.

## 4 — The harness/REPL half: the ui-map cannot compose its image from inside bina-ds

`bbox ui-map` also failed here on `scripts/ui-coverage/compose_map.py`:
`ModuleNotFoundError: No module named 'PIL'` — the capture itself ran (in the `ui-capture` image), but
the compose step runs in the CALLER, and the office agent's container ships no Pillow. Same class of
gap as the pinning that `data/ui-map/ui-capture.py` already documents: a documented agent command
whose dependency is not in the image the agent runs in. Recorded here because it hit this run; the
home for the fix is `apps/bina-ds/Dockerfile`.

## 5 — Found on the way: the heavy-job slot leaked to watchdogs (fixed)

`scripts/lib.sh::heavy_admit` holds the "one heavy job at a time" slot as an `flock` fd. flock(2)
locks belong to the **open file description**, and bash does not set close-on-exec on
`exec {fd}>>` — reproduced minimally:

```
$ bash -c 'exec {fd}>>/tmp/z.lock; flock -n "$fd"; ( sleep 25 ) & exit 0'
$ sleep 1; flock -n /tmp/z.lock true; echo $?    # 1 → still held, by an orphaned `sleep`
```

`run_capture.sh`'s shard watchdogs are `( sleep 900; … ) &` — they outlive the capture on purpose, so
a finished `bbox ui-map` kept the slot for up to 15 more minutes and the next heavy job waited on a
process that no longer existed. Measured on both offices: on `srv000001` the mobile profile sat in
`waiting for the heavy-job slot … held by: ui-map --profile desktop | pid 2817452` while that pid was
gone and only `sleep 900` (ppid 1) held the fd; `kill` of that stray sleep released the slot and the
queued capture started immediately. Fixed by `heavy_detach` (lib.sh) — called first thing in the
watchdog subshell — with the reproduction in its comment.
