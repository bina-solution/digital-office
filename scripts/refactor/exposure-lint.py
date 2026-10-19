#!/usr/bin/env python3
"""exposure-lint — gate G84: nothing reaches a host interface the office's security session forbids.

    python3 scripts/refactor/exposure-lint.py             # the report; today's known red is named
    python3 scripts/refactor/exposure-lint.py --strict    # waivers ignored: every known red is a finding
    python3 scripts/refactor/exposure-lint.py --self-test

WHY THIS EXISTS. `ai/context/dgo-security-session.md` is the owner's own exported conversation
(6 October 2026, re-sent by him on 2026-10-09) and the standard this office's security layers are
measured against. The pentest behind `rap-009` measured what that standard costs today: 19 host
names served with 6 undeclared, `n8n.localhost` answering `200` with no sign-in, the engine socket
read-write in six containers, and traefik publishing `6379`/`15432` on `0.0.0.0` — Docker's own
documented firewall bypass (doc line 60-61), live on this host. Every one of those is a fact of a
COMPOSE FILE, and nothing in this directory read a compose file for it.

A live scan answers what is running NOW; this gate answers what the NEXT COMMIT will run, from the
tree alone — no network, no Docker daemon, no `.env`, ~1 s. Its DENOMINATOR is every compose file
this repo would put containers on a machine from, taken from git rather than from a hand-kept list
(rule 8 step 2: the file count, not just the finding count) — `git ls-files`-tracked `compose.yml`
and `docker-compose*.yml` under `apps/` (any depth), `platform-base/` (any depth) and
`ops/devops-vps/` (the GHA runner's own stack). Every app counts, enabled or not: a gallery app that
ships here is one `enabled: true` away from running, which is the same reason G15 pins its images.
`NOT_RUN_HERE` is the only thing outside that denominator, and it carries a reason per entry and an
anti-rot check of its own.

The `Dockerfile*` beside each build context is read for rule R4 only. `.generated/` is never read:
that is the renderer's output, it needs a `.env`, and it is a consequence of these files rather
than a source.

THE FOUR RULES, EACH WITH THE LINE IT COMES FROM. The doc is quoted, not paraphrased; where the
doc only RECOMMENDS a thing, the gate counts it instead of failing (rule R3, and R4's second half).

  R1  A PUBLISHED HOST PORT THAT IS NOT THE FRONT DOOR OR THE LOOPBACK.
      404-407  «One front door. Only a reverse proxy (Caddy or Traefik) publishes ports, and only
                80 and 443. No app container has a `ports:` line.»
      415      «If you must publish a port for debugging, bind it to `127.0.0.1:port` only.»
      64       «Don't publish the DB port; keep MySQL on an internal Docker network only.»
      44       «Exposed services … the MySQL port published to the internet in the compose file
                (ports: 3306:3306).»
      60-61    «Docker publishes ports by bypassing UFW firewall rules.» — a bare `8080:80` is on
                `0.0.0.0` whatever the host firewall says.
      Allowed: a publish bound to `127.0.0.1`/`::1` (the doc's own debugging form), and ports 80/443
      published by the app that DECLARES the `edge` capability (`platform-base/traefik/app.json`) —
      "only a reverse proxy publishes ports, and only 80 and 443" is one sentence, so both halves of
      it are checked. The host side of a `${VAR:-default}` publish is linted at its DEFAULT, which is
      what a clone with no `.env` runs — the same choice G15 makes for image tags.

  R2  AN ENGINE SOCKET MOUNTED READ-WRITE. A socket in a container is root on the host.
      53-56    «Container escape to the host … it becomes possible if you mount
                /var/run/docker.sock, run containers privileged, or mount host folders writable.»
      216-217  «Docker API. Never give any app the raw Docker socket. The socket proxy exposes only
                read-only calls to the tools that need them.»
      262      «…never use privileged, and never mount the Docker socket.»
      445      «…no privileged, no Docker socket mounts…»
      A mount whose source or target names `docker.sock` — `/var/run/docker.sock`,
      `${BBOX_DOCKER_SOCK:-…}` (the project's own socket, `/run/bbox-docker.sock` on the host), a
      literal `/run/bbox-docker.sock` — and whose mode is not `:ro` is a finding. `:ro` passes: the
      doc's own acceptable form is the socket proxy "exposes only read-only calls", and the five
      `:ro` mounts here say so. The mount string found is quoted, because "which socket" and
      "read-write or not" are two facts and only one of them is in the filename.

  R3  AN IMAGE NOT PINNED BY DIGEST (COUNTED, NOT ENFORCED — see below).
      81       «Pin image versions and update them regularly.»
      286-289  «Pin images by digest (image: x@sha256:...) and verify signatures with cosign, so an
                image can't be swapped under the same tag.»
      448      «Images. Pin images by digest and scan them (Trivy or Docker Scout).»
      The doc states digest pinning, and this gate still does NOT fail on it, for two measured
      reasons that belong in the open rather than in a silent exception: (1) G15
      (`image-pin-lint`) already owns "is every third-party image pinned at all"; (2) G15's own
      docstring (:38-52) records that digest pinning is in DIRECT TENSION with the offline bundle —
      `docker save`/`load` transfers RepoTags and not RepoDigests (moby#43570), so a compose file
      pinned by digest stops resolving after an airgap `docker load` — and says «DO NOT SWITCH THIS
      ON FOR THE SHIPPED COMPOSE FILES». So the count is printed every run, with the references, and
      the exit status does not depend on it. Flip it to a failure the day `--digests` becomes
      shippable, and only then.

  R4  PRIVILEGED, AND ROOT WHERE THE IMAGE DECLARED OTHERWISE. Two shapes, two strengths.
      55       «…if you mount /var/run/docker.sock, run containers privileged, or mount host folders
                writable.» (said again at 262 «never use privileged» and 444 «no privileged»)
      437      «5. Per-container hardening. This is the OWASP and CIS core: non-root user,
                read_only: true, cap_drop: ALL, no-new-privileges:true, resource limits, no
                privileged, no Docker socket mounts…»
      247-250  «Rootless Docker or userns-remap. Root inside a container then maps to an unprivileged
                user on the host, so a container escape lands as "nobody".»
      (a) ENFORCED — `privileged: true` on a service, and a container that runs as ROOT although the
          image it builds from declares a non-root `USER`: a compose `user:` naming root (`root`,
          `0`, `0:0`) throws away the Dockerfile's own decision, and nothing else can. Measured
          2026-10-09: the tree has NO `user:` key anywhere, so the second shape is a pure guard —
          which is the point, because the first `user: root` is otherwise invisible. The first shape
          has exactly one instance, and it is the one that shows why a justification is not a switch:
          `ops/devops-vps/gha-runner/docker-compose.yml` runs `docker:27-dind` privileged, because a
          Docker daemon inside a container cannot work without it — that one is in JUSTIFIED, with
          the reason, and it stays visible on every run. `privileged` is also justified in the doc's
          own words for sensors («it starts in a privileged container, which suits a compose
          setup», :354), which is why the reason is asked for rather than the word banned.
      (b) COUNTED — "non-root user" is the one item of :437 the doc states inside a checklist and
          nowhere with a "never": the sharp words are spent on privileged (:262) and the socket
          (:217, :262). So a first-party image whose Dockerfile declares no `USER`, or declares root
          — the container runs as uid 0 — is counted and printed, not failed. 39 services were
          measured that way on 2026-10-09; the live number is the report's, not this sentence's, and
          a count printed on every run is how it falls.

DELIBERATELY NOT GATED, each for a reason rather than an omission:

  * `network_mode: host` — the item that asked for this gate names it, and the doc does NOT: the
    string `network_mode` does not appear in `dgo-security-session.md` at all, and `host network` /
    "host's network" never in that sense. A rule invented here would be this gate's opinion wearing
    the doc's authority. The one use in the tree (`apps/dgo-extend/docker-compose.yml:195`,
    `network_mode: "service:dgo-net"`) is a container sharing another CONTAINER's namespace, not the
    host's, and the file says why.
  * `read_only: true`, `cap_drop: ALL`, `no-new-privileges`, seccomp/AppArmor profiles, resource
    limits and "secrets in files rather than environment variables" — all named by the doc (:212-213,
    :254-264, :437-446) and all OUTSIDE the four rules this gate was asked for. They are a sweep of
    their own (each needs its own denominator and its own rollout), and half of them are moot on a
    container that already runs as uid 0 — which is what R4(b) counts.
  * `cap_add` — the doc names capabilities only as something to DROP (:212, :437). The tree's one
    `cap_add` (`apps/dgo-extend`, NET_ADMIN/NET_RAW for a WireGuard interface) is reasoned in the
    file; a rule here would be about a mechanism the doc never discusses.
  * anything about a RUNNING office — which containers are actually up, which host names the edge
    serves, whether a socket is bound at this moment. Those are G61/G70's live lane and the pentest
    skill's job; this gate is the static half and says so.

ANTI-ROT (G31/G34/G50's rule, and G86's). Every entry in KNOWN_RED and JUSTIFIED is keyed
`<compose path>|<service>|<the exact string found>` and must still match a real finding: an entry
whose mount or publish was fixed, renamed or deleted FAILS as a stale declaration. That is how both
lists shrink themselves — a waiver is not a place a finding goes to be forgotten, and the fix of a
known red is a red CI run until the entry is deleted.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import posixpath
import re
import subprocess
import sys

try:
    import yaml
except ImportError:
    print("exposure-lint: pyyaml required (same dependency as image-pin-lint)", file=sys.stderr)
    raise SystemExit(2)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
TREES = ("apps", "platform-base")
DOC = "ai/context/dgo-security-session.md"

#: Images built by THIS repo, and therefore pinned by the commit rather than by a digest. The rule
#: is G15's, verbatim: a local tag, and the GHCR name CI pushes the same build to. Kept in step with
#: `image-pin-lint.py`'s FIRST_PARTY_* by hand, because the two answer different questions (G15:
#: "is it pinned at all"; here: "is it digest-pinned, and is a digest even the right question for
#: this reference").
FIRST_PARTY_PREFIXES = ("deployment-hacohen-", "binaos/", "incoming-documents-local", "my-docs-local",
                        "llm-gateway-local")
OFFICE_REGISTRY = "ghcr.io/solomonboltin/digital-office/"

#: The doc's line for each rule, printed beside it so a reader can check the quotation.
RULE_DOC = {
    "R1": f"{DOC}:404-407,415,64,44,60-61 — one front door (80/443), a debug port on 127.0.0.1 only",
    "R2": f"{DOC}:53-56,216-217,262,445 — never the raw Docker socket; the proxy is read-only calls",
    "R4": f"{DOC}:55,262,444 — never privileged; {DOC}:437,247-250 — non-root user",
}

#: A host side that IS the loopback: the doc's own debugging form (`bind it to 127.0.0.1:port only`).
LOOPBACK = {"127.0.0.1", "::1", "localhost"}

#: The ports the front door may publish, and only it (doc :404-407 "only 80 and 443").
FRONT_DOOR_PORTS = {"80", "443"}

#: Compose files that are NOT this office's stack, each with the reason, named rather than silently
#: skipped (rule 8 step 2). Anti-rot: an entry that is no longer a tracked file FAILS, so the list
#: cannot outlive the files it excuses.
NOT_RUN_HERE: dict[str, str] = {
    "apps/any-concurrency/docker-compose.standalone.yml":
        "a self-contained harness for running any-concurrency OUTSIDE the platform — that is G26's "
        "own description of it (`data-volumes-lint.py:128`), the compiler reads `<app>/"
        "docker-compose.yml` and nothing else, and no hook or state line runs this file. It would "
        "otherwise report its own `${PORT:-8080}:8000` and a `profiles: [n8n]`-gated n8n on "
        "`5678:5678` — a laptop harness (`open http://localhost:8080`, its first line), not a door.",
    "apps/any-concurrency/examples/docker-compose.n8n.yml":
        "an EXAMPLE of wiring any-concurrency into somebody else's n8n stack, in a directory named "
        "`examples/`. Nothing reads it: not the compiler, not a hook, not a test. Its `8080:8000` "
        "and `5678:5678` are the example's, not this office's.",
    "apps/any-concurrency/examples/docker-compose.traefik.yml":
        "the same, for somebody else's traefik — and its `80:80` is not this office's front door, "
        "so it would be reported twice over. Nothing reads it.",
}

#: THE MEASURED KNOWN RED — 2026-10-09, on `hp-dgo` at the commit that added this gate. Each one is a
#: real exposure the doc forbids, still in the tree, recorded with WHY it is still there. `--strict`
#: treats every one of them as a finding. A stale entry FAILS (see ANTI-ROT above).
KNOWN_RED: dict[str, str] = {
    # ── R1: published on 0.0.0.0, where `127.0.0.1:` in front of the host port is the whole fix,
    #        and is what every other publish in this tree already does. Measured live by `rap-009`'s
    #        pentest as traefik publishing `6379`/`15432` on `0.0.0.0` — the second number is this
    #        office's `TRAEFIK_POSTGRES_HOST_PORT`, the first is the default linted here.
    "platform-base/traefik/docker-compose.yml|traefik-deployment|${TRAEFIK_POSTGRES_HOST_PORT:-5432}:5432":
        "the host side is published on 0.0.0.0 (5432 by default, 15432 on this office's .env), so "
        "Docker's port publish bypasses the host firewall and any machine on the network reaches "
        "Postgres' passthrough. The comment above it justifies the port NUMBER being overridable, "
        "not the interface: `127.0.0.1:${TRAEFIK_POSTGRES_HOST_PORT:-5432}:5432` is the fix, and it "
        "is a production traefik config change that needs its own item (sec-0xx), not this gate's.",
    "platform-base/traefik/docker-compose.yml|traefik-deployment|${TRAEFIK_REDIS_HOST_PORT:-6379}:6379":
        "same publish, same interface, redis' passthrough (6379 default). Same one-line fix — bind "
        "the host side to 127.0.0.1 — and the same reason it is not done here: a production edge "
        "change, measured 2026-10-09 by the pentest, owed its own item.",
    # ── R1: openhands is a gallery app, `enabled: false` in platform.state.yaml — so none of these
    #        four is reachable on this office TODAY. They are gated anyway because a gallery app is
    #        one `enabled: true` from running (G15's reasoning about shipping images), and 2375 is
    #        not an ordinary debug port: it is the Docker API with no TLS.
    "apps/openhands/docker-compose.yml|docker-proxy|2375:2375":
        "publishes the Docker API itself on every interface — the engine that runs this office, "
        "with no TLS in front of it. openhands is disabled on this office (`enabled: false`), so it "
        "is not reachable today; it is red because enabling it is one state line, and because the "
        "port sits beside a read-write engine socket (see R2 below) in the same service.",
    "apps/openhands/docker-compose.yml|openhands|3000:3000":
        "openhands' own web UI on 0.0.0.0, one line above a correct `127.0.0.1:3001:3000` to the "
        "same container port — which is what makes it a decision rather than an oversight: the "
        "loopback form exists in the file, under the same service. Disabled gallery app, so not "
        "reachable today; red for the day it is enabled.",
    # ── R2: the one read-write engine socket a read-only mount WOULD do for, which is the case this
    #        rule exists to name. The other seven read-write mounts are in JUSTIFIED below, each with
    #        the reason `:ro` would not do — this one has none.
    "platform-base/traefik/docker-compose.yml|traefik-deployment|${BBOX_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock":
        "traefik's docker provider only LISTS containers and WATCHES events (`/containers/json`, "
        "`/events`) — it never writes — so `:ro` is the correct spelling of what this mount is, and "
        "it is the spelling every read-only consumer here already uses (connections, "
        "any-concurrency, machine). Kept read-write because the comment above it explains the "
        "SOCKET PATH choice, not the mode, and because none of the six other read-write mounts has "
        "a socket proxy in front of it either. Measured 2026-10-09: the source is "
        "`${BBOX_DOCKER_SOCK}`, i.e. this project's own `/run/bbox-docker.sock`, not a Desktop "
        "socket.",
}

#: Real exposures that the doc's own qualifier EXCLUDES, each with the written reason `:ro` would
#: not do. Not findings — but not silent either: they are printed on every run, and a stale entry
#: FAILS exactly like a stale known red does.
JUSTIFIED: dict[str, str] = {
    "platform-base/autoheal/docker-compose.yml|autoheal|${BBOX_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock":
        "autoheal's whole job is `POST /containers/<id>/restart` — a write. The file states the "
        "residual risk itself (its volumes block: «a docker socket in a container is root on the "
        "host. It is mounted READ-WRITE here … because this service must be able to POST "
        "/containers/<id>/restart, and there is no narrower Docker permission than \"the socket\"»), "
        "and it is the only such comment in the tree that answers the mode rather than the path.",
    "platform-base/app-management/docker-compose.yml|app-management|${BBOX_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock":
        "the control plane installs and brings apps up, which is `docker compose up` — reads and "
        "writes. Its own file says which half needs the write («the docker socket, to read live "
        "container state (and, in the apply stage, to bring the [stack] up)», :11).",
    "platform-base/data-management/docker-compose.yml|data-management|${BBOX_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock":
        "the archiver's import path creates containers from an export, so it writes to the engine. "
        "Its file explains the socket PATH (:44-45, why the host's /run/bbox-docker.sock appears as "
        "/var/run/docker.sock inside) — a read-only mount would break import and nothing else here.",
    "apps/bina-ds/docker-compose.yml|bina-ds|${BBOX_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock":
        "the agent's shell runs `./bbox run` — compose, i.e. the engine — from inside the container. "
        "It is the deliberate door described in the office's own operating model: `exec` on a "
        "machine is `POST /api/computers/<id>/exec`, and this container is that door's own tool.",
    "apps/openhands/docker-compose.yml|openhands|/var/run/docker.sock:/var/run/docker.sock":
        "a coding agent that launches its own runtime containers (docker-outside-of-docker) — "
        "already declared as such by G32's SOCK_ALLOWED_APPS for the same reason. Disabled gallery "
        "app on this office; read-write is what the service IS.",
    "apps/openhands/docker-compose.yml|docker-proxy|/var/run/docker.sock:/var/run/docker.sock":
        "openhands' docker-proxy exists to MUTATE the engine's API surface — it is the socket proxy "
        "the doc asks for (:216-217), wrapping a socket it must therefore hold itself. Disabled "
        "gallery app; its own port 2375 is red above, not this mount.",
    "apps/portainer/docker-compose.yml|portainer|${BBOX_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock":
        "a container-management UI: start, stop, remove, exec are its interface. Disabled gallery "
        "app on this office; a read-only socket would make it a viewer, which is not what it is.",
    # ── R4: the one `privileged: true` in the tree, and the reason a justification is asked for
    #        instead of the word banned. This file is NOT this office's stack (it is the CI runner's,
    #        under ops/devops-vps/), which is why it is in the denominator rather than untested: the
    #        runner is the one place this repo deliberately runs a daemon inside a container.
    "ops/devops-vps/gha-runner/docker-compose.yml|dind|privileged: true":
        "`docker:27-dind` is a Docker daemon inside a container, which cannot work unprivileged — "
        "and the file's own header says what it is for («GitHub Actions self-hosted runner … "
        "DinD-isolated», with `cpus`/`mem_limit` caps so the website on that VPS keeps breathing). "
        "The nested daemon's own API is not published to the host at all (no `ports:` on `dind`), "
        "only onto the compose network the runner shares with it. Asked for, and answered, rather "
        "than assumed — which is what this table is for.",
}


# ── reading the tree ─────────────────────────────────────────────────────────────────────────────

def _resolve(value: str) -> str:
    """`${VAR:-default}` -> the default (what a clone with no `.env` gets); `${VAR}` is left alone."""
    return re.sub(r"\$\{[^}:]+:-([^}]*)\}", r"\1", str(value))


def _trees() -> tuple[dict[str, str], dict[str, str], list[str]]:
    """({compose path -> text}, {Dockerfile path -> text}, [paths NOT_RUN_HERE excluded]).

    The denominator comes from git, not from a glob over whatever happens to be on disk: an
    ignored build artefact and a shipped compose file are different things, and a gate that reads
    the second one must not silently read the first.
    """
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                             capture_output=True, text=True).stdout.split()
    compose_re = re.compile(r"(^|/)docker-compose[^/]*\.ya?ml$")
    composes: dict[str, str] = {}
    excluded: list[str] = []
    for rel in sorted(tracked):
        if rel != "compose.yml" and not compose_re.search(rel):
            continue
        if not (rel == "compose.yml" or rel.startswith(("apps/", "platform-base/", "ops/devops-vps/"))):
            continue
        if rel in NOT_RUN_HERE:
            excluded.append(rel)
            continue
        composes[rel] = (REPO / rel).read_text(encoding="utf-8", errors="replace")
    dockerfiles: dict[str, str] = {}
    for rel in sorted(tracked):
        if re.search(r"(^|/)Dockerfile[^/]*$", rel) and rel.startswith(("apps/", "platform-base/")):
            dockerfiles[rel] = (REPO / rel).read_text(encoding="utf-8", errors="replace")
    return composes, dockerfiles, excluded


def _edge_apps() -> set[str]:
    """The app id(s) whose manifest declares the `edge` capability — the one front door (:404-407)."""
    found = set()
    for tree in TREES:
        for manifest in sorted((REPO / tree).glob("*/app.json")):
            try:
                doc = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for cap in (doc.get("capabilities") or []):
                if isinstance(cap, dict) and cap.get("name") == "edge":
                    found.add(manifest.parent.name)
    return found


def _dockerfile_of(compose_rel: str, svc: dict, dockerfiles: dict[str, str]) -> str | None:
    """The text of the Dockerfile a service BUILDS from, or None when it builds nothing."""
    build = svc.get("build")
    if build is None:
        return None
    if isinstance(build, dict):
        ctx = str(build.get("context") or ".")
        name = str(build.get("dockerfile") or "Dockerfile")
    else:
        ctx, name = str(build), "Dockerfile"
    base = posixpath.normpath(posixpath.join(posixpath.dirname(compose_rel), ctx))
    for cand in (posixpath.join(base, name), posixpath.join(posixpath.dirname(compose_rel), name),
                 posixpath.join(posixpath.dirname(compose_rel), "Dockerfile")):
        if cand in dockerfiles:
            return dockerfiles[cand]
    return None


def _users(text: str | None) -> list[str]:
    """Every `USER` a Dockerfile declares, in order (the last one is the image's)."""
    return re.findall(r"^\s*USER\s+(\S+)", text or "", re.M)


def _last_user(text: str | None) -> str | None:
    users = _users(text)
    return users[-1] if users else None


def _is_root(user: object) -> bool:
    """Does this identity name root? `root`, `0`, `0:0` — and `None`/empty means the image says
    nothing, which for a Dockerfile means uid 0 and for a compose `user:` means the image's default."""
    return str(user).strip().strip('"').strip("'").lower() in ("root", "0", "0:0", "0:0:0", "0.0")


# ── the rules ────────────────────────────────────────────────────────────────────────────────────

def _port_found(entry: object) -> str:
    """The publish as the file writes it — what the gate quotes back."""
    if isinstance(entry, dict):
        return (f"{{target: {entry.get('target')}, published: {entry.get('published')}, "
                f"host_ip: {entry.get('host_ip')}}}")
    return str(entry).strip().strip('"').strip("'")


def _split_publish(entry: object) -> tuple[str | None, str | None, bool]:
    """(host ip, host port, readable?) — `None` ip means 0.0.0.0, which is what compose defaults to."""
    if isinstance(entry, dict):
        ip = entry.get("host_ip")
        port = entry.get("published", entry.get("target"))
        return (str(ip) if ip is not None else None), (str(port) if port is not None else None), port is not None
    spec = re.sub(r"/(?:tcp|udp|sctp)$", "", _resolve(_port_found(entry)).strip())
    if spec.startswith("["):                                     # [::1]:8080:80
        end = spec.find("]")
        rest = spec[end + 2:].split(":")
        return spec[:end + 1], (rest[0] if rest and rest[0] else None), bool(rest and rest[0])
    parts = spec.split(":")
    if len(parts) == 1:                                          # "8080"
        return None, parts[0], bool(parts[0])
    if len(parts) == 2:                                          # "8080:80" — 0.0.0.0:8080
        return None, parts[0], bool(parts[0])
    if len(parts) == 3:                                          # "ip:8080:80"
        return (parts[0] or None), parts[1], bool(parts[1])
    return None, None, False                                     # unreadable: say so, do not guess


def _rule_ports(compose_rel: str, svc: dict, edges: set[str]) -> list[dict]:
    app_id = compose_rel.split("/")[1]
    out = []
    for entry in (svc.get("ports") or []):
        found = _port_found(entry)
        ip, port, readable = _split_publish(entry)
        if not readable:
            out.append(dict(rule="R1", found=found, why="the host side of this publish cannot be "
                           "read statically (a `${VAR}` with no `:-` default), so this gate cannot "
                           "say which interface it binds. Declare a default, which is also what a "
                           "clone with no `.env` will run."))
            continue
        if ip in LOOPBACK:
            continue                                             # the doc's own debugging form (:415)
        if app_id in edges and port in FRONT_DOOR_PORTS:
            continue                                             # the one front door (:404-407)
        where = f"{ip or '0.0.0.0'}:{port}"
        if app_id in edges:
            why = (f"the edge publishes {where} — the front door may publish 80 and 443 and nothing "
                   f"else (:404-407 «only a reverse proxy … publishes ports, and only 80 and 443»).")
        else:
            why = (f"publishes {where} on every interface, and {app_id} does not declare the `edge` "
                   f"capability. Docker's publish bypasses the host firewall (:60-61), so this is "
                   f"reachable from the network whatever ufw says — bind it to 127.0.0.1 (:415) or, "
                   f"for a database, keep it off the host entirely (:64).")
        out.append(dict(rule="R1", found=found, why=why))
    return out


def _mount_found(entry: object) -> str:
    if isinstance(entry, dict):
        return (f"{{source: {entry.get('source')}, target: {entry.get('target')}, "
                f"read_only: {entry.get('read_only')}}}")
    return str(entry).strip()


def _rule_sockets(svc: dict) -> list[dict]:
    out = []
    for entry in (svc.get("volumes") or []):
        text = _mount_found(entry)
        if "docker.sock" not in text:
            continue                                                 # not an engine socket
        if isinstance(entry, dict):
            read_only = bool(entry.get("read_only"))
            source = str(entry.get("source", ""))
        else:
            # the mode is the LAST colon field; a `${VAR:-a:b}` source may contain colons of its own,
            # so the string is not split — the suffix is what decides.
            read_only = re.search(r":ro(?:,[a-z]+)*\s*$", text) is not None
            source = text.split(":", 1)[0]
        if read_only:
            continue                                                 # the doc's acceptable form (:216-217)
        out.append(dict(rule="R2", found=text, why=(
            f"mounts an engine socket read-write (`{source}`) — the doc's own escape path (:53-56) "
            f"and its sharpest line (:262 «never mount the Docker socket»). Where the write is not "
            f"actually needed, `:ro` is the correct spelling of what the mount is; where it IS "
            f"needed, say so in JUSTIFIED with the call that needs it.")))
    return out


def _rule_privileged(svc: dict) -> list[dict]:
    if svc.get("privileged") is not True:
        return []
    return [dict(rule="R4", found="privileged: true", why=(
        "a privileged container is root on the host by construction (:53-56), and the doc says it "
        "twice more with the word «never» (:262, :444). If the service genuinely needs it — the "
        "doc's own sensors do (:354) — add it to JUSTIFIED with the reason, which is a written "
        "decision rather than a switch."))]


def _rule_root_override(compose_rel: str, svc: dict, dockerfiles: dict[str, str]) -> list[dict]:
    """Root although the image declared otherwise — the only shape where a Dockerfile's USER loses."""
    user = svc.get("user")
    if user is None or not _is_root(user):
        return []
    image_user = _last_user(_dockerfile_of(compose_rel, svc, dockerfiles))
    if not image_user or _is_root(image_user):
        return []                                                    # nothing was declared to lose
    return [dict(rule="R4", found=f"user: {user} (the image declares USER {image_user})", why=(
        f"the Dockerfile this service builds from declares `USER {image_user}`, and this compose "
        f"service overrides it with root — a decision the file made is undone in the file beside "
        f"it, and nothing else can undo a `USER` this way (:437 «non-root user», :247-250)."))]


def _third_party_unpinned(composes: dict[str, dict]) -> list[tuple[str, str]]:
    """`[(image, where)]` — third-party references with no `@sha256:` (rule R3, counted)."""
    out, seen = [], set()
    for rel, doc in sorted(composes.items()):
        for name, svc in sorted((doc.get("services") or {}).items()):
            if not isinstance(svc, dict):
                continue
            image = svc.get("image")
            if not image:
                continue
            image = _resolve(str(image))
            if "@sha256:" in image:
                continue
            if (image.startswith(FIRST_PARTY_PREFIXES) or image.startswith(OFFICE_REGISTRY)
                    or image.endswith("-local:latest")):
                continue                                             # this repo's own build output
            key = (image, rel)
            if key not in seen:
                seen.add(key)
                out.append((image, f"{rel}:{name}"))
    return out


def _root_by_omission(composes: dict[str, dict], dockerfiles: dict[str, str]) -> list[str]:
    """First-party services whose container runs as uid 0 because nothing declares a user."""
    out = []
    for rel, doc in sorted(composes.items()):
        for name, svc in sorted((doc.get("services") or {}).items()):
            if not isinstance(svc, dict) or svc.get("build") is None:
                continue
            user = svc.get("user")
            if user is not None:
                continue                                             # declared (R4(a) judges its value)
            image_user = _last_user(_dockerfile_of(rel, svc, dockerfiles))
            if image_user is None or _is_root(image_user):
                out.append(f"{rel}:{name}")
    return out


def scan(composes: dict[str, str], dockerfiles: dict[str, str],
         edges: set[str] | None = None) -> tuple[list[dict], list[tuple[str, str]], list[str], int]:
    """(findings, unpinned images, root-by-omission services, services read). Hermetic."""
    edges = _edge_apps() if edges is None else edges
    findings: list[dict] = []
    parsed: dict[str, dict] = {}
    services = 0
    for rel, text in sorted(composes.items()):
        try:
            doc = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            findings.append(dict(rule="R0", found=rel, why=f"unparseable compose file: {exc}"))
            continue
        parsed[rel] = doc
        for name, svc in sorted((doc.get("services") or {}).items()):
            if not isinstance(svc, dict):
                continue
            services += 1
            for f in (_rule_ports(rel, svc, edges)
                      + _rule_sockets(svc)
                      + _rule_privileged(svc)
                      + _rule_root_override(rel, svc, dockerfiles)):
                f["where"] = f"{rel}|{name}|{f['found']}"
                f["file"], f["service"] = rel, name
                findings.append(f)
    return findings, _third_party_unpinned(parsed), _root_by_omission(parsed, dockerfiles), services


# ── the self-test ────────────────────────────────────────────────────────────────────────────────

SELF_TEST: list[tuple[str, str, dict, dict, bool]] = [
    # (label, the compose path, the compose document, the Dockerfiles, must-be-a-finding)
    # R1 — must catch
    ("a bare publish is on 0.0.0.0",
     "apps/_probe/docker-compose.yml", {"services": {"a": {"ports": ["8080:80"]}}}, {}, True),
    ("a DB port published on every interface",
     "apps/_probe/docker-compose.yml", {"services": {"a": {"ports": ["3306:3306"]}}}, {}, True),
    ("the edge publishing 6379 is still not 80/443",
     "platform-base/traefik/docker-compose.yml", {"services": {"t": {"ports": ["6379:6379"]}}}, {}, True),
    ("a non-edge app publishing 80 is not the front door",
     "apps/_probe/docker-compose.yml", {"services": {"a": {"ports": ["80:80"]}}}, {}, True),
    ("the default of a ${VAR:-…} is what is linted",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"ports": ["${P:-5432}:5432"]}}}, {}, True),
    ("a long-syntax publish with no host_ip",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"ports": [{"target": 80, "published": 8080}]}}}, {}, True),
    # R1 — must allow
    ("a publish bound to the loopback is the doc's debugging form",
     "apps/_probe/docker-compose.yml", {"services": {"a": {"ports": ["127.0.0.1:8080:80"]}}}, {}, False),
    ("the loopback written as a variable default",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"ports": ["${B:-127.0.0.1}:3081:3081"]}}}, {}, False),
    ("the edge publishing 80 and 443",
     "platform-base/traefik/docker-compose.yml",
     {"services": {"t": {"ports": ["80:80", "443:443"]}}}, {}, False),
    ("a container port with no host publish at all",
     "apps/_probe/docker-compose.yml", {"services": {"a": {"expose": ["8080"]}}}, {}, False),
    # R2 — must catch
    ("a read-write host socket",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"volumes": ["/var/run/docker.sock:/var/run/docker.sock"]}}}, {}, True),
    ("the project's own socket, read-write",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"volumes": ["${BBOX_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock"]}}},
     {}, True),
    ("a literal bbox-docker.sock read-write",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"volumes": ["/run/bbox-docker.sock:/var/run/docker.sock:rw"]}}}, {}, True),
    ("the long syntax with read_only: false",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"volumes": [{"type": "bind", "source": "/var/run/docker.sock",
                                      "target": "/var/run/docker.sock", "read_only": False}]}}}, {}, True),
    # R2 — must allow
    ("a read-only socket mount is the doc's acceptable form",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"volumes": ["${BBOX_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock:ro"]}}},
     {}, False),
    ("the long syntax with read_only: true",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"volumes": [{"type": "bind", "source": "/var/run/docker.sock",
                                      "target": "/var/run/docker.sock", "read_only": True}]}}}, {}, False),
    ("an ordinary bind that merely contains a colon",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"volumes": ["./data:/app/data:rw", "vol:/var/lib/pg:rw"]}}}, {}, False),
    # R4 — must catch
    ("a privileged container",
     "apps/_probe/docker-compose.yml", {"services": {"a": {"privileged": True}}}, {}, True),
    ("root overriding a Dockerfile's own USER",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"user": "root", "build": "."}}}, {"apps/_probe/Dockerfile": "FROM x\nUSER node\n"},
     True),
    ("uid 0 spelled as 0:0 over a Dockerfile's USER",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"user": "0:0", "build": "."}}}, {"apps/_probe/Dockerfile": "FROM x\nUSER 65534\n"},
     True),
    # R4 — must allow
    ("a non-root user override",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"user": "1000:1000", "build": "."}}}, {"apps/_probe/Dockerfile": "FROM x\nUSER node\n"},
     False),
    ("root where the Dockerfile itself declares root — nothing was lost",
     "apps/_probe/docker-compose.yml",
     {"services": {"a": {"user": "root", "build": "."}}}, {"apps/_probe/Dockerfile": "FROM x\nUSER root\n"},
     False),
    ("privileged: false",
     "apps/_probe/docker-compose.yml", {"services": {"a": {"privileged": False}}}, {}, False),
    ("a service that builds nothing and sets no user",
     "apps/_probe/docker-compose.yml", {"services": {"a": {"image": "postgres:17"}}}, {}, False),
]


def self_test() -> int:
    """The rules on documents written here: what each must catch, and what it must leave alone."""
    bad = 0
    for label, rel, doc, dockerfiles, should in SELF_TEST:
        findings, _unpinned, _rooty, _n = scan({rel: yaml.safe_dump(doc)}, dict(dockerfiles),
                                               edges={"traefik"})
        got = bool(findings)
        if got != should:
            bad += 1
        print(f"  [{'ok ' if got == should else 'FAIL'}] {'caught' if got else 'allowed':<8} "
              f"({'must catch' if should else 'must allow'}): {label}")
    # the counted rules, which are not findings and must not become any
    unpinned = _third_party_unpinned({"a/docker-compose.yml": {"services": {
        "u": {"image": "postgres:17"}, "d": {"image": "postgres@sha256:" + "0" * 64},
        "f": {"image": "deployment-hacohen-console"}, "o": {"image": OFFICE_REGISTRY + "drive:latest"}}}})
    if [i for i, _ in unpinned] != ["postgres:17"]:
        bad += 1
        print(f"  [FAIL] the digest count must be 1 (postgres:17), got {unpinned}")
    else:
        print("  [ok ] counted  a digested, a first-party and an office-registry image are not counted")
    stale = _self_test_anti_rot()
    bad += stale
    print(f"\nexposure-lint self-test: {len(SELF_TEST) + 2 - bad}/{len(SELF_TEST) + 2} passed")
    return 1 if bad else 0


def _self_test_anti_rot() -> int:
    """A waiver that matches nothing must be a finding — proven on a copy, never on the real tables."""
    global KNOWN_RED
    saved = KNOWN_RED
    try:
        KNOWN_RED = {"nowhere/docker-compose.yml|noservice|9999:9999": "a test entry"}
        findings, _u, _r, _n = scan({}, {}, edges=set())
        stale = _stale(findings)
    finally:
        KNOWN_RED = saved
    if not stale:
        print("  [FAIL] a waiver matching nothing must FAIL (the G31/G34 anti-rot rule)")
        return 1
    print("  [ok ] allowed  a waiver that matches nothing is a stale declaration, and fails")
    return 0


def _stale(findings: list[dict], excluded: list[str] | None = None) -> list[str]:
    matched = {f["where"] for f in findings}
    out = [f"{entry} — matches no finding in the tree any more (stale declaration: the "
           f"mount/publish it names was changed, renamed or removed — delete it)"
           for entry in list(KNOWN_RED) + list(JUSTIFIED) if entry not in matched]
    if excluded is not None:
        out += [f"NOT_RUN_HERE names {rel}, which is not a tracked compose file any more — stale "
                f"exclusion (delete it). The reason it carried: {NOT_RUN_HERE[rel]}"
                for rel in NOT_RUN_HERE if rel not in excluded]
    return out


# ── the report ───────────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="ignore KNOWN_RED and JUSTIFIED: report what this office has measured as "
                         "exposures as findings (the pre-fix red)")
    ap.add_argument("--self-test", action="store_true", help="prove each rule on documents written here")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    compose_text, dockerfiles, excluded = _trees()
    if not compose_text:
        print("G84 FAIL — read ZERO compose files, so nothing was checked")
        return 1
    findings, unpinned, rooty, services = scan(compose_text, dockerfiles)
    stale = _stale(findings, excluded)
    red = [f for f in findings if f["where"] in KNOWN_RED]
    justified = [f for f in findings if f["where"] in JUSTIFIED]
    unwaived = [f for f in findings if f["where"] not in KNOWN_RED and f["where"] not in JUSTIFIED]

    print("G84 exposure-lint — what reaches a host interface, read from the compose files and their "
          "Dockerfiles.\n")
    print(f"read {len(compose_text)} compose file(s) and {services} service(s) — `compose.yml` and "
          f"every tracked `docker-compose*.yml` under {'/, '.join(TREES)}/ and ops/devops-vps/ — plus "
          f"{len(dockerfiles)} Dockerfile(s).")
    print(f"  outside the denominator, named rather than silently skipped ({len(NOT_RUN_HERE)}):")
    for rel in NOT_RUN_HERE:
        print(f"    {rel}")
        print(f"        {NOT_RUN_HERE[rel]}")
    print("static: no network, no Docker daemon, no .env — the `.generated/` render is a consequence "
          "of these files, not a source.")
    print("the rules, each with the line it comes from:")
    for rule, line in RULE_DOC.items():
        print(f"  {rule}  {line}")

    def show(tag: str, f: dict, note: str) -> None:
        print(f"  [{f['rule']}] {f['file']}  (service {f['service']})")
        print(f"        found: {f['found']}")
        print(f"        {tag}: {note}")

    if red:
        print(f"\nKNOWN RED — {len(red)} exposure(s) measured 2026-10-09, each still in the tree with "
              f"the reason it is:")
        for f in red:
            show("why red", f, KNOWN_RED[f["where"]])
    if justified:
        print(f"\nJUSTIFIED — {len(justified)} real exposure(s) the doc's own qualifier excludes "
              f"(`:ro` would not do, and the file says which call needs the write):")
        for f in justified:
            show("why justified", f, JUSTIFIED[f["where"]])
    if unwaived:
        print(f"\nG84 FAIL — {len(unwaived)} unwaived exposure(s). A host port on every interface, "
              f"or an engine socket held read-write with nothing said about it, is what the doc's "
              f"first two rules are about:")
        for f in unwaived:
            print(f"  [{f['rule']}] {f['file']}  (service {f['service']})  found: {f['found']}")
            print(f"        {f['why']}")
        print("\n  Fix it in the compose file, not in this gate: bind the port to 127.0.0.1, add "
              "`:ro` to the socket, or — if the write is genuinely needed — write the reason into "
              "JUSTIFIED, where a stale entry fails.")

    print(f"\nADVISORY (counted, not enforced — the reasons are in the docstring):")
    print(f"  R3  {len(unpinned)} third-party image reference(s) with no `@sha256:` digest. The doc "
          f"asks for digest pinning (:81, :286-289, :448) and this gate does not fail on it: G15 owns "
          f"\"pinned at all\", and G15's own docstring records that a digest breaks the offline "
          f"bundle (`docker load` drops RepoDigests).")
    for image, where in unpinned[:6]:
        print(f"        {image}   [{where}]")
    if len(unpinned) > 6:
        print(f"        … and {len(unpinned) - 6} more")
    print(f"  R4  {len(rooty)} first-party service(s) run as uid 0 — the image's Dockerfile declares "
          f"no `USER` and no compose `user:` names one. The doc says it inside the OWASP/CIS "
          f"checklist (:437 «non-root user»), never with the «never» it spends on privileged (:262) "
          f"and the socket (:217), so it is a count that is printed every run rather than a failure.")

    if stale:
        print(f"\nG84 FAIL — {len(stale)} stale declaration(s) in this gate's own tables "
              f"(the G31/G34 anti-rot rule):")
        for s in stale:
            print(f"  {s}")
        return 1
    if args.strict and (red or justified):
        print(f"\nG84 FAIL (--strict: KNOWN_RED and JUSTIFIED ignored) — "
              f"{len(red) + len(justified)} exposure(s) stand:")
        for f in red + justified:
            print(f"  [{f['rule']}] {f['file']}  (service {f['service']})  found: {f['found']}")
        return 1
    if unwaived:
        return 1

    print(f"\nG84 PASS — {len(findings)} exposure(s) found, {len(red)} known red and "
          f"{len(justified)} justified, every one named above; nothing unwaived.")
    if red:
        print(f"  {len(red)} known red: delete the KNOWN_RED entry the moment its compose line is "
              f"fixed — this gate fails on a stale entry, which is how the list shrinks itself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
