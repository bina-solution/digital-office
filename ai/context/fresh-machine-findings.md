# What a genuinely fresh machine found

The stack was rebuilt from nothing — new Docker engine, empty volumes, a clone with no `.generated/`
and no local caches. Eight bugs surfaced. **Every one of them was invisible on a warm machine**, and
that is the whole point of the list: each had been latent for a while, and none would have been
found by running the baseline again on a box that had already run it.

Chronological, with what made each one hard to see.

## 1. n8n's bulk import races on shared tag names

`bbox n8n push` printed "An error occurred while importing workflows" and the workflow table stayed
at **zero**. Two levels down:

```
duplicate key value violates unique constraint "idx_812eb05f7451ca757fb98444ce"
```

— the UNIQUE index on `tag_entity(name)`. `import:workflow` creates each workflow's tags as it
walks them, and twenty tag names here are shared by more than one workflow (`indox` alone by 48).
The bulk run races to INSERT the same tag twice and the entire import rolls back.

**Why it hid:** it needs an *empty tag table*. Any machine that has ever run a push already has the
tags and never races. A clean install always does.

**Fix:** insert every referenced tag once, before the import. `platform-base/n8n/hooks/push`.

**And this is almost certainly the long-standing CI failure too.** `integration-n8n-workflows` has
been failing with "workflows 80 < 84" for a while, and everyone (including me, in the first pass)
read that as a counting problem. It is the same bug: the import is not transactional, it *stops* at
the first tag collision. CI happened to collide near the end and got 80 of them; this machine
collided at the start and got 0. Same cause, two very different-looking symptoms, and only the
second one is obviously a failure. The counting fix (deriving the expectation from
`reconcile.py blueprints` instead of globbing every app's blueprint, installed or not) is still
correct and still needed — it was a second, independent bug in the same check.

## 2. The n8n encryption key had drifted from the blueprint

`.env`'s `N8N_ENCRYPTION_KEY` (fingerprint `ddd175d8`) no longer matched the key the committed
credentials are encrypted under (`77aee1e8`, the `.env.ex` value). n8n's credential UPDATE decrypts
the stored blob first, so the push died on the first credential and nothing after it ran.

**Why it hid:** the push hook checked the fingerprint and only *warned*, and its warning text was
wrong — it said workflows would still restore. They do not.

**Fix:** `.env` aligned to `.env.ex` for that key (backup beside it), the hook refuses with the
remedy, and `scripts/env-consistency-check.py` runs in baseline P0 so it is caught in the first ten
seconds rather than the fiftieth minute. It also checks the Supabase JWTs against
`SUPABASE_JWT_SECRET` — the other value here that must *agree* with something rather than merely be
set, and the one that once took out all six document/sync suites with `Invalid Compact JWS`.

**And a correction I had to make to my own fix**, because it is the same mistake in the other
direction. I first made the mismatch unconditionally fatal, which broke CI: `ci-env.sh` mints
throwaway secrets, so the CI key never matches the blueprint and never did — run #250 came back with
`n8n-push failed (after retries)`, 0 workflows, 0 credentials. A mismatch is fatal only when the
instance ALREADY holds credentials under a different key, because then updating them means
decrypting them first. On a fresh instance there is nothing to decrypt and the credentials are
simply created under this key. The hook now counts `credentials_entity` before refusing, and the
preflight refuses only when the drift is *fixable* — when `.env.ex` carries the blueprint's key and
`.env` has drifted off it. Anything stricter blocks a legitimate environment.

## 3. apitools crash-looped on a missing libGL

`requirements.txt` asks for `opencv-python-headless`, but `layoutparser` depends on plain
`opencv-python` and pip installed both. They ship the same `cv2` package, so the last one wins — the
GUI build, which links `libGL.so.1`, deliberately absent from this image.

**Why it hid:** a warm machine has the image cached from before the layoutparser pin.

**Fix:** make headless authoritative after install. `--no-deps` on the reinstall is load-bearing —
without it pip drags numpy 2.x over the pinned 1.26.4 and cv2 dies differently.

## 4. whatsapp was permanently unhealthy while working perfectly

Its probe was `curl -f http://localhost:3000` on a `node:22-slim` image, which has no curl. Every
check died with `exec: curl: executable file not found` — the probe was reporting on the probe.

**Why it hid:** nothing fails. The container just never goes healthy, `bbox run` waits out its whole
window, and the card shows red for an app serving 200s.

**Fix:** probe with `node`, the one binary the image is guaranteed to have, against `127.0.0.1`
(node 18+ resolves `localhost` to `::1` first and the server binds IPv4). Plus **two** gates, because
the failure is silent by construction: G18 statically, and a live probe audit in baseline P3.

## 5. Docker 29 breaks all routing, silently

Traefik v3.3 compiles its docker client against API 1.24. Docker 29 raised the daemon's *hard*
minimum to 1.40 and capped `DOCKER_MIN_API_VERSION` there, so the documented workaround is accepted
and does nothing. Traefik starts, reports healthy, discovers **zero** routers, and every
`*.localhost` 404s.

**Why it hid:** it isn't an error anywhere. It looks like a hundred unrelated test failures.

**Fix:** run Docker 28.x (what production runs). `bbox baseline` P0 now fails fast and says so.
The real fix — a traefik release whose docker provider negotiates the version — needs its own
validation pass and is recorded as debt.

## 6. The label bootstrap ran before the fixtures it reads

`mail_organizer` failed 0/2 — 22 labels never created, `DOC_TO_SYNC` never applied — for a label
engine that is fine. `bootstrap_localmail()` seeds GreenMail's label registry *from* `tag_rules`,
and ran once up front. On a fresh database `tag_rules` is empty then: the suites seed it themselves
as they run.

**Why it hid:** this gate had never been seen red. Its first real verdict was this one. Worth saying
plainly — the gate was doing its job; the harness around it was not.

**Fix:** retry before each suite, latch on success.

## 7. The reference third-party app could not be embedded

`hello-bina` declared `embed: true` with an alias but no `url`, so the compiler emitted a console
tile with nothing behind it, and it was missing from the ui-coverage manifest entirely — which made
`bbox ui-map` refuse to run at all. It also meant the sample app was not being counted (94 views
across 17 apps → 95 across 18).

**Why it matters more than the others:** this is the app an author copies.

## 8. The label engine had been a silent no-op

`mail_organizer`'s label-engine lane failed 5/8: an appended, unlabelled message with an attachment
came back with `labels=[]` — not even `PROCESSED`, which the engine applies unconditionally.

`Sub Search` was an `executeWorkflow` node on **typeVersion 1.1** passing a literal `op: "search"`.
Below 1.2 n8n sends `null` for **every** input field, not just the literal one:

```
Sub Search  ->  gmail api received {"op": null, "params": null}
            ->  matched no branch, returned nothing
            ->  the engine stopped, labelled nothing, and reported SUCCESS
```

**Why it hid** — and this one is the worst of the eight. Nothing errors. The engine execution is
green, the router execution is green, and no mail is labelled. Every *other* gmail lane injects mail
that already carries its to_sync label, so a total labelling outage looks like a healthy empty run.
The only thing that could ever have caught it is the one lane that appends UNLABELLED mail, and that
lane had never been run: the harness bug in finding #6 meant it had never got as far as a real
verdict.

**How it was found**, because the method is the transferable part. Reading the 54-node workflow
produced a confident, wrong answer (I wrote "local mode does not supply attachments" into the
handoff doc before checking it). What settled it was `scripts/n8n-exec-dump.py --raw`, which showed
the node's stored `runData` verbatim: the real sub-execution id, and eight empty output arrays. I
had been reading the wrong child execution the whole time.

Gate: **G19** scans every `executeWorkflow` node in the installed blueprints — 412 of them — and
refuses this pattern. It earns a permanent lint rather than a one-off fix because the failure is
silent AND the bug is invisible in review: `typeVersion` is a field nobody reads, and the mapping
beside it looks perfectly correct.

## What this says about the gates

Six of the eight are now gated: **G16** conditions, **G17** resolver, **G18** healthcheck binaries,
**G19** sub-workflow inputs, the live probe audit in baseline P3, and the env-consistency preflight
in P0. Two are not gateable — one is a property of the host (Docker version), one of ordering inside
a test harness — and both now fail loudly with the remedy in the message.

The common thread is worth stating on its own, because it predicts where the next one will be.
**Every failure here was silent.** Not one produced a stack trace anybody would see: an import that
stops half-way and reports a count, a probe that reports on itself, a router that returns nothing
and succeeds, a traefik that discovers zero routers and stays healthy. The loud failures had all
been found already. What was left was the class that needs someone to ask a question nothing was
asking.

That is also why finding #8 is the one to remember. It was invisible for however long the engine had
been running, and the only thing that could have caught it was a gate that existed but had never
been run — so the gate's own first real verdict was the discovery. A test suite you have never seen
fail is not evidence; it is an untested assumption with good branding.

## The gap this exposes

`scripts/fresh-machine-check.sh` proves a bare clone **compiles, renders and passes the static
gates**. It never starts n8n, so it could not have caught #1, #2, #6 or #8 — half the list. A lane
that pushes the blueprint into a *fresh* n8n and asserts the counts would have caught all four, and
it is the highest-leverage thing left to build here.

The push now asserts its own completeness (staged vs. present), which closes part of it wherever a
push runs — CI included. The rest is the lane.
