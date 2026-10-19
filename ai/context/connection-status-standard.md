# Connection status — what the platform must say, what it says today, and why the link is dead

Written 2026-10-04, from a measured outage (a linked office unreachable from a phone, with **nothing
on screen explaining it**). **Repaired the same day — see §1.4 for the root cause and the fix.**
Two halves:

* **§1–3 — the outage**: what is actually broken right now between `macbook` and `vps1`, the exact
  evidence, and why the surface the owner was looking at could not say a word about it.
* **§4–8 — the standard**: one normative model for "connected / degraded / unreachable / unknown"
  across every hop, the gap between it and what exists, the ordered plan to close it, and the
  acceptance each item must pass.

Model and vocabulary come from [dgo-remote-apps.md](dgo-remote-apps.md) (the live link/remote-app
model) and [digital-office-network-plan.md](digital-office-network-plan.md) §5.4 (the *unbuilt*
richer vocabulary: `active / degraded / offline / revoked`). Where they disagree this document is
normative and says so.

---

## 1. The outage, measured

The pair, as the platform itself reports it (`GET http://dgo-extend:8983/api/link`):

| | macbook (home) | vps1 |
|---|---|---|
| office id / slot | `macbook` / 2 | `vps1` / 2 (far end) |
| tunnel address | `10.79.2.1` | `10.79.2.2` |
| domain | `localhost` | `staging.digital-office.co.il` |
| commit | `dad40e66` | `dad40e66` |
| tunnel runs on | `dgo-net` container (dialing end) | **the host** (`wg-quick@wg0`, `dgo-link-door.service`) |

**The link is dead, and has been for ~15 hours.** Evidence, all re-runnable:

```
# home — the platform's own verdict
curl -s http://dgo-extend:8983/api/link | jq '.items[] | {office,state,state_error}'
#   vps1 → state "down", state_error "ConnectionResetError"   (every app of vps1: ok=false)

# the tunnel, both ends
docker exec dgo-net-local wg show wg0          # latest handshake: 15 hours ago
#   on vps1: wg show wg0                        # latest handshake: 14h59m ago, rx frozen, tx growing

# the two proxies, every few seconds
docker logs --tail 5 dgo-link-local            # dgo-extend: nothing answers at 10.79.2.2:8983 (timed out)
#   on vps1: nothing answers at 10.79.2.1:8983 / door: nothing answers at 10.79.2.1:9002
```

So every remote tile on **both** consoles points at an app behind a tunnel that carries nothing:
on vps1 the `bina.macbook` tile ("בינה ודעת" = this office's `bina-ds`), and on the home console the
17 `remote.vps1.*` tiles. The owner's `ssh` to the same server, and the git/office APIs, work
normally — the machine is fine; the **tunnel** is not.

### 1.1 The path is fine; the tunnel's socket is wedged

This is the part worth writing down, because it rules out the usual suspects:

```
# every packet sent from this office to 31.97.196.82:51820 arrives at the server —
# proven by the server's own ufw counter, which moved by exactly the number sent:
iptables -L -n -v -x | grep 'udp dpt:51820'        # on vps1
#   268566 → 268596  (+30, python socket, ephemeral source port)
#   268606 → 268616  (+10, bound to source port 51820)
#   268616 → 268624  (+8,  148-byte payloads — handshake-sized, source port 51820)
```

Meanwhile the WireGuard peer inside `dgo-net-local` **counts itself as sending** — `ip -s link show
wg0` TX grew 592 B in 21 s (≈ one 148-byte handshake initiation every ~5 s, exactly what
`persistent-keepalive 25` + pending traffic produces) — and the server never sees one of them.

Conclusion: the UDP path, the NAT, the firewall and the keys are all fine; the loss is **specific to
the flow's source port**, and re-applying the tunnel on the same port does not recover it — see §1.4
for the resolution ("a stop/start of `wg-quick@wg0` brings both back" — `dgo-remote-apps.md:534` —
was the pre-2026-10-04 answer and did not hold here).

```
./bbox dgo link status          # what is declared vs what is rendered
./bbox dgo link up vps1         # re-render the link on BOTH ends, then a real ping
```

That verb was run twice on 2026-10-04: the first time it failed the step with
`המנהרה לא מעבירה תנועה: 10.79.2.1 לא ענה לפינג מן המכונה המרוחקת` (correct, and the clearest sentence
the platform produced all day), and after the port fix it returned `link: ok`. Both ends run the same
commit (`dad40e66`), so the plan *shape* was never straddling versions — the
`dgo-remote-apps.md:598-604` ordering rule is satisfied.

### 1.2 A live DNS landmine in the same declaration

The declared tunnel endpoint is the **name** `staging.digital-office.co.il`
(`GET /api/office` → `tunnel.endpoint`), and that name **has no A record**:

```
staging.digital-office.co.il        → NOERROR, no answer (only a TXT spf record)
*.staging.digital-office.co.il      → 31.97.196.82, at ANY depth (a.b.c.d.staging… resolves)
bina.macbook.console.staging.…      → 31.97.196.82
```

Two consequences, both already recorded as traps and neither enforced:

* `dgo-extend-azaria-findings.md` — *"`Endpoint` must be an IP — a name breaks inside a container"*:
  `wg-quick up` fails with `Name or service not known`, **the entrypoint logs `wg-quick failed on
  re-apply` and carries on**, and *"the office runs with no tunnel while every screen says the link
  is up"*. Today this is only survived because the applied config still holds the IP resolved
  earlier (31.97.196.82).
* `digital-office-network-plan.md` נספח ב — *"an entry host must be a name that resolves"*. Nothing in
  `platform/manager/serve.py` or `apps/dgo-extend/*.py` resolves a host before publishing it
  (no `getaddrinfo` anywhere in either), so the rule is documentation only.

### 1.3 What the owner saw, and why it was blank

The screenshot: `console.staging.digital-office.co.il`'s rail, tile **בינה ודעת** (the MacBook's
agent, published to vps1 as `bina.macbook`), and a grey content area with the browser's dead-frame
glyph.

Measured, hop by hop:

| hop | result |
|---|---|
| console host `console.staging.…` | 302 → authentik ✓ (router + cert fine) |
| tile exists on vps1 | ✓ `.generated/registry/console.modules.yaml`: `id: bina.macbook`, `external: true`, `host: bina.macbook` |
| framed URL `https://bina.macbook.console.staging.digital-office.co.il/a/bina/` (built by `externalUrl()`, `console/static/app.js:~114`) | DNS ✓, certificate is issued **for exactly that name** ✓, router answers 302 to its own authentik provider ✓ |
| the door behind it → the peer | ✗ `nothing answers at 10.79.2.1:9002` (the dead tunnel) |

And the reason there is no sentence on screen is structural, not an oversight in one string:

```js
// platform-base/console/static/app.js:126-141  externalFallback()
try { doc = f && f.contentDocument; } catch (e) { return; }   // cross-origin: it loaded
```

A **remote** app is by definition framed **cross-origin** (`<alias>.<office>.console.<host>`), so the
one detector the console has for "the frame did not come up" returns early, `REMOTE_DOWN` is never
set, `renderExternalNotice()` never runs, and the owner gets the browser's own placeholder. The
console's careful Hebrew card (`app.js:151-156`, naming the office and distinguishing *מכובה /
מנותקת / הקישור נפל* from *הטעינה לא הושלמה*) is unreachable for exactly the apps it was written
for. The tile itself looks **healthy**: `remoteInfo(m).off` is `r.ok === false || REMOTE_DOWN.has(id)`
(`app.js:195`) and nothing ever writes `remote.ok` (`console/app.py:144` reads it; the only writer of
peer files, `apps/dgo-extend/peers.py:95-110`, emits `{office, alias, label, module, base}` — no
`ok`). The office-level truth exists (`/data/remote-status.json` → `ok/at/error` → `/api/link` →
`state: down`), is fetched by `app-management` every 60 s, and is then **discarded** — the only
surface that renders any of it prints `הקישור לא ענה` and drops `state_error` (which today is the
Python class name `ConnectionResetError`, not a sentence).

---

### 1.4 Root cause, and the repair (same day, 18:20–18:45)

**The one flow sourced from UDP port 51820 was being dropped on the way out of the office, and
WireGuard kept counting it as sent.** Steps that proved it:

1. A local listener test (the peer's endpoint pointed at another container for 20 s) showed the
   handshake initiations **are** transmitted: `RX … from ('172.18.0.2', 51820) len 148 type 1`.
2. `tcpdump` on the office's own machine showed each one leaving as
   `192.168.5.15.51820 > 31.97.196.82.51820: UDP, length 148` — out of the VM, on the wire.
3. `tcpdump` on the server, and its ufw counter, saw **none** of them — while 148-byte packets of the
   same shape, from the same machine and from another container, sent to the same address and port,
   arrived every time (proved by the counter moving by exactly the number sent).
4. Re-applying the plan — a fresh container and a fresh `wg0`, same port — did **not** help, so it was
   not a wedged interface.
5. `wg set wg0 listen-port 51830` → **handshake in 10 seconds**, both ends, after 15 hours of silence.

So the dialing side's source port is the one part of the path this office does not control, and it
was blackholed (a stale NAT/conntrack binding for that 5-tuple, or an ISP/router rule against it —
both are consistent with the evidence; what is not in doubt is that the port, not the interface, was
the variable).

**The fix, landed:**

* `apps/dgo-extend/net.py` — `local_listen_port(dial)`: the dialing side's `ListenPort` comes from
  `DGO_WG_PORT` (default: the pair's port). **The dialed side keeps `WG_PORT`**: that number is the
  address this office dials (`<peer endpoint>:51820`) and the far end's firewall allows it by name, so
  moving it on one side only would be a link that stops handshaking with no error anywhere. Both
  branches are asserted in `net.py`'s selftest.
* `apps/dgo-extend/docker-compose.yml` — `DGO_WG_PORT=${DGO_WG_PORT:-}` on the app (the renderer).
* `.env` — `DGO_WG_PORT=51830` for this office; `.env.ex` documents the knob and when to set it.
* Rebuilt, re-converged: `./bbox dgo link up vps1` → `link: ok`,
  `מנהרה מול vps1 (both): 10.79.2.1 ↔ 10.79.2.2 · פינג חזר`, delivery
  `{bina-ds:agent: open, dgo-extend: open, door: open}`, `/api/link` → `state: up` with every vps1
  app `ok: true`, and from vps1 `curl -H 'Host: bina.localhost' http://10.79.2.1:9002/` → **200**.

**What this incident says about the standard, beyond the port:** the platform produced no sentence
about it anywhere (`/api/link` said `down / ConnectionResetError`, `/api/tunnel` said the files were
present, and the tile said nothing at all) — which is exactly what §4's S2/S3/S5 and §7's P1–P3 are
for. A tunnel that is "up" in every rendered file and dead on the wire must be a state, not an
absence.

---

## 2. Why "it works on one machine and not the other" is the expected shape

Nothing above is a one-off. The platform has **four independent status vocabularies** and no single
place that answers "what is broken and what do I do":

| layer | who decides | vocabulary today | reaches a screen? |
|---|---|---|---|
| office/link | `dgo-extend` `/api/link` → `up` / `down` / `unknown` + `state_error` | ✔ (but `state_error` is a class name) | only `app-management`: `הקישור פעיל` / `הקישור לא ענה` / `מקושרת בלי מנהרה` / `מקושרת` |
| tunnel | `GET /api/tunnel` — file presence + byte counts | — | **nobody** (zero consumers in `apps/dgo-extend/static/`) |
| remote tile | the browser, from a blank frame | `REMOTE_DOWN` (never cleared, never set for cross-origin) | rail/home/palette/dock strings |
| app / service | console `/readyz` probe | `מחובר` / `בבדיקה` / `דורש טיפול` / `שגיאה` (`app.js:918-943`) | ✔ — and this one is the *model* the rest should follow |

A tunnel that is up while the peer's catalog is silent (the design's `degraded`) has **no field at
all**; a peer that was never pulled is `unknown`; "declared but never converged" is not a state
anywhere; and an app that is enabled with its container down is presented as raw JSON inside the
frame (`{"error":"app_unreachable","app":"drive","message":"HTTPConnectionPool(host='drive',
port=8975)…"}`, `console/app.py:481`).

---

## 3. The bar the project already set for itself

This is not a new standard — it is the one already written down, in three places, and only partly
honoured:

* **`digital-office/sim/ASTRYX-EXTRACTION.md:143-145`** — *"Every state is designed — never a
  dead-end. Loading → Skeleton, Empty → Empty State with a next action, Error → recovery affordance…
  every view answers 'what now?'"*; `:161` non-blocking status/banner over modal.
* **`platform-base/console/static/app.js:918-943`** — the four-state chip, with the two rules that
  make it trustworthy: **unknown ≠ error ≠ needs-action** (the service answered "not ready" → it knows
  why → `דורש טיפול`; it did not answer → `שגיאה`; it answered off-contract → its own sentence), and
  **no false green** (`:1088-1093`: a last-known verdict must say it is last-known; badge and summary
  derive from one function so they cannot contradict).
* **`digital-office/design/INDOX-SYNC.md:57-67`** — recovery is the only move offered, and failure is
  never a button: `failed → נסה שוב`, stuck `in_progress → שחרר`, `synced → סנכרן מחדש`.

And one explicit exclusion that decides where the reference must come from: the sim **excludes**
offline states by construction (`DRIVE-MAIL-COMPONENTS.md:826-827`: an always-true offline banner
would be *"permanently meaningless"*), and `PORT-PLAN.md:95` forbids closing that gap through the
sim. So for disconnection the console's live chip/`REMOTE_DOWN` behaviour is the de-facto spec, and
the sim is ported *toward* it — the inverse of the usual direction.

---

## 4. The standard (normative)

**S1 — One taxonomy, applied to every hop.** Every status surface composes from the same four
states, in the same Hebrew, with the same colours as `app.js:918-922`
(`מחובר` / `בבדיקה` / `דורש טיפול` / `שגיאה`). A new surface that invents a fifth word is a defect.

**S2 — `unknown`, `degraded` and `offline` are different states, and each names its actor.**
`unknown` = we have no measurement (never probed / never converged); `degraded` = the transport works
but the thing behind it does not answer (the handshake is fresh, the catalog is silent → *do not
route there*); `offline` = the transport itself is down. Adopt the semantics of
`digital-office-network-plan.md` §5.4 verbatim; `down` is a **cause**, not a state, and must stop
being a user-visible word.

**S3 — Every state names the hop, not just the office.** The owner must be able to tell "the MacBook
is switched off" from "the tunnel is up but its console is not answering" from "the tunnel is down"
from "the app's container is down" from "SSO did not complete" from "the name does not resolve".
§5 is the hop table; a surface may show fewer hops but may never *conflate* them.

**S4 — Every non-`מחובר` state carries the next action.** At minimum one of: `נסה שוב`
(re-probe), `הער את הקישור` (run the link step), `פתח את הלשכה` (the peer's own console),
`פתח את האפליקציות` (app-management), `פתח בחלון נפרד`. No state may be a dead end (S-ref:
`ASTRYX-EXTRACTION.md:143-145`, `INDOX-SYNC.md:57-67`).

**S5 — A verdict is live, or it says when it was taken.** Any value that came from a stored result
must carry its age (`נבדק לאחרונה 14:02`, amber after the freshness window — the `data-stale`
pattern already in `machine/static/index.html:385-386` and `bina-ui/bina-page.css:75-77`). Never
render a stored value in the same skin as a measured one.

**S6 — Evidence beats a declared field, it propagates, and it expires.** A runtime observation
(a frame that never rendered, a probe that failed) must mark *every* surface that lists the item
(rail, home tile, bottom nav, palette, dock) — and must be **cleared** when a later probe succeeds.
Today `REMOTE_DOWN` is `add`-only (`app.js:184`), so one blank frame marks an app dead for the life
of the page even after the office recovers.

**S7 — Never a dead frame.** The content frame is not allowed to be the first thing that fails
silently. Two mechanisms, both required:
(a) a **pre-flight**: before framing an `external` app, ask the office's own backend for its verdict
on that app (`/api/modules` already knows the office, the link state and the target host) and, when
it is not `ok`, render the Hebrew card *instead of* the frame;
(b) a **watchdog that works cross-origin** — a same-origin probe endpoint the frame's host reports
into, or a `postMessage` heartbeat from a tiny page the console serves through the same door — so a
cross-origin frame that never paints is detected too. `externalFallback()`'s `catch → return` is the
bug this rule outlaws.

**S8 — No raw technical strings to the owner.** Exception class names, HTTP codes, `str(e)`,
internal hostnames and ports (`ConnectionResetError`, `TypeError`, `Failed to fetch`, `HTTP 502`,
`host='drive', port=8975`, `unreachable`) belong in the log and in an expandable "details" fold —
never in the sentence. The API keeps `state_error` for machines; the UI shows a *cause class* and a
*direction*, and offers details on demand.

**S9 — The platform's own blindness is a state too.** When the engine socket is unreadable, 40 apps
each saying `אין מידע` is not a status; it is noise. One banner at the top of the rail:
*"הפלטפורמה לא מצליחה לקרוא את מצב המכולות"* + the reason + the action. The same for a vault that is
unreachable (today `connections_unreachable` reaches the owner) and for the console's own
unconditional `healthz` (`console/app.py:76-79` returns `{"ok": true}` always).

**S10 — One owner per fact, and no orphan readers.** A field that is read must be written: either
`peers.py` writes `ok` into the peer record (from `remote-status.json`, per office **and** per app),
or `console/app.py:144` stops reading it. Per-app `ok` must not be the office-wide bit
(`dgo-extend/app.py:856` currently stamps every app with the office's liveness).

**S11 — Every status is assertable.** A new state must be registered in
`scripts/ui-coverage/manifest.yaml` (`states:` + a DOM recipe) and driven by a
`digital-office/sim/flow-qa.py` suite at desktop **and** `--mobile`, with a **fault-injection
fixture** (a mock/fixture that makes the office unreachable on purpose) — otherwise the class stays
in `UI-INVENTORY.md` bucket 5 ("not coverable in a healthy run") and `score.py:109-111` keeps scoring
a wrong state green on element count alone.

**S12 — Repair is one verb per failure class, and it is the same one the docs give.** `מצב` surfaces
must name the verb, and the verb must exist: `./bbox dgo link status|up|down` (tunnel),
`./bbox dgo` / `bbox apps` (office convergence), `docker restart authentik-server-*` (SSO),
`bbox remote <office> <alias>` (one authenticated call through the link).

---

## 5. The hop table (what to measure, per layer)

Each row: the hop, the cheapest true measurement, where it exists today, and what a UI must say.

| # | hop | measurement | exists today? | must say (on failure) |
|---|---|---|---|---|
| 1 | **machine** (the peer's host) | `computers` probe over SSH (`/api/computers/<id>/status`, with `classify_stderr`) | ✔ best-in-class (`computers/static/app.js:19-26`, `app.py:459-490`) | `המחשב <label> לא עונה` + the classified cause + its `action` |
| 2 | **tunnel** | `wg show wg0 latest-handshakes` age vs 3× keepalive, both ends; plus the applied-config fingerprint | partly: `GET /api/tunnel` (file presence only), no consumer | `המנהרה מול <office> לא מעבירה תנועה (לחיצת יד אחרונה לפני X)` + `הער את הקישור` |
| 3 | **addressing / DNS** | resolve the endpoint name and every published `<alias>.<office>.<console-host>` | ✗ nowhere | `השם <host> אינו נפתר ל־DNS — פנה לספק הדומיין`; block the publish instead (§1.2) |
| 4 | **door** | one TCP connect + one HTTP call to `<alias>.<office>:<door>` from a container that shares the tunnel namespace | ✗ (only a log line in `dgo-link`) | `דלת הקישור אינה עונה` |
| 5 | **catalog / projection** | `GET /api/link` `state`/`state_error`/`state_at` (already computed) | ✔ computed, ✗ discarded | `הלשכה <label> לא ענתה לאחרונה ב־HH:MM` + the cause class |
| 6 | **edge** (peer's traefik + cert) | HTTP status for the nested host (302 = router+SSO alive; 404 = no router; cert SAN) | ✗ | `הקצה של <label> אינו מנתב את <alias>` |
| 7 | **SSO** | is there an authentik provider for the exact host (compiled) + did the flow complete | partly (compiled providers exist) | `נדרשת התחברות ללשכה <label>` + open-in-new-window |
| 8 | **app container** | `app-management` conditions per app (`Started`/`Ready`, `DockerUnavailable`) | ✔ (`app-management/static/app.js:72-86`) | `האפליקציה <name> כבויה בלשכת <label>` + `הפעל` |
| 9 | **app readiness** | the app's own `/readyz` through the console proxy | ✔ (`app.js:918-943`) | as today — this is the model |

Rule: a surface may only *summarise* rows it can actually measure; a summary that hides which row
failed is worse than no summary (§1.3's blank frame is what that costs).

---

## 6. Gap inventory (today vs the standard)

This is an instance of a class the repo already named and gates: **a correct failure report that the
layer above throws away** (`scripts/refactor/unread-error-lint.py`, gate G66 — an exit code, a
stringified exception, an empty list or a green PASS standing in for a result). Gaps 1–4 below are
that class in the status plane: `state_error` is computed and dropped, `remote.ok` is read with no
writer, per-app `ok` is stamped from an office-wide bit, `REMOTE_DOWN` records evidence that never
expires. The remediation for the status plane is therefore the same shape as G66's: make the
*reader/writer pair* mechanically checkable, not reviewed. (G66's docstring cites
`issues/unread-failure-defect-class.md`, which does not exist in the tree — worth restoring or
repointing while touching this.)

Ranked; `file:line` from the 2026-10-04 sweep.

1. **`remote.ok` is read and never written** — `console/app.py:144` vs `peers.py:95-110`;
   `projection.save_status` writes `remote-status.json` (`projection.py:491-494`) that the console
   never reads. ⇒ S10, §1.3.
2. **`REMOTE_DOWN` never clears and never fires cross-origin** — `app.js:135,184,126-141`. ⇒ S6, S7.
3. **The link is one boolean and its reason is dropped** — `dgo-extend/app.py:856,867-869`;
   `app-management/static/app.js:323-324` renders four strings and discards `state_error`. ⇒ S2, S3.
4. **`/api/tunnel` has no consumer at all** — a wedged tunnel and a healthy one look identical on
   every screen. ⇒ S3.
5. **The console proxy's own failures are served as raw JSON inside the frame** —
   `console/app.py:446` (`unknown_app`), `:481` (`app_unreachable` + `str(e)` with internal
   host:port), `:268,284,293,303`. ⇒ S8.
6. **Raw technical strings leak into Hebrew sentences** — `computers/static/app.js:98,409`;
   `dgo-extend/app.py:307,329,358,1245,748`; `console/static/app.js:1984`;
   `app-management/static/app.js:218,873,498`. ⇒ S8.
7. **Platform blindness has no banner** — `console/app.py:76-79` (`healthz` cannot fail);
   app-management degrades per app to `DockerUnavailable` → `אין מידע`;
   `notifications/app.py:508-533` is the only honest 503 and nothing consumes it. ⇒ S9.
8. **Staleness is admitted in exactly one panel** (the console's connection health,
   `app.js:1088-1093`) and hidden everywhere else. ⇒ S5.
9. **No hop-level surface for a linked office** — `dgo-extend`'s own UI renders none of
   `/api/link`, `/api/tunnel`, `state_error`. ⇒ S3, S4.
10. **Nothing resolves a published host before publishing it** (§1.2). ⇒ S2/S3 precondition.

---

## 7. The plan

Ordered, smallest safe change first. Each item is shippable alone; each names its proof.

**P0 — the outage (today).** Re-apply the link (`./bbox dgo link up vps1`), verify with
`wg show wg0 latest-handshakes` on both ends and a `dgo-link` door probe. Then fix the declaration:
`tunnel.endpoint` must be the IP (or the code must resolve names before `wg-quick`), and the
`.env`/declaration must stop naming a host that has no A record. *Proof*: `curl -H 'Host:
bina.localhost' http://10.79.2.1:3080/healthz` from a container on vps1 → 200; the tile paints.

**P1 — write the field that is read.** `peers.py` writes `ok` (+ `at`, + the cause class) into every
peer record from `remote-status.json`, per office and per app; the console's `remoteInfo()` renders
`is-offline` + `לא זמינה כרגע` from it *before anything is opened*. Clear the mark when a later
verdict is `ok` (S6). *Proof*: unit fixture + with the tunnel down, the tile is already marked, and
with it up, the mark clears within one poll.

**P2 — never a dead frame.** (a) pre-flight in `openModule` for `external`/`remote` modules: ask
`/api/modules`-adjacent backend for the app's verdict and render `renderExternalNotice()` instead of
the frame when it is not `ok`; (b) cross-origin watchdog: a heartbeat the console serves through the
same door (`/a/<alias>/__ping`) or `postMessage` from a wrapper page, so a frame that never paints
is detected; (c) the notice gains hop + action (§5 rows 2–6) instead of the current three-cause
sentence. *Proof*: with the tunnel down, opening the `bina.macbook` tile shows the Hebrew card naming
the office **and** the hop — the screenshot case — at desktop and `--mobile` (S11).

**P3 — the link screen.** `dgo-extend`'s UI renders `/api/link` + `/api/tunnel`: per office the state
(`מחובר` / `מושפל` / `לא מחובר` / `לא נבדק`), the handshake age, the endpoint, the door, the catalog
age, and the two actions (`הער את הקישור`, `בדוק עכשיו`). `degraded` becomes a real field: handshake
fresh **and** catalog silent. *Proof*: with the tunnel down the screen says `לא מחובר — לחיצת יד
אחרונה לפני 15 שעות`, and `bbox dgo link status` prints the same table.

**P4 — publish-time DNS refusal.** Before rendering a router/alias/endpoint for a host, resolve it;
refuse (with the record to add) when it does not resolve; and make the tunnel endpoint an IP at
render time. Applies to the apex case (`staging.digital-office.co.il`), not just to subdomains.
*Proof*: a fixture whose host does not resolve fails the render with the exact record, and the gate
`reconcile` runs keeps it failing.

**P5 — platform blindness + staleness.** One rail banner when the engine/vault is unreadable (S9);
`data-stale` on every stored verdict (S5); `console /healthz` stops lying (it must be able to fail).

**P6 — the machine's story.** Fold `computers`' classifier (the best hop-naming in the platform,
`app.py:459-490`) into the office surfaces: a linked office whose *machine* is unreachable must say
so with the classified cause and its `action`, not `הקישור לא ענה`.

**P7 — contract hygiene.** `bbox dgo` and the link verbs appear in `bbox help`; `apps/dgo-extend/
AGENT.md` is rewritten off the retired `placement` model onto `remote:` (it is what every session
loads as its brief); `state_error` becomes a cause class + a details string; `next_actions` is part
of `/api/link` so every consumer offers the same verb.

---

## 8. Acceptance (how each phase is judged)

1. **Fault injection is the test.** Each phase carries a fixture that breaks exactly one hop
   (tunnel down, catalog silent, door dead, cert wrong, container down, SSO not completed) and an
   assertion that the surface names **that** hop and offers **its** action. A status surface tested
   only in the healthy state is untested (S11).
2. **No silent frame.** With any hop broken, the framed app area is never the browser's own
   placeholder: it is a Hebrew card with the office, the hop, the age and an action.
3. **No raw strings.** A grep gate over the owner-facing strings for
   `HTTP [0-9]{3}|Failed to fetch|TypeError|Error|Exception|port=|:[0-9]{4}` inside `static/` files
   returns zero (details folds excepted).
4. **One vocabulary.** `CHIP_HE`'s four words are the only status words in the shell; a new word in
   a screen fails the gate.
5. **Truth after recovery.** Break a hop, watch the surface go red, repair it, and watch the surface
   go green **without a page reload** (this is where `REMOTE_DOWN`'s `add`-only set fails today).
6. **The three environments.** The same surfaces are asserted on the local stack
   (`macbook`/`.localhost`) and on a real domain (`vps1`) — the nested-host and DNS differences are
   exactly where the current silent failure lives.

---

## 9. Decisions for the owner

1. **Repair — done, 2026-10-04.** `./bbox dgo link up vps1` failed first (correctly, with the ping
   message), then succeeded after the listen-port fix (§1.4). The link is `up`, all three delivery
   ports answer from the far machine, and vps1 fetches this office's agent through the door (200).
   Still open, and needing an owner decision: **hp-laptop is `unknown`** (its machine refuses SSH on
   `192.168.16.104:2222`, so it has never pulled a catalog). Its tunnel will also need re-converging
   to learn any new port when it returns.
2. **Endpoint as a name or an IP?** Today the declaration holds a name that does not resolve.
   Recommend: store the IP, keep the name as documentation, and refuse to publish a name that does
   not resolve (§1.2).
3. **Is 51830 permanent?** The port change is a workaround for a path condition (a blackholed flow),
   not a diagnosis of the network. If it recurs on 51830, the next move is to test a third port and
   then to look at the home router/ISP with the *same* evidence recipe (§1.4) — and P3's link screen
   is what should tell you first.
4. **Version skew inside the docs.** `ai/context/dgo-remote-apps.md` is the model; the
   `network`-app federation design (`degraded`/`offline`/`authentik-fleet`/`dow0`) is unbuilt but
   cited in the present tense, and `apps/dgo-extend/AGENT.md` still teaches `placement`. Recommend
   adopting the *vocabulary* of §5.4 now and marking those docs as design-only.
