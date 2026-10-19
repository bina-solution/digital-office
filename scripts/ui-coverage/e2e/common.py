#!/usr/bin/env python3
"""
common.py — shared helpers for the per-app E2E UI-automation suites (Stage 2 of the ui-map task).

Design constraints these suites operate under:
  * The stack has no Docker Desktop / host-published ports for most services (console,
    supabase-db, incoming-documents, ...) — only n8n is published (127.0.0.1:5678). Every other
    service is reachable ONLY by its container IP on the traefik-network, exactly like
    scripts/ui-coverage/capture.py's own capture containers do. `container_ip()` below resolves
    that the same way `docker inspect` does.
  * Auth: console/drive/mail(view)/incoming-documents/my-docs all sit behind Authentik
    forward-auth (see manifest.yaml `hosts:`). The login recipe is PORTED VERBATIM from
    scripts/ui-coverage/capture.py's `ak_login`/`open_gated` — that pair is the one piece of this
    repo's UI automation independently proven to work end-to-end (62/62 views, 0 auth-wall
    rejections). Do not reinvent it.
  * incoming-documents' own BFF (the React SPA + its API) has NO auth check of its own once you
    are inside the container network — ported from scripts/ui-coverage/_status_edit_probe.py /
    _regression_probe.py, which already drive it directly at http://<container-ip>:8080 with no
    Authentik hop. That is deliberately reused rather than re-derived.
  * Backend assertions go through `psql()` (docker exec into the supabase-db / n8n-postgres
    containers) — no psycopg2 on the host, and this matches how apps/indox/hooks/test.py already
    asserts backend state.
  * Every row/file/folder/label a suite creates is tagged so a single cleanup pass can find and
    remove exactly what these suites made, never anything else. See QA_TAG / qa_name().
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"

# ── QA-data tagging convention ────────────────────────────────────────────────
# One run-scoped tag per invocation (stable within a run, unique across runs) so a partial
# failure's leftovers are still identifiable and removable by the same cleanup pass. Every
# object these suites create in the UI carries this string somewhere legible (a filename
# prefix, a company name suffix, a sync-registry label) — see qa_name().
QA_TAG = os.environ.get("QA_RUN_TAG") or f"QA_E2E_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def qa_name(label: str) -> str:
    """A human-legible name that is unambiguously ours: prefix + label + the run tag."""
    return f"{QA_TAG}__{label}"


def is_qa_name(name: str) -> bool:
    return bool(name) and "QA_E2E_" in name


# ── .env reader (mirrors apps/indox/hooks/test.py's env()) ───────────────────
_ENV_CACHE: dict[str, str] = {}


def env(key: str, default: str = "") -> str:
    if not _ENV_CACHE:
        for ln in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, _, v = ln.partition("=")
                _ENV_CACHE[k.strip()] = v.strip()
    return _ENV_CACHE.get(key, default)


DEPLOYMENT_NAME = env("DEPLOYMENT_NAME", "shlomo-laptop")
AK_USER = os.environ.get("AK_USER", "akadmin")
AK_PASS = os.environ.get("AK_PASS") or env("AUTHENTIK_BOOTSTRAP_PASSWORD")


# ── docker helpers ─────────────────────────────────────────────────────────────

def _docker(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def container(base: str) -> str:
    """<base>-<deployment> is the naming convention every service in this stack uses."""
    return f"{base}-{DEPLOYMENT_NAME}"


def container_ip(base: str, network: str = "traefik-network") -> str:
    name = container(base)
    r = _docker("inspect", name, "--format",
                "{{range $k,$v := .NetworkSettings.Networks}}{{$k}}={{$v.IPAddress}} {{end}}")
    if r.returncode != 0:
        raise RuntimeError(f"container {name!r} not found/running: {r.stderr.strip()}")
    nets = dict(p.split("=", 1) for p in r.stdout.split() if "=" in p)
    if network in nets:
        return nets[network]
    if nets:
        return next(iter(nets.values()))
    raise RuntimeError(f"container {name!r} has no network IP")


def psql(sql: str, db: str = "postgres", container_base: str = "supabase-db",
         user: str = "postgres", timeout: int = 30) -> str:
    """Run one statement via docker exec psql, tuples-only unaligned — returns raw stdout."""
    r = _docker("exec", container(container_base), "psql", "-U", user, "-d", db,
                "-t", "-A", "-c", sql, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def psql_one(sql: str, **kw) -> str | None:
    out = psql(sql, **kw).strip()
    return out.splitlines()[0].strip() if out else None


def psql_rows(sql: str, sep: str = "|", **kw) -> list[list[str]]:
    r = _docker("exec", container(kw.pop("container_base", "supabase-db")), "psql", "-U",
                kw.pop("user", "postgres"), "-d", kw.pop("db", "postgres"),
                "-t", "-A", "-F", sep, "-c", sql, timeout=kw.pop("timeout", 30))
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip() or r.stdout.strip()}")
    return [ln.split(sep) for ln in r.stdout.splitlines() if ln.strip()]


# ── console / view profile ─────────────────────────────────────────────────────

def console_ip() -> str:
    return container_ip("console")


CONSOLE_PORT = os.environ.get("UI_CONSOLE_PORT", "8000")


def console_base_url() -> str:
    """The console's URL by HOSTNAME, not raw IP — `console.localhost:8000`. Resolving that
    name to the right container IP is the browser's job (see `host_resolver_rules()` /
    `new_browser()`), exactly like run_capture.sh's `UI_HOST_RESOLVER="MAP *.localhost ${CIP}"`.
    Earlier draft of this file navigated straight to `http://<ip>:8000/` and dropped the
    hostname entirely — Authentik's session cookie and the app's own origin checks are scoped to
    `console.localhost`, so a raw-IP Host header risks a subtly different (and untested) code
    path than every other proven capture in this repo. Keep the hostname; resolve it instead."""
    return f"http://console.localhost:{CONSOLE_PORT}"


def host_resolver_rules() -> str:
    """Chromium --host-resolver-rules value that sends every *.localhost name straight at the
    console container's IP — the SAME rule run_capture.sh passes into the ui-capture containers.
    Every first-party app this suite touches is reached by hash-routing INSIDE the console
    (open_console_module), never by navigating to its own standalone *.localhost host, so mapping
    the wildcard at the console is correct and sufficient (see run_capture.sh's own comment on why
    a disabled/standalone app must NOT be part of this path)."""
    return f"MAP *.localhost {console_ip()}"


def incoming_documents_base_url() -> str:
    ip = container_ip("incoming-documents")
    port = os.environ.get("UI_INCOMING_PORT", "8080")
    return f"http://{ip}:{port}"


CHROME_CANDIDATES = [
    os.environ.get("UI_CHROME_BIN"),
    *[str(p) for p in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))],
]


def chrome_executable() -> str | None:
    for c in CHROME_CANDIDATES:
        if c and Path(c).exists():
            return c
    return None


# ── Authentik login (ported verbatim from scripts/ui-coverage/capture.py) ────

def on_ak_wall(page) -> bool:
    u = page.url or ""
    if "/flow/" in u or "outpost.goauthentik.io" in u:
        return True
    try:
        return bool(re.search(r"Welcome to authentik|Login to continue|Email or Username",
                              page.content(), re.I))
    except Exception:
        return False


def settle(page, ms: int = 1500):
    try:
        page.wait_for_load_state("networkidle", timeout=9000)
    except Exception:
        pass
    page.wait_for_timeout(ms)
    hydrate(page)


def hydrate(page, target: int = 60, budget_ms: int = 12000):
    last, stable = -1, 0
    for _ in range(int(budget_ms / 400)):
        try:
            n = page.evaluate("document.querySelectorAll('*').length")
        except Exception:
            return
        if n >= target and n == last:
            stable += 1
            if stable >= 2:
                return
        else:
            stable = 0
        last = n
        page.wait_for_timeout(400)


def ak_login(page) -> bool:
    for _ in range(3):
        try:
            page.get_by_role("textbox").first.fill(AK_USER)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1200)
            page.locator("input[type=password]").first.fill(AK_PASS)
            page.keyboard.press("Enter")
            page.wait_for_url(lambda u: "/flow/" not in u, timeout=15000)
            settle(page)
            return True
        except Exception:
            page.wait_for_timeout(1000)
    return False


def open_gated(page, url: str) -> bool:
    for _ in range(3):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        settle(page)
        if not on_ak_wall(page):
            return True
        ak_login(page)
    return not on_ak_wall(page)


def open_console_module(page, module: str, wait_ms: int = 2600):
    """Open console.localhost (resolved to the console container by the browser's own
    --host-resolver-rules — see new_browser()), authenticate if gated, then hash-route to a
    module and return the module's iframe as a frame_locator.

    The hash is baked into the URL passed to goto/open_gated — `base + "/#/m/" + module` — NOT
    set afterward via `page.evaluate("location.hash = ...")`. An earlier version of this function
    did the latter and it raced the console SPA's own router: navigating to console.localhost's
    bare "/" first, waiting, THEN setting location.hash landed on the console's own default first
    route (observed live 2026-08-06: the "מסך התקנה" / install screen) instead of routing to the
    requested module — a real bug in this helper, not in the app. Ported from
    scripts/ui-coverage/capture.py, which reaches every embedded module this same way and is
    proven end-to-end (62/62 views, 0 auth-wall rejections)."""
    base = console_base_url()
    full = f"{base}/#/m/{module}"
    ok = open_gated(page, full)
    if not ok:
        raise RuntimeError("could not get past the Authentik wall for console")
    # belt-and-braces, same as capture.py: clear any leftover modal/palette from a previous
    # same-document hash navigation before reading the frame.
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    settle(page, ms=wait_ms)
    return page.frame_locator("iframe")


# ── result bookkeeping (mirrors flow-qa.py's check()/RESULTS shape) ──────────

class Suite:
    def __init__(self, name: str):
        self.name = name
        self.results: list[tuple[str, bool, str]] = []

    def check(self, label: str, cond: bool, detail: str = "") -> bool:
        cond = bool(cond)
        self.results.append((label, cond, str(detail)))
        mark = "  PASS  " if cond else "  FAIL  "
        line = f"{mark}{self.name}/{label}"
        if detail and not cond:
            line += f" — {detail}"
        print(line, flush=True)
        return cond

    @property
    def passed(self) -> int:
        return sum(1 for _, ok, _ in self.results if ok)

    @property
    def failed_list(self):
        return [(n, d) for n, ok, d in self.results if not ok]

    def summary(self) -> str:
        n = len(self.results)
        return f"{self.name}: {self.passed}/{n} passed"


def poll_until(fn, tries: int = 30, interval_s: float = 2.0, what: str = ""):
    """Poll fn() until it returns a truthy value or we run out of tries; returns the last
    (possibly falsy) value. Used for 'watch it being processed automatically' style waits."""
    v = None
    for i in range(tries):
        v = fn()
        if v:
            return v
        time.sleep(interval_s)
    return v


def new_browser(playwright, headless: bool = True):
    exe = chrome_executable()
    args = ["--no-sandbox", "--disable-dev-shm-usage", "--ignore-certificate-errors", "--disable-gpu"]
    try:
        args.append(f"--host-resolver-rules={host_resolver_rules()}")
    except Exception as e:
        print(f"[common] host-resolver-rules unavailable ({e}) — console.localhost may not "
              f"resolve; falling back to whatever DNS this host has for *.localhost", flush=True)
    browser = playwright.chromium.launch(headless=headless, executable_path=exe or None, args=args)
    return browser


def new_context(browser, **kw):
    kw.setdefault("ignore_https_errors", True)
    kw.setdefault("viewport", {"width": 1600, "height": 950})
    kw.setdefault("locale", "he-IL")
    return browser.new_context(**kw)


ARTIFACTS = REPO_ROOT / "ci-artifacts" / "e2e"
ARTIFACTS.mkdir(parents=True, exist_ok=True)


# ── generic in-network HTTP call (mailapi, incoming-documents BFF, etc.) ─────
# These services have no auth of their own once you're inside traefik-network (see
# scripts/ui-coverage/_status_edit_probe.py's header comment for incoming-documents; mailapi is
# the same shape — an internal service the UI apps call, never exposed past Traefik itself).

def container_request(base: str, path: str, method: str = "GET", body: dict | None = None,
                       port: int = 80, timeout: int = 20):
    import urllib.request
    import urllib.error
    ip = container_ip(base)
    url = f"http://{ip}:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                  headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def mailapi_call(path: str, method: str = "GET", body: dict | None = None):
    """Direct call into the mailapi container (:8970) — the same backend mailview itself talks
    to. No auth once inside traefik-network. Used to verify mail arrival/labels independent of
    the UI, not merely re-reading what the UI already rendered."""
    return container_request("mailapi", path, method=method, body=body, port=8970)


# ── n8n (workflow engine) — trigger + poll a workflow by REST, ported from
#    scripts/_run_label_engine_test.py / apps/indox/hooks/test.py, the two places that already
#    prove this mechanism works live. ─────────────────────────────────────────

N8N_BASE = os.environ.get("N8N_TEST_BASE", "http://localhost:5678")


def _n8n_req(path: str, method: str = "GET", body: dict | None = None, cookie: str | None = None,
             timeout: int = 60):
    import urllib.request
    import urllib.error
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(N8N_BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getheaders(), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.headers.items(), e.read().decode("utf-8", errors="replace")


def n8n_login() -> str:
    hdrs, _ = _n8n_req("/rest/login", "POST", {
        "emailOrLdapLoginId": env("N8N_OWNER_EMAIL"),
        "password": env("N8N_OWNER_PASSWORD"),
    })
    cks = [v.split(";")[0] for k, v in hdrs if k.lower() == "set-cookie"]
    return "; ".join(cks)


def n8n_run_workflow(workflow_id: str, trigger_node: str, cookie: str | None = None) -> str | None:
    """POST /rest/workflows/<id>/run against the given manual-trigger node name. Returns the
    executionId (str) or None on failure. `trigger_node` must match the workflow's actual node
    name EXACTLY, including any typographic quote characters (n8n exports some with U+2019)."""
    ck = cookie or n8n_login()
    _, rb = _n8n_req(f"/rest/workflows/{workflow_id}/run", "POST", {
        "triggerToStartFrom": {"name": trigger_node, "data": {"main": [[{"json": {}}]]}},
    }, cookie=ck)
    try:
        return json.loads(rb)["data"]["executionId"]
    except Exception:
        return None


def n8n_wait_execution(execution_id: str, budget_s: int = 300, poll_s: int = 8) -> str:
    """Poll n8n-postgres directly for the execution's status (proven pattern from
    apps/indox/hooks/test.py). Returns the final status string ('success'/'error'/'timeout'/...)."""
    deadline = time.time() + budget_s
    status = "timeout"
    while time.time() < deadline:
        out = psql_one(
            f"SELECT status FROM execution_entity WHERE id={int(execution_id)};",
            container_base="n8n-postgres", user=env("POSTGRES_USER", "hacohen"), db="n8n",
        )
        if out and out not in ("running", "new", "waiting"):
            return out
        time.sleep(poll_s)
    return status
