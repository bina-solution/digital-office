# client-move — a client's own office on its own server, and everything of the client's moved into it

First client: **Examplex** (DGO-1924). The precedent it copies is Exampleu's office (DGO-1469…1495, 1636, 1685, 1873);
what went wrong there is fixed here, not repeated. Everything below is run by an agent through the office's own
doors (`./bbox computers exec|transfer`, the apps' APIs). The owner's hand is needed for exactly three things,
each one line on a «בעלים» item: the server in a live office's «מחשבים» (DGO-1925), his own password at the new
office's claim link, and the go for the live switch (the cutover).

| tool | what it moves | runs in | identity that makes a re-run change nothing |
|---|---|---|---|
| `plane_move.py` | Plane projects whole (`EXX`, numbers kept) or chosen items (`MEET:30,31,32`, `DGO:…=BINA`): items, states, labels, modules, comments, files, relations | the office's `project-pln` container | the item's own `(external_source, external_id)` — plan.py's `dgo-plan` key, meet's `meet-recording` key — else `(dgo-move, <ID>-<n>)`; comments `(dgo-move, <source id>)`; files name+size |
| `drive_move.py` | a folder of «קבצים» | the office's `drive` container | path + size, `mode=exclusive` (never «name (2)», never a replace); verify by sha256 |
| `meet_move.py` | recorded meetings: `recordings/<uuid>/` whole (mp4, ogg, json, flow/ page) | a helper with both volumes | path + sha256; a different file refuses the whole run |
| the app's own `hooks/backup` · `hooks/restore` (mac-dgo 748a665) | Examplex's store (`examplex.db` + files) | as the hooks run: `bbox export|import --app examplex` | the restore replaces the store whole, keeps the replaced one, and checks itself against the archive's facts |
| `client_repo.py` | the client-apps repo's commit: `apps/examplex` (held out of the public copy) + `context/` (its research) | a scratch git dir that has the line | fixed author and date: the same line is the same commit |

## Rehearsal — 2026-11-17, on throwaway targets (the proof)

- **Plane:** the HP's EXX, Examplex's MEET-30/31/32 and the 20 Examplex-only DGO items → scratch projects XTRT, MEETT, BINAT
  on the HP's Plane (archived afterwards). Run 1: 389 created, 0 problems, XTRT-n = EXX-n for all 94; run 2: 0 writes.
  The source then grew (EXX-95…120; four files and a comment on MEET-32): 60 created, numbers equal 120/120, 0 problems;
  again: 0 writes. Two items whose labels changed at the source were KEPT as the target had them and counted
  («differs» 2); `verify` named exactly those two; `--update` changed exactly 2; `verify`: 143 items, 0 differences.
  An import killed mid-run (the office recreated project-pln) is simply run again.
- **Store:** a consistent copy of vps1's live store (the hook's own code: SQLite online backup + files tar, read only)
  → the real `hooks/restore` into a scratch container `examplex-exx1924` (no network). Facts 12/12 identical (586 orgs, 78
  products, 553 links, 4 orders, 9 accounts, 23 files); Examplex served it (healthz 200, home 200). Run 2, with Examplex
  running: stopped it, kept the replaced store, swapped, started it — facts identical again.
- **Meetings:** exx101/102/104 (61 files, 754 MB) staged on vps1 by hard links (no extra disk), carried by the computers
  app's resumable `transfer` (verified), placed into a scratch recordings volume (61 created; then 61 kept, twice),
  61/61 sha256 equal to vps1's, owned by meet's user, 49 page links rewritten and none left to the HP's Plane.
- **Drive:** the HP's /Examplex (15 files) → a scratch folder (15 created; then 15 kept, twice), sha256 verified.
- **client-apps repo:** `client_repo.py` gives the same commit for the same line (91890d8 at mac-dgo bdad6ed): `apps/examplex`
  = the line's tree + 3 counted redactions, `context/` = 16 research files (EXF's design map left out). «0 names left»
  was true only for the first RX: it was case-sensitive and knew no app names (see the findings). What Examplex's office
  has is 95e9c5c, cut from dgo-stable 13020603b with today's RX: 11 redactions in apps/examplex, 6 in context/.
- **Second reader** (a fresh session, the code only): 1 blocker and 8 should-fixes, all fixed before the runs above.
- **Gates** on a probe commit: G10 caught Hebrew output without UTF-8 (fixed; 690 scripts pass); G5, G9, G31, G34,
  heredoc pass; G60 and the rest that fail fail the same without these files.

## Install and link — the runbook

`X` is the server's computer id in the HP's «מחשבים» (`./bbox computers ssh list`), `IP` its address. Every command on
the server is `./bbox computers exec $X --timeout N -- '<cmd>'` from the HP (root there; never a hand SSH).

0. **Owner (DGO-1925):** the server is added to the HP's «מחשבים» and the HP's office key is in its `authorized_keys`
   (or the Mac, when up, shares it to the HP: computers `shares`). Proof: `computers exec $X -- 'id; uname -a'`.
   Done 2026-11-17 the second way: the owner had added it on the Mac only; the Mac shared it (POST
   `/api/computers/<its id>/shares {"to":"hp-laptop","public_key":<the HP's ./bbox computers share key>}`, run in the
   Mac's computers container by `computers exec computer_local-local.macbook` — the same as `./bbox computers share
   <its id> "<key>" hp-laptop` in the Mac's checkout), which tags the HP's key in the server's
   `authorized_keys` (`computers-share:<sid>:hp-laptop`, revoked from the Mac). The share's door names the Mac's own
   host (`computers.localhost`), so the HP adds the server by ADDRESS with its own key — `./bbox computers add <IP>
   --user root --label "…"` — and does not depend on the Mac afterwards.
1. **Readiness:** OS, CPU, RAM, disk, ports 80/443 free, docker (none yet is fine). Exampleu's server: Debian 13, 4 vCPU,
   15 GB, 197 GB. Say it on the item.
2. **DNS of the office** (our zone, no client name at stake): `examplex` and `*.examplex` A → IP with the Internic tool
   (`./bbox domain-internic add-record`, as DGO-1476 did for Exampleu). Wait until `dns.google` answers IP.
3. **Install** — the public one-liner, which is exactly the public README's steps:
   `curl -fsSL https://digital-office.co.il/install.sh | DGO_BUSINESS_NAME=Examplex bash` (folder `~/digital-office`, the
   public `main`). Before `bbox run` finishes, put the office on the core (a fresh VPS starts from the full default set
   and skips the wizard — issues/a-fresh-vps-office-starts-from-the-full-default…). Then `.env`, by `env_set` (lib.sh),
   never by hand. As run for Examplex (the server's `/root/dgo-install-examplex.sh`): `apt-get install -y git` (a fresh
   Debian has none, and install.sh stops on it), clone the public repository to `/root/digital-office`, copy
   `platform.state.core.yaml` to `platform.state.yaml`, `./debian-install.sh`, the `env_set` lines below, `./bbox run`
   — 13 core containers in ~3 minutes:
   - `DGO_BRANCH=main` `DGO_FOLLOW=main` (takes each public release by itself; nothing committed on the server — the
     Exampleu drift, DGO-1577, is what that rule prevents)
   - `DGO_LINK_HOST=link.examplex.digital-office.co.il` — the office's link door. It is not in `.env.ex`, and Exampleu's
     was set by hand on its server with no record (DGO-1685): here it is written, and `https://link.examplex…` must
     answer with a valid certificate before any office asks to join
   - `DGO_CLIENT_APPS_REPO=/root/examplex-apps.git` `DGO_CLIENT_APPS_REF=apps` (below)
   - `BINA_CLAUDE_DESKTOP_PUID=0` `BINA_CLAUDE_DESKTOP_PGID=0` when the checkout is root's (DGO-1684)
   - `PLANE_OWNER_EMAIL=<the owner's address>` before Plane is enabled: a fresh `.env` leaves it empty, Plane's
     onboard then falls back to `N8N_OWNER_EMAIL`, a placeholder on a fresh office, and refuses (no workspace, no key — meet logs 401s); after
     it, `./bbox project-pln onboard` (the password is minted into `.env` and the vault, never printed)
   - nothing of `EXAMPLEX_*` yet: the product's own domain moves only at the cutover.
4. **Claim — owner:** the one-time link is the install log's `setup?code=` line (Examplex: `/root/dgo-install.log`;
   up to 0.3.1 the line prints `${COMPANY_SLUG}.${COMPANY_BASE_DOMAIN}` unexpanded — it is
   `signin.examplex.digital-office.co.il`; fixed by DGO-1970). It
   is never written on an item: Claude gives it to the owner in chat. He sets his own password. Examplex's apps were
   enabled before the claim (`apps enable project-pln drive meet examplex`, so the move could run), which skips the
   wizard — Itzik asked for the apps in the meeting of 2026-11-17 (bs110, MEET-35). Itzik is invited from the office's people screen (his own password,
   by his own link). Owner item: DGO-1966.
5. **Examplex's app:** the private apps repository lives ON the client's server — a bare repo `/root/examplex-apps.git`,
   branch `apps`, whose every commit is cut from the line by `client_repo.py`, never edited:
   ```bash
   python3 scripts/client-move/client_repo.py --git <scratch repo with the line> --line dgo-stable --app examplex \
     --context "research_notes/Examplex v1 2026-11-12" \
     --exclude "research_notes/Examplex v1 2026-11-12/05-exf-services-design-map.md" --redact "$RX" \
     ${PREV:+--parent $PREV} --ref refs/heads/examplex-apps
   git -C <scratch> bundle create examplex-apps.bundle refs/heads/examplex-apps
   # on the server: git init --bare /root/examplex-apps.git; git -C /root/examplex-apps.git fetch <bundle> examplex-apps:refs/heads/apps
   ```
   then `./bbox client-apps pull` there, and examplex is enabled from the apps screen. No GitHub repository, no deploy key,
   nothing pushed anywhere (Exampleu's push waited on the owner, DGO-1824). Updates: the same, with `PREV` = the repo's
   `apps`. Its `apps/examplex` is the line's tree except the counted redactions (11 at dgo-stable 13020603b: EXF's
   services app, named as the design's reference — `product.json`, comments, one requirement; the line keeps them,
   the company's design check reads `reference_app`). Its repository is today ONE commit, 95e9c5c (see the findings).
6. **Link — one way (DGO-1840):** `apps/computers/herd.yaml` → `clients.examplex: {herd: Examplex, door:
   https://link.examplex.digital-office.co.il, pin: <`./bbox dgo identity fingerprint` there, the same as its «DGO Extend» screen>, by: [hp-laptop,
   macbook]}`, committed on the office's branch. Each office in `by` asks to join by itself; the owner approves once on
   Examplex's `#/m/dgo-extend`, checking the HP's fingerprint 3A4B-3343-4492-5A1A (until DGO-1877 makes a declared join
   need no click). Examplex sees nothing of ours (clients.withheld).
7. **The display map — the install's last step, every time** (the owner, 2026-11-18: «תמיד כשאני אומר לך להתקין
   לשכה חדשה אתה חייב לסיים עם מפת תצוגה מלאה של אותה לשכה … צילום מסך של כל האפלקציות בלשכה ודף הראשי כדי להמנע
   מבאגים כאלה ובעיות תצוגה וסטנדרטים נמוכים עוד לפני שאני רואה את זה»). Signed in as the office's owner, take a shot
   of the console's main page and of every tile the office runs, at the desktop and the phone profile
   (`scripts/ui-coverage/view-profiles.yaml`). Read each shot, and fix what is wrong before the office is called up:
   a sign-in asked twice, a blank or broken screen, a wrong name. Then put the shots on the install's item. Examplex's first
   day missed this: «ניהול פרויקטים» showed Plane's own sign-in to the /setup owner (DGO-1982), and the owner found it
   on his phone.
8. **The move (data)** — below, in this order.
9. **Cutover** — below; the owner's yes.

## The move

Order: Plane first (MEET items must exist before their recordings land, or the target's meet transcribes them again),
then Drive and meetings, the store last (at the cutover). Every step twice; the second run must report nothing new.

**Plane** — export on the HP (its database, read only: the API's requests a minute per key are the whole office's):
```bash
S=EXX\ MEET:30,31,32\ DGO:1827-1834,1836,1837,1844,1864,1897-1902,1906,1907=BINA
# other clients — their names AND their apps' names, in any case (the same RX for client_repo, plane_move, meet_move)
RX='(?i)דוגמה|exampleu|EXU-[0-9]+|exf(-[0-9]+)?|examplef( guys)?|examplech|פיירפלייס|קמינים|ארובות|הסתדרות'
python3 scripts/client-move/plane_move.py snapshot-sql $S | docker exec -i plane-db-hp sh -c 'psql -U "${POSTGRES_USER:-plane}" -d "${POSTGRES_DB:-plane}" -At' > snap.json
docker exec project-pln-hp mkdir -p /tmp/dgo-move && docker cp scripts/client-move/plane_move.py project-pln-hp:/tmp/dgo-move/
docker exec -i -e PLANE_MOVE_PACE=2 project-pln-hp python3 /tmp/dgo-move/plane_move.py export $S --redact "$RX" < snap.json > plane.json
```
import there, in `project-pln-<DN>` (`PLANE_MOVE_PACE` default 1.1 s; on a shared office 2). An item already there
that differs is kept and counted as `differs` (people may have worked on it); `--update` takes the source's, and is
for the days before the cutover only:
```bash
W='--rewrite https://console.staging.digital-office.co.il/a/meet/=https://console.examplex.digital-office.co.il/a/meet/
   --rewrite https://console.staging.digital-office.co.il/#/m/plane.hp-laptop/bina/=https://console.examplex.digital-office.co.il/#/m/project-pln/bina/
   --rewrite https://console.staging.digital-office.co.il/#/m/project-pln/bina/=https://console.examplex.digital-office.co.il/#/m/project-pln/bina/'
python3 plane_move.py import plane.json $W        # then the same again: «created 0»
python3 plane_move.py verify plane.json $W        # VERIFY … "diffs": 0
```
A rehearsal is the same with `--as EXX=XTRT --as MEET=MEETT --as BINA=BINAT` on any office.

**Drive** — `docker exec -i drive-hp python3 -I - export /Examplex < drive_move.py > examplex-drive.tar`; there the script
goes into the container first (stdin carries the bundle): `docker exec drive-<DN> mkdir -p /tmp/dgo-move && docker cp
drive_move.py drive-<DN>:/tmp/dgo-move/`, then `docker exec -i drive-<DN> python3 -I /tmp/dgo-move/drive_move.py import
/Examplex < examplex-drive.tar` (twice: «kept 15»), and `verify /Examplex` (size and sha256 of every file).

**Meetings** — on vps1, stage by hard links (no disk), manifest, carry, place:
```bash
docker volume create exx_meet; SRC=/var/lib/docker/volumes/digital-office_meet_recordings/_data/recordings
DST=$(docker volume inspect exx_meet -f '{{.Mountpoint}}')/recordings; mkdir -p $DST
for u in aa5b2c0e-0173-40ab-a19b-7a7f60889653 a1b0ca12-5365-4536-8fe4-e29a0c965574 21de5fda-33ed-453a-b167-0824469be56c; do cp -al $SRC/$u $DST/$u; done
docker run --rm -i --network none -v exx_meet:/staged python:3.12-slim python3 - manifest /staged < meet_move.py
./bbox computers transfer computer_ssh-df3d4270 $X exx_meet           # from the HP; resumable, verified
# on the server, AFTER the Plane import; pairs.txt is one OLD=NEW a line (below), in order:
ARGS=(); while IFS= read -r l || [ -n "$l" ]; do [ -n "$l" ] && ARGS+=(--rewrite "$l"); done < pairs.txt
docker run --rm -i --network none -v exx_meet:/staged:ro -v <project>_meet_recordings:/rec -v "$PWD":/t:ro \
  python:3.12-slim python3 /t/meet_move.py place /staged /rec "${ARGS[@]}" --redact "$RX"
… verify /staged /rec "${ARGS[@]}" --redact "$RX"
```
**The pairs** (Examplex's: 335, kept beside the bundle): the pages link the source's items by key (`…/browse/DGO-1902/`)
and by id (`…/projects/<project id>/issues/<item id>`), on two console prefixes (`plane.hp-laptop`, `project-pln`). A
host prefix alone leaves both broken where the key or the id is not the target's, so first, for every moved item, its
two id links and (where the key changes: DGO→BINA, MEET-30→MEET-1) its two key links → `…examplex…/browse/<its key
there>/`, made from the import's `map` and the source database's ids; then the three prefix pairs (`$W`). Proof: no
`console.staging`, `plane.hp-laptop`, source project id or `/browse/DGO-` left in the two flow files.

The two `flow/` files (`data.js`: the page's title, summary, topics, tasks and transcript; `flow.json`: its record —
title, who, tags, docs) are the only files changed, by the pairs and by `--redact`, as the Plane step does to the
meeting's item. The recording itself (mp4, ogg) is the meeting, and the client was in it. A page placed before a fix
is removed first (`place` never overwrites), then placed again from a staging of those files alone.

**Prove it after every move** — no other client anywhere on the client's office (each count must be 0):
```bash
P='דוגמה|exampleu|EXU-[0-9]+|exf|examplef|examplech|פיירפלייס|קמינים|ארובות|הסתדרות'   # the RX's names, for grep -i
git -C /root/examplex-apps.git log -p --all | grep -ciE "$P"                 # the apps repository, its whole history
grep -rliE "$P" ~/digital-office/apps/examplex "<the meet recordings volume>/recordings" --include=*.js \
  --include=*.json --include=*.html --include=*.txt --include=*.py --include=*.md | wc -l
# Plane: every item's name and description, every comment, file name, module and project, matched with ~* "$P"
```

## Cutover — Examplex's live service moves (the owner's yes; nothing of it before)

Today Examplex serves from vps1 (`examplex-staging`, `app.examplex.co.il`, `examplex.co.il`, `www` → 93.184.216.5; TTL 1 h app,
6 h apex/www; DNS at Internic/sitesdepot).

- **T-1 day:** TTL of `@`, `app`, `www` to 300 s (traffic unchanged). Rehearse the store once more on the new server
  itself: export on vps1 → restore into the new office's examplex → facts equal → the new office's examplex answers
  `https://examplex.examplex.digital-office.co.il/healthz`.
- **T0, at night (≈ 15 min):**
  1. freeze: `docker stop examplex-staging` on vps1 — from here no order is written anywhere;
  2. export on vps1: `bbox export --app examplex` (when vps1 has taken a line with 748a665), else the same hook code run by
     hand exactly as rehearsed (examplex_volume.py `copy` + examplex_facts.py, in helpers of examplex-staging's image);
  3. carry (≈ 10 MB) and `hooks/restore <dir> full` on the new office; facts must equal the export's — else stop and
     roll back (vps1 is untouched);
  4. the new office's `.env`: `EXAMPLEX_APP_BASE_URL=app.examplex.co.il` (the site and apex follow the app's defaults),
     `./bbox run` — its routers now answer for Examplex's names;
  5. Internic: A `@`, `app` → IP (`www` is a CNAME to `@`); wait until `dns.google` answers IP; certificates are issued
     on the new office (restart its traefik once if ACME gave up before DNS answered, c5b403c8);
  6. proof: `https://app.examplex.co.il/healthz` 200 from outside, a sign-in, a supplier's catalog, the counts of the facts;
     Itzik and the owner sign in.
  7. vps1: `examplex-staging` stays STOPPED, its volume kept 14 days (nothing is uninstalled).
- **Rollback (any step fails, or the owner says so):** Internic back to 93.184.216.5; if orders were taken on the new
  office, its store comes back by the same two hooks (export there → restore on vps1); `docker start examplex-staging`.
  Window ≤ 5 min with TTL 300.

## What the rehearsal found (so nobody finds it again)

- **Plane's API limits requests a minute per KEY, and an office's agents share its key:** while the limit was
  upstream's 60, an export through the API (one GET per comment list, file list and relation list) held the whole
  office at 429 for minutes (it is 300 on our offices since 5c9ee7fd0, PLANE_API_KEY_RATE_LIMIT). Export reads the
  database (one query); the API is paced, reads included (`PLANE_MOVE_PACE`).
- Plane refuses: a project name with marks (· ( ) — HTTP 400); a second triage state (every project has its own);
  a module on a project whose module view is off (a new project's is). The tool handles all three.
- **From inside the office's Claude app container, a bind mount of a SUB-path of the checkout reaches a different, empty
  folder on the engine** (only the checkout root is shared): a hook's `-v <dir>:/x` from there sees nothing. Run hooks
  from the machine (`computers exec local`) or, as the rehearsal did, in a helper whose paths are the engine's own
  (a scratch volume mounted at its `/var/lib/docker/volumes/<v>/_data`).
- vps1 runs vps1-dgo, which has no `apps/examplex/hooks/backup`: until it takes the line, a `bbox export` there would tar
  the live database. The cutover's step 2 says what to run instead.
- The meeting pages (flow/data.js, flow/flow.json) and the MEET items link to vps1's console and the HP's Plane: the
  `--rewrite` pairs (per item first, then the host prefixes — «The pairs» above).

## What the real install found (Examplex, 2026-11-17)

- **Never ask a public resolver for a name before it exists.** An early `dns.google` probe of `examplex…` cached NXDOMAIN
  there for the zone's SOA minimum (3 h); Cloudflare and the server answered the new record at once, and Let's
  Encrypt (its own resolvers) issued every certificate on the first `bbox run`.
- The InterNIC app (on the Mac) loses its portal session when the Mac restarts: `./bbox domain-internic status` says
  `needs_human_login`; `./bbox domain-internic login` signs in by itself once (never loop it).
- `computers exec` carries at most 1 MiB of stdin: the apps bundle and the move files go to the server as a volume
  (`computers transfer local $X <volume>`), not inline.
- Public 0.3.1's `client-apps.sh` needs `rsync` (a fresh Debian has none) and places no `context/` — both fixed on the
  line (327a062fd, f30a8ab40); the client's documents arrive with the next public release (the office follows `main`).
- The office branch guard refuses `git update-ref` typed in a command, even in a scratch repository: give
  `client_repo.py` the line as a commit id (`--line $(git rev-parse origin/dgo-stable)`). The message names what
  `--line` was given, so the same commit id gives the same commit, but not the commit that a ref name gives.
- A watcher that runs `pgrep -f "bbox run"` through `computers exec` matches its own command line: wait on the log's
  last line instead.
- **The first RX let another client through.** It matched `EXF` only in capitals and knew no app names, so Examplex's
  repository got EXF's services app by name (`examplech-services`, 8 lines) and one lowercase `exf`, and exx102's meeting
  page kept a spoken «example shop». Plane was clean. Found by the case-insensitive scan above; fixed the same
  night: the RX above, Examplex's repository rebuilt as ONE commit cut with it (95e9c5c — a commit on top would have
  kept the old text in its history; the side clone removed too), the page re-placed with `--redact`. On the line,
  `product.json`'s `reference_app` keeps naming the app: the company's design check (kadima) reads it, so the
  boundary is where the name stops.
- **The meeting pages kept nine links to the HP** (by id, and `DGO-1902`), and `flow/flow.json` was not rewritten at
  all: the host pairs alone cannot map an item whose key or id differs there. Fixed the same night by the generated
  pairs above, both flow files rewritten (all six re-placed; 0 links left to vps1 or the HP).
