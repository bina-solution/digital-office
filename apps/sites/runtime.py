"""sites.runtime — THE FIXED PATTERN for running a site on a machine.

One site, one directory, one compose project, one container, one log file. Everything the office
knows about a site is rendered into three files under `<root>` on the machine it runs on:

    <root>/docker-compose.yml   the stack: nginx (or the site's own image) + optional builder
    <root>/nginx/default.conf   the server, including the JSON access log the office reads
    <root>/site.meta.json       what the office believes about this site (the other two follow
                                from it), written for a human who is standing on the machine
    <root>/README.md            what this directory is and how to operate it without the office
    <root>/site/                the served content          (static, static-built)
    <root>/src/                 the checked-out source      (git)
    <root>/logs/access.log      the visits, one JSON object per line

Why a directory and not "ssh in and run nginx": because the machine is not ours. A site the office
manages must be inspectable, restartable and removable BY THE OWNER, with the office absent — the
RENDERED files are the contract, and this app is one of its two writers (the owner's editor is the
other, until the next deploy overwrites it, which is exactly what "declared, not registered" means).

Three content kinds, and they are the whole pattern:

    dir           the content is files in `<root>/site` (uploaded, or copied from wherever it was)
    git           the content is a repository cloned into `<root>/src`, optionally BUILT into
                  `<root>/site` by a one-shot builder service (eleventy/vite/next/…)
    volume        the content is a docker volume that already exists on the machine — how a site
                  that predates the office joins the pattern WITHOUT copying a byte (adoption)

What this file deliberately does NOT do: it never addresses the engine of the machine the OFFICE
runs on. Every command here is sent to a machine through `apps/computers` and executed by THAT
machine's docker. `local` is such a machine and nothing else (`COMPOSE` below is the remote's).
"""
from __future__ import annotations

import json
import logging
import os
import re

import machines
from machines import MachineError, q, run, stdout_of

log = logging.getLogger("sites.runtime")

#: The REMOTE machine's compose. Kept as a name rather than inlined at each call site because the
#: distinction it carries is the whole safety story of this module: the office host's own engine is
#: addressed through `bbox`/`scripts/dc` only, and this app holds no socket to it (gate G32). Every
#: use below is `ssh <machine> "… ${COMPOSE} …"`.
COMPOSE = "docker compose"

DEFAULT_ROOT = os.environ.get("SITES_ROOT", "/opt/bina-sites")
WEB_IMAGE = os.environ.get("SITES_WEB_IMAGE", "nginx:1.27-alpine")
BUILD_IMAGE = os.environ.get("SITES_BUILD_IMAGE", "node:22-alpine")
DEFAULT_EDGE = {
    "provider": "traefik",
    "network": "traefik-network",
    "certresolver": "myresolver",
    "http_entrypoint": "web",
    "https_entrypoint": "websecure",
    "middlewares": [],
    "tls": True,
}
MANAGED_SENTINEL = "bina-site-managed"     # a label that says "the office rendered this stack"


def slug_ok(sid: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", sid or ""))


def container_name(site: dict) -> str:
    """The container the office talks to for this site.

    A MANAGED site is `site-<id>` — deterministic, so `docker logs site-<id>` works from the
    machine's shell without asking the office. An ADOPTED site keeps whatever container it already
    had: renaming a running production container to make our noun prettier would be a change with
    no upside and a real outage.
    """
    legacy = (site.get("legacy") or {}).get("container")
    if site.get("source") == "adopted" and legacy:
        return legacy
    return f"site-{site['id']}"


def content_of(site: dict) -> dict:
    c = dict(site.get("content") or {})
    c.setdefault("type", "dir")
    if c["type"] == "dir":
        c.setdefault("dir", "site")
    return c


def web_root_dir(site: dict) -> str | None:
    """Where the SERVED files live, relative to `<root>` — None for a proxy (nothing is served).

    A site with a build step serves the BUILT output (`out`, default `site`) whichever way its
    source arrived — a repository or a directory — because that is what the builder writes. Only a
    plain directory with no builder is served from wherever its files are.
    """
    if site.get("kind") == "proxy":
        return None
    c = content_of(site)
    if c["type"] == "volume":
        return None
    if c.get("build"):
        return c.get("out") or "site"
    if c["type"] == "git":
        return c.get("src") or "src"
    return c.get("dir") or "site"


def source_dir(site: dict) -> str:
    """Where the site's SOURCE lives (what a builder reads), relative to `<root>`."""
    c = content_of(site)
    return c.get("src") or ("src" if c["type"] == "git" else (c.get("dir") or "site"))


def hosts_of(site: dict) -> list[str]:
    return [h for h in (site.get("hosts") or []) if h]


def canonical_host(site: dict) -> str:
    hs = hosts_of(site)
    return hs[0] if hs else ""


def site_url(site: dict, path: str = "/") -> str:
    h = canonical_host(site)
    if not h:
        return ""
    scheme = "https" if (site.get("edge") or {}).get("tls", True) and "." in h else "http"
    return f"{scheme}://{h}{path}"


# ── the rendered stack ───────────────────────────────────────────────────────────────────────────
def _traefik_labels(site: dict) -> list[str]:
    edge = {**DEFAULT_EDGE, **(site.get("edge") or {})}
    if edge.get("provider") != "traefik":
        return []
    hosts = hosts_of(site)
    if not hosts:
        return []
    svc = f"site-{site['id']}"
    rule = " || ".join(f"Host(`{h}`)" for h in hosts)
    labels = [
        "traefik.enable=true",
        f"traefik.docker.network={edge['network']}",
        f"traefik.http.services.{svc}.loadbalancer.server.port={int(site.get('port') or 80)}",
        f"traefik.http.routers.{svc}-http.entrypoints={edge['http_entrypoint']}",
        f"traefik.http.routers.{svc}-http.rule={rule}",
        f"traefik.http.routers.{svc}-http.service={svc}",
    ]
    mw = ",".join(edge.get("middlewares") or [])
    if mw:
        labels.append(f"traefik.http.routers.{svc}-http.middlewares={mw}")
    if edge.get("tls", True):
        labels += [
            f"traefik.http.routers.{svc}-https.entrypoints={edge['https_entrypoint']}",
            f"traefik.http.routers.{svc}-https.rule={rule}",
            f"traefik.http.routers.{svc}-https.service={svc}",
            f"traefik.http.routers.{svc}-https.tls=true",
            f"traefik.http.routers.{svc}-https.tls.certresolver={edge['certresolver']}",
        ]
        if mw:
            labels.append(f"traefik.http.routers.{svc}-https.middlewares={mw}")
    return labels


def render_compose(site: dict) -> str:
    """The stack. Read this as the pattern's definition — everything else is derived from it."""
    edge = {**DEFAULT_EDGE, **(site.get("edge") or {})}
    c = content_of(site)
    project = site["project"]
    root_dir = web_root_dir(site)
    lines: list[str] = [
        f"# bina-site:{site['id']} — RENDERED by the office's sites app from the site's record.",
        "# Do not hand-edit: the next deploy overwrites this file. Change the site in the office",
        f"# (http://sites.localhost:8080 or the „אתרים” tile) — the record is the source of truth.",
        f"# machine: {site.get('machine')}   root: {site.get('root')}   hosts: {', '.join(hosts_of(site))}",
        "services:",
        "  web:",
        f"    image: {WEB_IMAGE}",
        f"    container_name: {container_name(site)}",
        "    restart: unless-stopped",
        "    labels:",
        f"      - {MANAGED_SENTINEL}=1",
    ]
    lines += [f'      - "{l}"' for l in _traefik_labels(site)]
    lines += [
        "    volumes:",
        "      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro",
        "      - ./logs:/var/log/nginx",
    ]
    if site.get("kind") == "proxy":
        upstream = (site.get("content") or {}).get("upstream") or ""
        lines.append(f"      # nothing served locally: nginx proxies to {upstream}")
    elif c["type"] == "volume":
        lines.append(f"      - {c['volume']}:{c.get('mount') or '/usr/share/nginx/html'}:ro")
    else:
        lines.append(f"      - ./{root_dir}:{c.get('mount') or '/usr/share/nginx/html'}:ro")
    lines += [
        f"    networks: [{edge['network']}]",
    ]
    if c.get("build") and c["type"] in ("git", "dir"):
        b = c["build"]
        src = c.get("src") or "src"
        cmd = b.get("command") or "echo 'no build command set' >&2; exit 1"
        env_lines = [f"      - {k}={v}" for k, v in (b.get("env") or {}).items()]
        lines += [
            "  # ONE-SHOT builder: renders the source into the served directory, then exits. It is",
            "  # in the SAME compose as the server on purpose — the site's toolchain is part of the",
            "  # site, and a build that only exists in someone's shell is a build nobody can repeat.",
            "  builder:",
            f"    image: {b.get('image') or BUILD_IMAGE}",
            "    working_dir: /work",
            "    restart: 'no'",
            "    volumes:",
            f"      - ./{src}:/work:ro",
            f"      - ./{c.get('out') or 'site'}:/out",
        ]
        if env_lines:
            # The build's OWN environment (ELEVENTY_ENV=production and friends). Without a way to
            # declare it, the only place to put it would be a hand-edited file on the machine — the
            # exact drift this pattern exists to remove.
            lines += ["    environment:"] + env_lines
        lines += [
            f"    command: >-",
            f"      sh -c {json.dumps(_builder_script(b.get('command') or ''))}",
        ]
    lines += ["", "networks:", f"  {edge['network']}:", "    external: true", ""]
    if c["type"] == "volume":
        lines += ["volumes:", f"  {c['volume']}:", "    external: true", ""]
    return "\n".join(lines)


def _builder_script(user_command: str) -> str:
    """The builder's shell: work on a COPY of the source, render, then replace the served tree.

    Copying matters: npm/vite write inside the tree (node_modules, .cache, dist) and `<root>/src` is
    a git checkout the next deploy resets — a build that mutates its own source is a build whose
    second run behaves differently from its first. The served directory is emptied only after the
    build SUCCEEDS, so a failed build leaves the previous site live instead of a half-written one.
    """
    return ("set -e; mkdir -p /tmp/work /out; cp -r /work/. /tmp/work/; cd /tmp/work; "
            f"{user_command}; "
            "if [ -z \"$(ls -A /tmp/work/dist 2>/dev/null)\" ]; then "
            "echo 'build produced no dist/ — refusing to replace the served files' >&2; exit 1; fi; "
            "rm -rf /out/* ; cp -r /tmp/work/dist/. /out/")


NGINX_HEADERS = """  # security headers live in the SITE, not only in the edge: the same stack must be safe on a
  # machine whose traefik has no `security-headers@file` middleware, and a header that only exists
  # in one deployment's edge config is a header the next deployment does not have.
  add_header X-Content-Type-Options nosniff always;
  add_header Referrer-Policy strict-origin-when-cross-origin always;
  add_header X-Frame-Options SAMEORIGIN always;
  add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
  add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;"""

NGINX_LOG_FORMAT = """# THE one log the office reads. JSON, one object per line, written under ./logs so the office
# collects visits by reading a file — no script in the page, no third party, nothing to block.
#
# It sits OUTSIDE `server {}` because nginx accepts `log_format` only in the `http` context, and this
# file is included from conf.d (which IS http context). A definition inside the server block is a
# startup error — i.e. a site that does not come up at all. The server block only needs the NAME.
log_format bina_json escape=json '{"t":"$time_iso8601","ip":"$remote_addr","m":"$request_method",\\
"u":"$request_uri","s":$status,"b":$body_bytes_sent,"r":"$http_referer","a":"$http_user_agent",\\
"h":"$host","rt":$request_time}';"""

NGINX_LOG_USE = """  access_log /var/log/nginx/access.log bina_json;
  error_log /var/log/nginx/error.log warn;"""


def _canonical_redirect(site: dict) -> str:
    """The `if ($host = <other>) { return 301 … }` block, or "".

    Opt-in per site (`edge.canonical_redirect`), and off by default on purpose — and when it is on,
    it redirects the **www twin of the canonical host** and anything explicitly listed in
    `edge.redirect_hosts`. NOT every other hostname: `site.staging.<domain>` exists precisely to
    serve the site under a name whose DNS may differ from the apex (that is how the office previews a
    site during a DNS change), and collapsing it into the apex would turn a working preview into a
    redirect to production — which is what the first version of this function did, on 2026-09-23, to
    digital-office.co.il's staging alias.
    """
    edge = {**DEFAULT_EDGE, **(site.get("edge") or {})}
    hosts = hosts_of(site)
    if not edge.get("canonical_redirect") or not hosts:
        return ""
    apex, scheme = hosts[0], "https" if edge.get("tls", True) else "http"
    twin = f"www.{apex}" if not apex.startswith("www.") else apex[4:]
    targets = [h for h in hosts[1:] if h == twin] + \
              [h for h in (edge.get("redirect_hosts") or []) if h in hosts and h != apex]
    lines = [f"  if ($host = {h}) {{ return 301 {scheme}://{apex}$request_uri; }}"
             for h in dict.fromkeys(targets)]
    return "\n".join(lines)


def render_nginx(site: dict) -> str:
    head = [
        f"# bina-site:{site['id']} — RENDERED by the office's sites app. Do not hand-edit.",
        NGINX_LOG_FORMAT,
        "",
        "server {",
        "  listen 80;",
        "  server_name _;",
        "  charset utf-8;",
        "  server_tokens off;",
        NGINX_LOG_USE,
        "",
        "  gzip on; gzip_vary on; gzip_comp_level 6; gzip_min_length 1024;",
        "  gzip_types text/plain text/css application/javascript application/json "
        "image/svg+xml application/xml;",
        "",
        NGINX_HEADERS,
        "",
        "  # the office's own liveness probe, answered by the server itself (never cached, never",
        "  # logged): it must keep answering when the app behind it is broken.",
        '  location = /healthz { access_log off; default_type text/plain; return 200 "ok\\n"; }',
    ]
    canon = _canonical_redirect(site)
    if canon:
        head += [
            "",
            "  # ONE canonical hostname. Every other name this site answers on redirects to it with a",
            "  # 301 — otherwise the same page is served under two names, search engines split its",
            "  # ranking between them, and a share link that happens to use www is a different page",
            "  # as far as everyone downstream is concerned.",
            canon,
        ]
    extra_headers = [h for h in ((site.get("edge") or {}).get("headers") or []) if h]
    if extra_headers:
        head += [
            "",
            "  # Headers this SITE declares (edge.headers in its record). The pattern cannot know that",
            "  # a site talks to plausible.io, and a migration that drops its Content-Security-Policy",
            "  # is a security regression dressed as a refactor — so the policy lives in the record.",
        ]
        head += [f"  add_header {h.strip().rstrip(';')} always;" for h in extra_headers]
    nginx_extra = ((site.get("edge") or {}).get("nginx_extra") or "").strip()
    if nginx_extra:
        head += ["", "  # The site's own nginx directives (edge.nginx_extra). Part of the RECORD, so a",
                 "  # redeploy writes them back instead of deleting them."]
        head += ["  " + line for line in nginx_extra.splitlines()]
    if site.get("kind") == "proxy":
        upstream = (content_of(site).get("upstream") or "").rstrip("/")
        body = [
            "  location / {",
            f"    proxy_pass {upstream};",
            "    proxy_http_version 1.1;",
            "    proxy_set_header Host $host;",
            "    proxy_set_header X-Real-IP $remote_addr;",
            "    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
            "    proxy_set_header X-Forwarded-Proto $scheme;",
            "    proxy_read_timeout 300s;",
            "  }",
        ]
    else:
        body = [
            "  root /usr/share/nginx/html;",
            "  index index.html;",
            "",
            "  # `= /` first: an empty content directory otherwise answers 403 (nginx refuses to list",
            "  # a directory) and a missing deploy looks like a permissions problem. A clean 404 is the",
            "  # truth, and it is the code every crawler and monitor already understands.",
            "  location = / { try_files /index.html =404; }",
            "  location / { try_files $uri $uri/ $uri.html =404; }",
            "",
            "  # `expires` and not `add_header`: add_header inside a location REPLACES the inherited",
            "  # security headers above (nginx inheritance rule), and the site would silently lose",
            "  # them on exactly the requests that serve its assets.",
            "  location ~* \\.(?:css|js|svg|woff2?)$ { expires 1y; try_files $uri =404; }",
            "  location ~* \\.(?:png|jpe?g|gif|webp|avif|ico)$ { expires 30d; try_files $uri =404; }",
            "",
            "  error_page 404 /404.html;",
            "  location = /404.html { internal; }",
        ]
    return "\n".join(head + [""] + body + ["}", ""])


def render_meta(site: dict) -> str:
    return json.dumps({
        "pattern": "bina-site.v1",
        "id": site["id"], "label": site.get("label"), "hosts": hosts_of(site),
        "machine": site.get("machine"), "root": site.get("root"), "project": site.get("project"),
        "kind": site.get("kind"), "port": site.get("port"), "content": content_of(site),
        "edge": {**DEFAULT_EDGE, **(site.get("edge") or {})},
        "written_by": "apps/sites (the office's sites app) — the record in the office is the truth",
    }, ensure_ascii=False, indent=2) + "\n"


def render_readme(site: dict) -> str:
    hosts = ", ".join(hosts_of(site)) or "(no hostname yet)"
    return f"""# site: {site['id']} — {site.get('label') or ''}

This directory is a **site the office runs**. It was rendered by the „אתרים” app of the Digital
Office; the office's record for this site is the source of truth and the next deploy rewrites these
files.

| | |
|---|---|
| hostnames | `{hosts}` |
| machine | `{site.get('machine')}` |
| compose project | `{site.get('project')}` |
| container | `{container_name(site)}` |
| content | `{content_of(site).get('type')}` |
| served from | `{web_root_dir(site) or '(proxy)'}` |

## Operate it without the office

```sh
cd {site.get('root')}
docker compose -p {site.get('project')} ps          # what is running
docker compose -p {site.get('project')} logs -f web # the server (and its errors)
docker compose -p {site.get('project')} restart web # bounce it
docker compose -p {site.get('project')} down        # stop it (content is NOT deleted)
```

Visits are in `logs/access.log` — one JSON object per line, written by this site's own nginx.
"""


def files(site: dict) -> dict[str, str]:
    return {
        "docker-compose.yml": render_compose(site),
        "nginx/default.conf": render_nginx(site),
        "site.meta.json": render_meta(site),
        "README.md": render_readme(site),
    }


# ── the edge: what publishes a site on that machine ──────────────────────────────────────────────
def probe_edge(machine_id: str) -> dict:
    """Find the reverse proxy that can publish a site ON THIS MACHINE.

    Discovered, never assumed: the office's own host publishes `*.localhost` through its own
    traefik on :8080, the VPS publishes real domains through `traefik-staging` with an ACME
    resolver, and a fresh machine has neither. A pattern that hardcoded `myresolver` +
    `traefik-network` would render a stack that routes nothing — and look correct while doing it.
    """
    out = stdout_of(machine_id, (
        "for c in $(docker ps --format '{{.Names}}' | grep -i traefik); do "
        "echo \"CTR $c\"; "
        "docker inspect $c --format 'NET {{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'; "
        "docker inspect $c --format 'CMD {{json .Config.Cmd}}'; "
        "done"), timeout=60)
    edges: list[dict] = []
    cur: dict | None = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("CTR "):
            cur = {"container": line[4:].strip(), "networks": [], "certresolvers": [],
                   "entrypoints": [], "middlewares": [], "source": "docker"}
            edges.append(cur)
        elif line.startswith("NET ") and cur is not None:
            cur["networks"] = line[4:].split()
        elif line.startswith("CMD ") and cur is not None:
            try:
                argv = json.loads(line[4:])
            except ValueError:
                argv = []
            for a in argv if isinstance(argv, list) else []:
                a = str(a)
                m = re.match(r"--certificatesresolvers\.([\w.-]+)\.acme", a)
                if m:
                    cur["certresolvers"].append(m.group(1))
                m = re.match(r"--entrypoints\.([\w.-]+)\.address", a)
                if m:
                    cur["entrypoints"].append(m.group(1))
                if a.startswith("--providers.file.directory="):
                    cur["file_provider"] = a.split("=", 1)[1]
    # the file provider's middleware catalogue — the only way to know whether `compress@file` can
    # be referenced on THIS machine (a label naming a middleware that does not exist means the
    # router is dropped by traefik, and the site 404s while its container reports healthy).
    for e in edges:
        d = e.get("file_provider")
        if not d:
            continue
        cmd = (f"docker exec {q(e['container'])} sh -c "
               f"{q('cat ' + d.rstrip('/') + '/*.yaml ' + d.rstrip('/') + '/*.yml 2>/dev/null')}")
        text = stdout_of(machine_id, cmd, timeout=45)
        e["middlewares"] = _middlewares_from(text)
    return {"edges": edges, "found": bool(edges)}


def _middlewares_from(text: str) -> list[str]:
    """`name:` keys under a top-level `middlewares:` mapping — a deliberately small parser, because
    the only question asked here is 'does this name exist', and a YAML library in this container
    for that would be a dependency with a CVE feed."""
    out, inside = [], False
    for raw in (text or "").splitlines():
        if re.match(r"^\s*middlewares:\s*$", raw):
            inside = True
            continue
        if inside:
            if raw.strip() and not raw.startswith((" ", "\t")):
                inside = False
                continue
            m = re.match(r"^\s{2,}([A-Za-z0-9_.-]+):", raw)
            if m:
                out.append(m.group(1))
    return out


def default_edge(machine_id: str) -> dict:
    """The edge a NEW site on this machine gets: the machine's own answer, with our defaults."""
    edge = dict(DEFAULT_EDGE)
    try:
        probe = probe_edge(machine_id)
    except Exception as e:                       # noqa: BLE001 — a probe must never break the caller
        log.warning("edge probe failed on %s: %s", machine_id, type(e).__name__)
        return edge
    edges = probe.get("edges") or []
    if not edges:
        return {**edge, "provider": "none"}
    e = edges[0]
    if e.get("networks"):
        edge["network"] = "traefik-network" if "traefik-network" in e["networks"] else e["networks"][0]
    if e.get("certresolvers"):
        edge["certresolver"] = e["certresolvers"][0]
    for key, wanted in (("http_entrypoint", "web"), ("https_entrypoint", "websecure")):
        if wanted in (e.get("entrypoints") or []):
            edge[key] = wanted
        elif e.get("entrypoints"):
            edge[key] = e["entrypoints"][0] if key == "http_entrypoint" else e["entrypoints"][-1]
    if "compress" in (e.get("middlewares") or []):
        edge["middlewares"] = ["compress@file"]
    edge["edge_container"] = e.get("container")
    edge["middlewares_available"] = e.get("middlewares") or []
    return edge


# ── lifecycle on the machine ─────────────────────────────────────────────────────────────────────
def _compose(site: dict, action: str) -> str:
    root = site["root"]
    project = site["project"]
    return (f"cd {q(root)} && {COMPOSE} -p {q(project)} -f {q(root + '/docker-compose.yml')} {action}")


def is_managed(site: dict) -> bool:
    return site.get("source") != "adopted" and bool(site.get("root"))


def deploy(site: dict, build: bool = True, timeout: int = 540) -> dict:
    """Write the stack, prepare the content, bring the site up — in that order, and never half.

    The content is prepared BEFORE the server is touched, so a build failure leaves the previous
    site running (the builder only replaces the served directory after its build succeeds). A site
    that is already up therefore gets a new version without a window in which it serves nothing.
    """
    if not is_managed(site):
        raise MachineError("האתר הזה נלקח כמו שהוא (adopted) — אין מה לפרוס; יש להעביר אותו לדפוס.",
                           machine=site.get("machine"), status=409)
    machine_id = site["machine"]
    root = site["root"]
    steps: list[dict] = []
    run(machine_id, f"mkdir -p {q(root + '/nginx')} {q(root + '/logs')} {q(root + '/site')}",
        timeout=60, what="יצירת תיקיית האתר")
    for rel, text in files(site).items():
        machines.write_file(machine_id, f"{root}/{rel}", text, timeout=60)
    steps.append({"step": "render", "ok": True, "files": sorted(files(site))})

    c = content_of(site)
    if c["type"] == "git":
        steps.append(_sync_git(site, c, timeout))
    if c.get("build") and build and c["type"] in ("git", "dir"):
        res = run(machine_id, _compose(site, "run --rm builder"), timeout=timeout,
                  what="בניית האתר")
        steps.append({"step": "build", "ok": True, "tail": (res.get("stdout") or "")[-800:]})
    # `up -d web`, NOT `up -d`: the builder is a ONE-SHOT service and `up -d` starts every service in
    # the file — so the site would be built a second time (npm ci and all) by a container nobody asked
    # for, which then sits there "Up" after the deploy has already reported success. The build belongs
    # to the explicit `run --rm builder` above; the deploy brings up the SERVER.
    res = run(machine_id, _compose(site, "up -d --remove-orphans web"), timeout=180,
              what="הרמת האתר")
    machines.exec_on(machine_id, _compose(site, "rm -sf builder"), timeout=60)
    steps.append({"step": "up", "ok": True, "tail": (res.get("stdout") or "")[-500:]})
    steps.append(_reload(site))
    check = verify_local(site)
    steps.append({"step": "verify", **check})
    return {"site": site["id"], "machine": machine_id, "root": root, "steps": steps,
            "ok": all(s.get("ok") for s in steps)}


def _reload(site: dict) -> dict:
    """Make the server actually READ the config this deploy just wrote.

    `docker compose up -d` does nothing to a container whose bind-mounted config changed: the file is
    new, the running nginx still holds the old one in memory, and the deploy reports success while
    the site behaves like last week. That is exactly what happened on 2026-09-23 — a rewritten
    redirect rule took effect only after a manual reload — so the deploy validates the config and
    reloads, and a config nginx REFUSES becomes a failed deploy rather than a landmine for the next
    container restart.
    """
    name = container_name(site)
    check = machines.exec_on(site["machine"], f"docker exec {q(name)} nginx -t 2>&1", timeout=90)
    out = ((check.get("stdout") or "") + (check.get("stderr") or "")).strip()
    if check.get("code") == 127 or "executable file not found" in out:
        return {"step": "reload", "ok": True, "skipped": "אין nginx בקונטיינר של האתר"}
    if check.get("code") != 0:
        raise MachineError("הגדרות nginx שנכתבו אינן תקינות — האתר לא נטען איתן",
                           machine=site["machine"], detail=out[-1200:])
    run(site["machine"], f"docker exec {q(name)} nginx -s reload", timeout=90,
        what="טעינת הגדרות nginx")
    return {"step": "reload", "ok": True, "config": "nginx -t עבר"}


def _sync_git(site: dict, c: dict, timeout: int) -> dict:
    """Clone or fast-forward the site's source on the machine.

    `reset --hard` rather than `pull`: this working copy is a BUILD INPUT that the office owns, not
    a place anyone edits, and a checkout that refuses to fast-forward (a human poked it once) would
    otherwise wedge every future deploy with a merge it has no business performing.
    """
    machine_id = site["machine"]
    root, repo = site["root"], c.get("repo") or ""
    if not repo:
        raise MachineError("חסר מאגר (repo) בהגדרת התוכן", machine=machine_id, status=400)
    src = c.get("src") or "src"
    branch = c.get("branch") or "main"
    path = f"{root}/{src}"
    cmd = (f"if [ -d {q(path + '/.git')} ]; then cd {q(path)} && git fetch --depth 1 origin "
           f"{q(branch)} && git reset --hard FETCH_HEAD && git clean -fd; else "
           f"git clone --depth 1 --branch {q(branch)} {q(repo)} {q(path)}; fi; "
           f"git -C {q(path)} log -1 --format='%h %s'")
    res = run(machine_id, cmd, timeout=timeout, what="משיכת קוד האתר")
    return {"step": "git", "ok": True, "repo": repo, "branch": branch,
            "head": (res.get("stdout") or "").strip().splitlines()[-1:] or [""]}


def start(site: dict) -> dict:
    if is_managed(site):
        run(site["machine"], _compose(site, "start"), timeout=120, what="הפעלת האתר")
    else:
        run(site["machine"], f"docker start {q(container_name(site))}", timeout=120,
            what="הפעלת האתר")
    return status(site)


def stop(site: dict) -> dict:
    if is_managed(site):
        run(site["machine"], _compose(site, "stop"), timeout=120, what="כיבוי האתר")
    else:
        run(site["machine"], f"docker stop {q(container_name(site))}", timeout=120,
            what="כיבוי האתר")
    return status(site)


def restart(site: dict) -> dict:
    if is_managed(site):
        run(site["machine"], _compose(site, "restart"), timeout=180, what="הפעלה מחדש")
    else:
        run(site["machine"], f"docker restart {q(container_name(site))}", timeout=180,
            what="הפעלה מחדש")
    return {"ok": True}


def status(site: dict) -> dict:
    """The container's own state, as the machine reports it — plus the SITE's state, which is not
    the same question (a running container serving a 500 is down as far as the owner is concerned;
    that answer comes from the uptime check, not from here)."""
    name = container_name(site)
    out = stdout_of(site["machine"], f"docker inspect {q(name)} 2>/dev/null", timeout=45)
    if not out.strip():
        return {"container": name, "present": False, "running": False, "state": "missing"}
    try:
        data = json.loads(out)[0]
    except (ValueError, IndexError):
        return {"container": name, "present": False, "running": False, "state": "unreadable"}
    st = data.get("State") or {}
    return {"container": name, "present": True, "running": bool(st.get("Running")),
            "state": st.get("Status"), "health": (st.get("Health") or {}).get("Status"),
            "started_at": st.get("StartedAt"), "restarts": data.get("RestartCount"),
            "image": (data.get("Config") or {}).get("Image"),
            "managed": (data.get("Config") or {}).get("Labels", {}).get(MANAGED_SENTINEL) == "1"}


def logs(site: dict, lines: int = 120) -> str:
    lines = max(1, min(2000, int(lines)))
    res = machines.exec_on(site["machine"],
                           f"docker logs --tail {lines} {q(container_name(site))} 2>&1", timeout=60)
    return (res.get("stdout") or "") + (("\n" + res["stderr"]) if res.get("stderr") else "")


def verify_local(site: dict) -> dict:
    """Ask the machine whether the site answers, from INSIDE the machine.

    Deliberately not "curl the public URL": on deploy day DNS, TLS and the edge are three
    independent things that can be wrong, and the one question the deploy can answer is whether the
    stack it just wrote serves. The public URL is the uptime check's job.
    """
    h = site.get("health_path") or "/"
    name = container_name(site)
    url = f"http://127.0.0.1:{int(site.get('port') or 80)}{h}"
    # The EXIT CODE is read from the remote shell and the body is only evidence.
    #
    # The first version of this piped wget straight into `head -c 300`, and a pipeline's exit status
    # is the LAST command's — so a 403 whose message fitted in 300 bytes came back as "ok" with a
    # non-empty body, and a deploy that served an empty directory reported success. (Found on
    # 2026-09-23 by deploying exactly that.) `--spider` asks the question without a body at all, and
    # the sample is fetched separately, best-effort.
    script = (f"wget -q --spider -T 10 {url} >/dev/null 2>&1; echo \"EXIT=$?\"; "
              f"wget -q -T 10 -O - {url} 2>/dev/null | head -c 200")
    res = machines.exec_on(site["machine"], f"docker exec {q(name)} sh -c {q(script)}", timeout=60)
    out = res.get("stdout") or ""
    code = None
    for line in out.splitlines():
        if line.startswith("EXIT="):
            code = line[5:].strip()
            break
    body = out.split("EXIT=", 1)[-1].split("\n", 1)[-1].strip() if "EXIT=" in out else out.strip()
    ok = code == "0"
    return {"ok": ok, "path": h, "bytes": len(body), "exit": code, "sample": body[:200],
            "error": None if ok else (res.get("reason") or res.get("stderr")
                                      or f"האתר החזיר שגיאה בתוך הקונטיינר (wget exit {code})")}


def remove(site: dict, purge_files: bool = False) -> dict:
    """Stop and forget a site. FILES ARE KEPT unless explicitly purged.

    The office's rule for anything destructive is the same everywhere: `on_uninstall: keep` is the
    default and the purge is a separate, named decision. A site's content is the one artifact here
    that cannot be re-derived from the record.
    """
    machine_id = site["machine"]
    out: dict = {"site": site["id"], "files_removed": False}
    if is_managed(site):
        machines.exec_on(machine_id, _compose(site, "down --remove-orphans"), timeout=180)
        out["stack_down"] = True
    else:
        machines.exec_on(machine_id, f"docker stop {q(container_name(site))}", timeout=120)
        out["stack_down"] = False
        out["note"] = "האתר נלקח כמו שהוא — הקונטיינר הופסק אבל הפריסה שלו לא נמחקה."
    if purge_files:
        root = site.get("root") or ""
        if root and root not in ("/", "/opt", "/opt/bina-sites"):
            run(machine_id, f"rm -rf {q(root)}", timeout=120, what="מחיקת תיקיית האתר")
            out["files_removed"] = True
    return out


# ── adoption and migration ───────────────────────────────────────────────────────────────────────
def inspect_existing(machine_id: str, container: str) -> dict:
    """What a container that ALREADY serves a site looks like, so the office can describe it without
    guessing: its image, mounts, network, port and — most useful — the Host rules in its labels."""
    out = stdout_of(machine_id, f"docker inspect {q(container)} 2>/dev/null", timeout=45)
    if not out.strip():
        return {"found": False, "container": container}
    try:
        d = json.loads(out)[0]
    except (ValueError, IndexError):
        return {"found": False, "container": container}
    labels = ((d.get("Config") or {}).get("Labels") or {})
    rules = [v for k, v in labels.items() if k.endswith(".rule")]
    hosts: list[str] = []
    for rule in rules:
        hosts += re.findall(r"Host\(`([^`]+)`\)", rule)
    mounts = [{"source": m.get("Name") or m.get("Source"), "dest": m.get("Destination"),
               "type": m.get("Type"), "mode": m.get("Mode")} for m in (d.get("Mounts") or [])]
    return {"found": True, "container": container,
            "image": (d.get("Config") or {}).get("Image"),
            "project": labels.get("com.docker.compose.project"),
            "working_dir": labels.get("com.docker.compose.project.working_dir"),
            "compose_files": labels.get("com.docker.compose.project.config_files"),
            "hosts": sorted(set(hosts)), "mounts": mounts,
            "networks": list(((d.get("NetworkSettings") or {}).get("Networks") or {}).keys()),
            "running": bool((d.get("State") or {}).get("Running"))}


def seed_content(site: dict, force: bool = False) -> dict:
    """Fill the pattern's directory from the content the site ALREADY has on that machine.

    This is the first step of migration and the reason migration is safe: the new stack is built from
    the very bytes the old one is serving (not from a fresh clone of whatever the default branch says
    today), so a site that moves into the pattern does not silently change content on the way. The
    source is `content.seed_from`, a directory ON THE MACHINE — the old deployment directory.

    Refuses to overwrite a non-empty target unless `force`: re-seeding a live site from an old
    directory is how a week of published changes disappears.
    """
    c = content_of(site)
    src = (c.get("seed_from") or "").rstrip("/")
    if not src:
        raise MachineError("אין content.seed_from להעתקה", machine=site.get("machine"), status=400)
    target = f"{site['root']}/{source_dir(site)}"
    if src == target:
        return {"ok": True, "skipped": "source and target are the same directory"}
    guard = f"mkdir -p {q(target)}; if [ -n \"$(ls -A {q(target)} 2>/dev/null)\" ]; then echo NONEMPTY; fi"
    exists = stdout_of(site["machine"], guard, timeout=60).strip()
    if "NONEMPTY" in exists and not force:
        return {"ok": False, "skipped": "התיקייה אינה ריקה — לא נדרסה", "target": target}
    cmd = (f"rsync -a --exclude node_modules --exclude .cache --exclude dist "
           f"{q(src + '/')} {q(target + '/')} 2>/dev/null || "
           f"cp -a {q(src + '/.')} {q(target + '/')}")
    run(site["machine"], cmd, timeout=300, what="העתקת תוכן האתר")
    size = stdout_of(site["machine"], f"du -sh {q(target)} 2>/dev/null | cut -f1", timeout=60)
    return {"ok": True, "from": src, "to": target, "size": size.strip()}


def log_source(site: dict) -> dict:
    """Where this site's visits are, in the order the pattern prefers:

    1. `<root>/logs/access.log` — a site the office renders writes its own JSON log there; that is
       the pattern and the cheap path (a file read over ssh).
    2. the container's stdout — an ADOPTED site (nginx's official image symlinks its access log to
       /dev/stdout) keeps its bytes in the engine's log store, and reading them is how a site the
       office did not render still gets statistics on day one, before anyone migrates it.
    """
    if is_managed(site):
        return {"kind": "file", "path": f"{site['root']}/logs/access.log"}
    return {"kind": "docker", "container": container_name(site)}


def read_logs(site: dict, offset: int, max_bytes: int = 4_000_000,
              since: int = 0) -> dict:
    """A window of this site's access log, plus the offset to ask from next time.

    The tail of a file, BY OFFSET and not by line count: log lines are appended while this runs, and
    counting from the end re-reads the same lines on every pass (double-counted visits) or skips the
    ones that arrived during the read. The offset is the cursor and it is advanced by exactly the
    number of bytes consumed.

    An ADOPTED site has no file to seek in — its nginx writes to the container's stdout — so the
    cursor there is a TIME (`since`, the epoch second of the last collection) and the engine's own
    log store is asked for what came after it.
    """
    src = log_source(site)
    machine_id = site["machine"]
    if src["kind"] == "file":
        path = src["path"]
        cmd = (f"test -f {q(path)} && wc -c < {q(path)} || echo 0")
        size = int((stdout_of(machine_id, cmd, timeout=45) or "0").strip().split()[0] or 0)
        if size < offset:                        # the file was rotated or truncated
            offset = 0
        if size <= offset:
            return {"lines": [], "offset": size, "size": size, "rotated": False}
        cmd = f"tail -c +{offset + 1} {q(path)} | head -c {max_bytes}"
        text = stdout_of(machine_id, cmd, timeout=90)
        consumed = len(text.encode("utf-8"))
        return {"lines": text.splitlines(), "offset": offset + consumed, "size": size,
                "rotated": False, "source": "file"}
    container = src["container"]
    since_arg = f"--since {int(since)} " if since else ""
    cmd = (f"docker logs --timestamps {since_arg}{q(container)} 2>&1 | tail -c {max_bytes}")
    text = stdout_of(machine_id, cmd, timeout=120)
    return {"lines": text.splitlines(), "offset": 0, "size": len(text), "source": "docker"}
