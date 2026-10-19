# DGO-55 / DGO-56 — the comparative beauty score: what was measured, and what it says

The protocol is [dgo55-56-proof-protocol.md](dgo55-56-proof-protocol.md); this file is its result.
Every number below came from a real capture on 2026-10-09; where a half could not be measured, it
says so and names the defect instead of inventing a score.

## What was run, and where

| half | where | command | views | result |
|---|---|---|---|---|
| **mailview** | the **staging office on srv908573** (`31.97.196.82`, the office that runs the mail stack: `mailview-staging`, `mailapi-staging`, `mailserver-staging`, `mailboxd-staging`) | `UI55_APPS=mailview bash scripts/ui-coverage/dgo55-score.sh` | **9/9 desktop, 9/9 mobile — all `CAPTURED ok`** | ✅ measured |
| **bina-ds** | this office (hp-dgo), live | `UI55_APPS=bina bash scripts/ui-coverage/dgo55-score.sh` | **0/1 desktop** — `main FAILED embedded app near-empty (20 nodes)`, retried, still failed | ⛔ blocked by a real defect (§3) |

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
| bina-ds | both | — | — | not measurable: the capture sees the console's "no screen" card (§3) |

So **DGO-56 is not met, and it is not a taste question**: two dimensions have names and counts. The
smallest fix that moves the number is clipping at phone size (one dimension, 15 of 100, lost whole),
then touch targets at 390 (44px is the coarse-pointer floor, 49 % today).

## 3 — Why the bina-ds half could not be measured (the defect, with its evidence)

The console embeds the office agent at `/a/bina/`; a browser that has never held the harness's own
session cookie gets, from the harness itself:

```
$ curl -s http://console:8000/a/bina/
401  dsh web authentication required; reopen the URL printed by dsh web.
```

That is the app's own line, and `platform-base/console/app.py` (`_app_no_screen`, lines 600–614)
already knows it and renders a card — "אין לה מסך להציג … היא לא זיהתה את הכניסה שלך" — instead of the
agent. The ui-map's capture is exactly such a browser (a fresh context), so it photographs the card:
`embedded app near-empty (20 nodes)`, 0/1 views. The owner's own browser works because he has, at
some point, followed the URL `dsh web` printed; nothing in the office gives the console that identity
on his behalf.

**What closes it** (the work, not a wish): the console must be able to open its OWN agent without a
human — the harness accepts a bearer token on its API (`apps/bina-ds/harness/customize.sh` patches its
auth to `tokenMatches(authz.slice(7), apiToken)`) and the office holds that token at
`/data/dsh/api-token`, so the console's proxy should sign in to its own agent with it (and the capture
should either drive that door or be given the same session). Until then the bina half of DGO-55 is
"not measured", never "no findings".

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
process that no longer existed. Measured on both offices: on `srv908573` the mobile profile sat in
`waiting for the heavy-job slot … held by: ui-map --profile desktop | pid 2817452` while that pid was
gone and only `sleep 900` (ppid 1) held the fd; `kill` of that stray sleep released the slot and the
queued capture started immediately. Fixed by `heavy_detach` (lib.sh) — called first thing in the
watchdog subshell — with the reproduction in its comment.
