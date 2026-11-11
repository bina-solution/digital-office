#!/usr/bin/env python3
"""The publication rules of a host that carries an API — DGO-1557.

    python3 platform/manager/test_publish.py     (pytest, or the shim used for test_https.py)

`apps/supabase` served its API (rest, storage, and `/pg/` SQL through postgres-meta) on traefik's
`web` entrypoint with no middleware and NO https router at all: on Exampleu 2026-11-09 a keyless
request from the internet got `401` from `/rest/v1/` and `/pg/` — i.e. the API was ASKED, its keys
were the only lock — while the https addresses the app hands to browsers (`STORAGE_PUBLIC_URL`)
answered 404 for want of a router. The enumeration that preceded this (n8n's own database on vps1,
and the tree) found no SERVICE caller of the public host at all: `object-storage`/`data-api` point at
`http://supabase-kong:8000` inside the office network, and the only caller of the public name is a
browser following a storage URL. That is what makes "https only, published only when the office
declares it" a fix and not a break.

What is proven here:
  * `https_only` emits no `-http` router (the whole defect), and the `-local` twin survives;
  * `publish: "domain"` renders NO public router for a `.localhost` value — an office that publishes
    nothing says so by its host variable (Exampleu's `supabase.localhost`) — and a public router for a
    real name, over TLS, with the certificate resolver;
  * an office whose declaration is `.localhost` never gets a certresolver on that name (ACME would
    loop: DGO-901);
  * the tree itself: no app that declares `https_only` also routes its host on `web` in its own
    compose, and supabase writes no routers of its own any more (the compiler owns them).
"""
import importlib.util
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("reconcile_publish", REPO / "platform/manager/reconcile.py")
rec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rec)

ENTRY = {"host": "supabase", "port": 8000, "service": "kong", "url_env": "SUPABASE_BASE_URL",
         "auth": "none", "https_only": True, "publish": "domain"}


def routes(labels):
    """{router: {"entrypoints": …, "middlewares": …, "tls": …}} from an emitted label list."""
    out = {}
    for l in labels:
        m = re.match(r"traefik\.http\.routers\.([A-Za-z0-9_-]+)\.(rule|entrypoints|middlewares|tls\.certresolver|tls)=(.*)", l)
        if m:
            out.setdefault(m.group(1), {})[m.group(2)] = m.group(3)
    return out


OFFICE = "example.com"


def _with_host(monkeypatch, value, server=False):
    """The office's own name is `example.com`; `value` is what SUPABASE_BASE_URL holds."""
    monkeypatch.setattr(rec, "_envfile_value",
                        lambda v: {"SUPABASE_BASE_URL": value, "DEPLOYMENT_DOMAIN": OFFICE}.get(v))
    monkeypatch.setattr(rec, "_SERVER_OFFICE", server)


def test_a_local_host_publishes_nothing(monkeypatch):
    """Exampleu's declaration: SUPABASE_BASE_URL=supabase.localhost means "this office publishes no
    Supabase API". Only the machine's own twin is left."""
    _with_host(monkeypatch, "supabase.localhost", server=False)
    got = routes(rec.routing_labels("supabase", ENTRY))
    assert sorted(got) == ["supabase-local"], sorted(got)


def test_no_host_at_all_publishes_nothing(monkeypatch):
    _with_host(monkeypatch, None)
    assert sorted(routes(rec.routing_labels("supabase", ENTRY))) == ["supabase-local"]


def test_a_real_name_is_published_over_tls_and_never_on_web(monkeypatch):
    _with_host(monkeypatch, "supabase.example.com", server=True)
    got = routes(rec.routing_labels("supabase", ENTRY))
    assert "supabase-http" not in got, "https_only: there is no plain-http twin"
    https = got["supabase-https"]
    assert "websecure" in https["entrypoints"]
    assert https["tls"] == "true"
    assert https["tls.certresolver"], "a public name on a server office needs a certificate"
    assert "hsts@file" in https.get("middlewares", ""), "and the pin (DGO-1595)"


def test_a_server_office_keeps_no_localhost_door_for_an_api_host(monkeypatch):
    """The second reader's finding: `Host: supabase.localhost` on port 80 of a server office reached
    kong in cleartext, no middleware, keys only — the same posture as the reported defect, needing
    only a spoofed Host header. A laptop office keeps that twin; it is the ONLY door there."""
    _with_host(monkeypatch, "supabase.example.com", server=True)
    assert "supabase-local" not in routes(rec.routing_labels("supabase", ENTRY))
    _with_host(monkeypatch, "supabase.localhost", server=False)
    assert "supabase-local" in routes(rec.routing_labels("supabase", ENTRY))


def test_a_dotted_name_that_is_not_the_office_is_not_published(monkeypatch):
    """`supabase.internal` has a dot and belongs to nobody: publishing it would also order a
    certificate no authority can issue (the second reader's other finding)."""
    for value in ("supabase.internal", "supabase.example.com.evil.net", "192.168.16.100",
                  "supabase.example.com."):
        _with_host(monkeypatch, value, server=True)
        got = routes(rec.routing_labels("supabase", ENTRY))
        assert "supabase-https" not in got, f"{value!r} must not be published: {sorted(got)}"


def test_a_localhost_office_gets_no_certresolver_on_that_name(monkeypatch):
    """The other half of Exampleu's note: a `.localhost` name must never carry a resolver, or ACME
    loops on it (DGO-901)."""
    _with_host(monkeypatch, "supabase.localhost", server=False)
    labels = rec.routing_labels("supabase", ENTRY)
    assert not [l for l in labels if "certresolver" in l and "supabase.localhost" in l]


def test_https_only_is_off_by_default(monkeypatch):
    """A screen keeps its plain-http twin (the office edge answers 308 on a server office, DGO-1595);
    only an API host asks for https only."""
    _with_host(monkeypatch, "demo.example.com", server=True)
    plain = {"host": "demo", "port": 80, "url_env": "SUPABASE_BASE_URL", "auth": "sso"}
    assert "demo-http" in routes(rec.routing_labels("demo", plain))


def _routers_by_host(text):
    """{router: (rule, entrypoints)} for every hand-written router in a compose."""
    out = {}
    for name, key, value in re.findall(
            r"traefik\.http\.routers\.([A-Za-z0-9_-]+)\.(rule|entrypoints)=(.*)", text):
        out.setdefault(name, {})[key] = value
    return out


def _serves_host(rule, host, var):
    """Does this router's rule name the host — as a literal first label, or through `<APP>_BASE_URL`?"""
    for h in re.findall(r"Host\(`([^`]+)`\)", rule or ""):
        if h.startswith("${") and var in h:
            return True
        if h.split(".")[0] == host:
            return True
    return False


def test_no_app_routes_an_https_only_host_on_web_in_its_own_compose():
    """The defect's shape: a hand-written router on `web` for a host the manifest declared https-only.
    Judged per HOST — one file may carry several entries, and supabase's Studio entry is a screen that
    keeps its plain-http twin like every other sso app."""
    import json
    bad = []
    for man in sorted(REPO.glob("apps/*/app.json")) + sorted(REPO.glob("platform-base/*/app.json")):
        d = json.loads(man.read_text(encoding="utf-8"))
        compose = man.parent / (d.get("compose") or "docker-compose.yml")
        if not compose.exists():
            continue
        text = compose.read_text(encoding="utf-8")
        routers = _routers_by_host(text)
        for r in (d.get("routing") or []):
            if not r.get("https_only"):
                continue
            host = str(r.get("host") or d.get("id"))
            var = str(r.get("url_env") or (d.get("id") or "").upper().replace("-", "_") + "_BASE_URL")
            for name, spec in routers.items():
                if not _serves_host(spec.get("rule") or "", host, var):
                    continue
                eps = spec.get("entrypoints") or ""
                if re.search(r"\bweb\b", eps) and "websecure" not in eps:
                    bad.append(f"{compose.relative_to(REPO)}: router '{name}' serves '{host}' on web, "
                               f"and that entry declares https_only")
    assert not bad, "\n  ".join(bad)


def test_the_supabase_api_host_has_no_hand_written_router():
    """Studio's routers stay (a screen, sso, its own entry). The API host is declared in app.json and
    the compiler emits it — https only, and only where the office names a real host."""
    text = (REPO / "apps/supabase/docker-compose.yml").read_text(encoding="utf-8")
    for name, spec in _routers_by_host(text).items():
        assert not _serves_host(spec.get("rule") or "", "supabase", "SUPABASE_BASE_URL"), \
            (f"router '{name}' serves the API host by hand; it is declared in app.json and the compiler "
             f"emits it (https only, published only where the office names a real host)")
