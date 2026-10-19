# The second office (DGO-35) — how the Mac's heavy apps get off the Mac

> **Superseded for hp-laptop (2026-10-04).** That office did not join this way. It was installed
> by its own owner and **paired** from the pairing screen (`/connect`, 2026-10-04 23:56): it runs
> **no SSH server**, by its owner's ruling, and nothing on the Mac installs, converges or reaches
> its machine. Do **not** set up `sshd` on it from this document. What follows is the record of the
> DECLARED route — an office this one installs over SSH — which is still how vps1 is run, and is
> kept for a machine that is meant to be run that way. The current picture is in
> [README.md](README.md); the model is in [dgo-remote-apps.md](../../ai/context/dgo-remote-apps.md).

Owner's goal (2026-10-01): the MacBook is the bottleneck (A18 Pro, 2 fast cores, 8 GB, on battery —
load averaged 100–160). A second machine becomes **a full office linked to the Mac**; the heavy apps
are **installed and run there**, and appear at the Mac as **remote apps** — the model and the whole
data path are in [dgo-remote-apps.md](../../ai/context/dgo-remote-apps.md). There is no "placement":
an app runs where it runs.

**The destination changed during the work (2026-10-01 18:05).** The first target was the portable
machine on the LAN (`192.168.16.103`, ~15 GB, Docker 29) — it was registered as
`computer_ssh-2a63fd64` and nothing was ever installed on it; it has since been **removed from the
fleet**. The destination is now **hp-laptop**: a Windows machine running **WSL Ubuntu** at
`192.168.16.104` (`DESKTOP-DTFB8I4.local`), SSH on **port 2222**, registered in `computers` as
**`computer_ssh-60477c6a`** (user `shlomo`).

State as of 2026-10-01 19:00: the entry exists and the LAN reaches the machine, but **sshd is not up
yet** (`Connection refused` on 2222) — the owner is installing `openssh-server` in WSL, enabling
mirrored networking and opening the firewall rule. Nothing below has been executed against it.

## 0. The door, and the two WSL-specific things that decide whether it works

```bash
# INSIDE WSL, as root (`wsl -d Ubuntu -u root`), ONCE. Ubuntu is Debian-family, so this is the same
# script the other offices use: sshd up + the office key + the prerequisites the converge needs.
KEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI… office-key@local'   # הרחבת הלשכה → חיבור לשכה
bash office-setup.sh --key "$KEY" --port 2222

# facts only (the "before" half of the proof), changes nothing:
bash office-setup.sh --check
```

`office-setup.sh` owns exactly the door: sshd enabled and started, the office's Ed25519 key in the
SSH user's `authorized_keys`, `Port 2222`, and the Debian-family prerequisites (`git`, `curl`,
`ca-certificates`, `jq`). It does **not** install Docker (the converge's `engine` step pins 28.5.2
through `debian-install.sh`), does **not** clone the checkout (`code` does), and does **not** disable
password login unless asked (`--harden`). Its `--check` also prints the three facts that decide
whether a WSL machine can host an office at all — `WSL=`, `SYSTEMD=` and `PATH_FS[...]`:

* **systemd must be on** (`/etc/wsl.conf` → `[boot] systemd=true`). Docker CE is a systemd service
  here, and the project's own engine is the one that runs the stack
  ([running-on-wsl.md](../../ai/context/running-on-wsl.md)); a distro without systemd cannot start it.
* **the checkout must be on the distro's ext4** (`/home/shlomo/…` or `/opt/…`), never `/mnt/c`: 9p
  reports every file as 777, `chmod` is a silent no-op, and `acme.json`'s required `600` becomes
  impossible — traefik then falls back to a self-signed certificate with no error anywhere.
* **mirrored networking** is what makes the WSL distro reachable at the LAN address and what lets it
  reach the Mac; without it the address the fleet dials belongs to Windows, not to the office.

**The SSH user must be root-equivalent, and that is a decision, not a detail.** `computers` runs
`ssh <user>@<host> <command>` — no `sudo`, no login shell, no wrapper (`apps/computers/app.py`,
`ssh_run`). A converge run as a non-root user cannot `apt-get install` (the engine step), cannot
write `/opt`, and cannot talk to the Docker socket. On WSL the project's own path is root
(`bbox.cmd run` ≡ `wsl -d Ubuntu -u root -- bash -lc …`), so the office should be declared with
**user `root`** — which means the same key in root's `authorized_keys`:

```bash
# inside WSL, as root
install -d -m 700 /root/.ssh && chmod 600 /root/.ssh/authorized_keys 2>/dev/null
grep -qF '<the key's base64 blob>' /root/.ssh/authorized_keys || echo "$KEY" >> /root/.ssh/authorized_keys
printf 'PermitRootLogin prohibit-password\nPubkeyAuthentication yes\n' \
  > /etc/ssh/sshd_config.d/10-digital-office.conf && systemctl restart ssh
```

Then the fleet entry is re-pointed at `root` (delete + re-create is the only shape the API has today,
and it costs nothing: no data is attached to a machine row):

```bash
curl -s -X DELETE http://computers:8977/api/computers/computer_ssh-60477c6a
curl -s -X POST   http://computers:8977/api/computers -H 'content-type: application/json' \
     -d '{"host":"192.168.16.104","port":2222,"user":"root","label":"hp-laptop","account_hint":"192.168.16.104:2222"}'
```

Verify from here, through the only door the office has to a machine:

```bash
curl -s -X POST http://computers:8977/api/computers/<id>/exec \
     -H 'content-type: application/json' -d '{"command":"hostname; nproc; free -m; df -h /","timeout":30}'
```

## 1. Declare the office and converge

The declaration is **live** (created 2026-10-01 through `POST /api/office`; read it back with
`GET /api/office/hp-laptop`):

```json
{
  "id": "hp-laptop",
  "label": "hp-laptop (WSL)",
  "machine": "computer_ssh-60477c6a",
  "domain": "hp.localhost",
  "path": "/opt/digital-office/hp-laptop",
  "engine": { "replace_docker": true },
  "source": {
    "repo": "https://github.com/solomonBoltin/deployment-hacohen.git",
    "branch": "dgo",
    "commit": "3363d802c10bb5ba114f1d6127ed0b8978fcab6b",
    "account": "git_github_token-1d2d52f4"
  },
  "apps": {
    "traefik": "enabled", "postgres": "enabled", "redis": "enabled", "authentik": "enabled",
    "connections": "enabled", "console": "enabled", "app-management": "enabled",
    "notifications": "enabled", "any-concurrency": "enabled", "machine": "enabled",
    "bina-ui": "enabled", "dgo-extend": "enabled",
    "browser42": "enabled"
  },
  "links": [{ "office": "local", "direction": "serve" }],
  "tunnel": { "slot": 3, "endpoint": "192.168.16.104", "dial": "peer", "relay_for": [] }
}
```

`tunnel.slot` is the office's **pair /24** (`10.79.<slot>.0/24`), one per linked pair: `net.py` refuses
rather than defaults when it is missing, because "two offices that silently share a slot are two
offices whose packets arrive at the wrong interface". The first draft of this declaration carried
`slot: 2` — the vps1 pair's slot. It is `3`, checked against `GET /api/office` (vps1 → 2,
hp-laptop → 3).

`browser42` is the only app of the owner's heavy list enabled here so far, deliberately: it is QA-only
(nothing depends on it at runtime), so proving it from the Mac proves the whole catalog → projection →
route → alias chain before anything with state moves. Each further app is one
`POST /api/office/hp-laptop` (or the screen) plus a converge.

### The domain decision (owner, 2026-10-01 19:20): `localhost` — written as `hp.localhost`

hp is a **LAN office**: its apps are served to the Mac over the link and appear on the *Mac's* edge
(`<alias>.hp-laptop.console.localhost:8080`), so nothing needs to resolve to 192.168.16.104 and no
certificate has to exist for it. hp's own console is `console.hp.localhost` — on the laptop itself.

`localhost` on its own is **rejected by the manifest validator**:
`DOMAIN_RE = ^([a-z0-9](…)?\.)+[a-z]{2,}$` requires at least one dot and a TLD of two or more letters
(`localhost` has neither). `hp.localhost` is the smallest spelling that keeps the owner's meaning —
RFC 6761 guarantees `*.localhost` resolves to loopback, on hp and in a browser, with no DNS work at
all.

Two consequences, both measured rather than assumed:

* **the converge must skip `dns`** — `step_dns` demands that `console.<domain>`/`auth.<domain>` resolve
  to the machine's own IP, and `console.hp.localhost` resolves to loopback (that is the point). Run
  `steps=["machine","engine","code","env","state","run"]`; `health` afterwards may warn for the same
  reason, and its warnings are per-host and honest.
* **hp's `.env` will be https-flavoured** (`AUTH_PROTOCOL=https`, `admin@hp.localhost`): `ci-env.sh`
  treats any non-empty `OFFICE_DOMAIN` as a real office, and the converge always passes the
  declaration's domain. This is invisible to the Mac's use of hp's apps — they are reached through
  the tunnel, and the catalog carries the `host` each app expects (dgo-remote-apps.md §1), which is
  what the consuming edge rewrites.

### The remaining open decision

* **Docker version.** If the distro's engine is not 28.x, `engine.replace_docker: true` is what
  authorizes `debian-install.sh` to replace it: on 29, traefik v3.3 discovers **zero** routers while
  reporting healthy, and every host 404s (CLAUDE.md). The `engine` step's own report is the verdict.

## 2. Link the two offices

`bbox dgo link up` on the Mac, with the WSL side listening: the Mac is behind the house NAT and the
WSL distro has a stable LAN address in mirrored mode, so the peer dials (`tunnel.dial: peer`).
WireGuard UDP 51820 must reach 192.168.16.104 — in mirrored networking that is a Windows firewall
rule, which is the same place the 2222 rule lives. Acceptance: `wg show` on both sides and a ping
**both ways** across `10.79.x.x`.

Once the link is up, the Mac's `dgo-extend` pulls hp's **catalog** (`GET /api/link/catalog`,
tunnel-only, 403 from anywhere else) and projects it into `platform.state.yaml` as the `remote:`
block; layer 0 then emits the routes, the `<alias>.<office>` network aliases and the registry entries.
**Installing an app there is what makes it appear here** — there is no per-app wiring on the Mac.

## 3. What runs there, in what order, and what it costs

Two kinds of number, and they are not interchangeable:

* **measured** — the office's own runtime study, [packaging/OPTIMISATION.md](../../packaging/OPTIMISATION.md),
  taken 2026-07-29 against this exact container set (33 containers, whole estate **4.7 GB**, in almost
  exact thirds: layers 1–2 = 3.1 GB, layer 3 = 1.55 GB);
* **declared** — each app's own budget (`app.json` `resources`, or the compose limit where the app
  declares none). That is the ceiling to plan against, not what it uses today.

The Mac's live figures are one command away, and they are the before/after proof of the whole
exercise (`docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' | sort -k3 -h`).

**Owner's target list for hp** (2026-10-01 18:05) — all thirteen run THERE and appear at the Mac as
remote apps:

| # | App | Containers | Measured RAM | Declared ceiling | Data that must come with it |
|---|---|---|---|---|---|
| 1 | `browser42` — QA-only, so it is the app whose move costs the business nothing while the path is being proven | 5 | idle 0.7–1.0 GiB, peak 1456 MiB (2026-09-23) | `1792M`, cpus `${BROWSER42_CPUS:-6}`, MCP heap 512M | `cloakprofile` + `data/browser42` |
| 2 | `n8n` + `n8n-postgres` + runners (careful: `postgres_storage` is the SHARED database, not n8n's — see the move lane's §4) | 6 | **770 MB** | `2g` / 2 cpus | `n8n_storage`, `postgres_storage` — and **`N8N_ENCRYPTION_KEY` must exist there first**, or every credential in the imported workflows is undecryptable |
| 3 | `supabase` + `INDOX` (DGO-64) — the document pipeline | 5 + indox | layer 3 total 1.55 GB | `rest` 256M, `storage` 512M, **`kong` 768M** (on the document path — an OOM there stops the pipeline), `meta` 256M, `studio` 384M = **2176 MB** | `supabase_storage_data`, the `supabase-db` instance, INDOX's 92 workflows |
| 4 | `project-pln` (Plane — the office's task tool) | 4 + minio | — | `1536M` / 1.5 cpus | `project_pln_data/logs/db/redis/minio` |
| 5 | `git` (Forgejo + the proxy) | 2 | — | — | the forge's own volumes; mirrors are copies and can be re-synced |
| 6 | `my-docs`, `drive`, `mail`, `apitools`, `sites`, `telegram-tv`, `digital-assets`, `social-list` | 1–3 each | — | small (each app's own `resources`) | their own volumes — `drive`'s uploads and `mail`'s local store are the ones with real content |

**What stays on the Mac** (the owner's list): the agents (`bina-ds`) and the central control —
`console`, `app-management`, `connections`, `authentik`, `traefik`, `dgo-extend`, `computers`. Every
office keeps its **own** `authentik` (1132 MB measured — 24% of this estate, and the single largest
thing either machine runs); what the Mac stops paying is the thirteen apps above.

`n8n` is the one app that legitimately appears **twice** while the move is in progress (once local,
once `<alias>.hp-laptop` marked remote) — the model supports it deliberately, and the Mac's copy is
disabled only after hp's copy serves the same workflows.

**The transfer ORDER is not this document's to own.** The table above is the SIZING view (what each
app costs while it runs, so the destination can be judged); the order — with the measured size of
every app's volumes, the downtime per app, the round-trip proof that starts it, and the traps a
plausible-looking plan misses — is [`ai/context/moving-an-office.md`](../../ai/context/moving-an-office.md)
§4, owned by the move lane (DGO-37). That order differs from the first draft written here (which put
browser42 first because it is QA-only): it opens with a tiny app moved **and brought back** — the
cheapest proof that the whole path works in both directions — and makes `git` last, because `git` is
how a broken office is repaired. Defer to it; this document should not carry a second opinion.

## 4. Moving an app WITH its data (not a copy of the containers)

The mechanism is `move.py` (`preflight → backup → stop → transfer → enable → verify`): every declared
volume of the app is tarred **here** into `~/.digital-office/move-<app>-<ts>/`, the destination's room
is checked first, the bytes cross with `computers`' `/stream` op (resumable, verified, one transfer at
a time — this app never holds a credential for either machine), and the app is enabled there only
after its data is there, with a rollback that starts it here again if anything fails. The order in its
`STEPS` is the safety property: a crash midway leaves a stopped app at home with its data intact,
never two half-empty copies.

That path is the `move` lane's (DGO-37): the step-by-step, the exact preconditions and what each step's
output must show are in [moving-an-office.md](../../ai/context/moving-an-office.md) — `computers`
moves BYTES (`/stream`, resumable and verified), `dgo-extend` moves an APP (`/api/office/<oid>/move`),
and no key crosses between the machines. Treat the order in §3 as the queue that document is fed.

## 5. Finishing at the Mac

Per app, in the same order, and **only after** hp's copy answers:

1. prove the remote app from here — the tile marked with the office name, plus
   `curl -s http://<alias>.hp-laptop:<port>/healthz` from inside the engine (the `<alias>.<office>` alias);
2. `./bbox apps disable <id>` at home (the writer of `platform.state.yaml`);
3. `./scripts/dc up -d --remove-orphans`, then `uptime` and `docker stats` — the load dropping is the
   point of the whole exercise.

Disabling at home is what frees the Mac: the containers stop, the volumes stay
(`data.on_uninstall: keep`), which is also the rollback path.

## 6. What must be true before the first heavy app is disabled at home

* hp's converge is green and its link state is `up` in `GET /api/link`;
* the app appears on the Mac's rail with the remote mark and opens from the console;
* its data is there (for n8n: the workflows run on hp and their credentials decrypt);
* a backup of the app's volumes exists at home from the move itself, and `df -h /` at the Mac shows
  the room that was freed.

## 7. The gate: `bbox dgo test 2`

`apps/dgo-extend/tests/phase2.py` is this lane's acceptance, written as measurements rather than
verdicts — one check per clause of the sentence above:

| check | what it measures |
|---|---|
| a declared office answers the office key | the machine's own hostname / OS / cores / free RAM / free disk |
| Docker is **28.x** | the version that decides whether traefik routes at all |
| the declared commit is fetchable | a local commit cannot be deployed: the machine clones from the repository |
| an app enabled there appears here | `GET /api/link`: the office's state and its apps, with an office that does not answer named as such |
| the compiled alias resolves | `<alias>.<office>` resolved INSIDE the engine, which is how every agent and hook addresses a remote app |
| the tunnel is up | WireGuard peers with their handshakes |
| the office converged | the last run's status/commit/health for each declaration |
| the destination has room | `admission.py`'s arithmetic on the live machine record, with the numbers |

The remote-app chain itself (catalog → projection → registry → route) is phase 3's gate; this one owns
the machine, the engine and the link that the chain needs underneath it.

## 8. Left over from the first target

`git rm apps/dgo-extend/placement.py` — written for the "placement" model the owner replaced; dead
code now. `admission.py` stays (the gate uses it to measure a destination before installing).
