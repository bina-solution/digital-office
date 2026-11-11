#!/usr/bin/env python3
"""The port-80 answer and the HSTS pin — DGO-1595.

Two things are proven here, and both are the reason the change is not three lines of traefik config:

  * traefik v3 cannot answer 308 (measured 2026-11-09 on v3.3: `redirectScheme`/`redirectRegex`/the
    entrypoint redirection give 301 or 302, and the v3.5 reference has no status field), so port 80
    is answered by a forwardAuth'd service whose 308 traefik copies verbatim. That router exists only
    on a SERVER office — a `*.localhost` office has no certificate and port 80 IS the office — and its
    rule excludes `/.well-known/acme-challenge/`, or every renewal on the office would fail.
  * every router on the `websecure` entrypoint carries `hsts@file`, and the middleware is written on
    every office (a router whose middleware does not resolve is DROPPED whole by traefik).

    python3 -m pytest platform/manager/test_https.py -q
"""
import importlib.util
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("reconcile_https", REPO / "platform/manager/reconcile.py")
rec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rec)


def _office(monkeypatch, server):
    monkeypatch.setattr(rec, "_SERVER_OFFICE", server)


def test_a_dotted_domain_with_a_resolver_is_a_server_office(monkeypatch):
    monkeypatch.setattr(rec, "_SERVER_OFFICE", None)
    monkeypatch.setattr(rec, "_envfile_value", lambda var: {"DEPLOYMENT_DOMAIN": "office.example.com"}.get(var))
    assert rec.server_office() is True


def test_localhost_is_not_a_server_office(monkeypatch):
    monkeypatch.setattr(rec, "_SERVER_OFFICE", None)
    monkeypatch.setattr(rec, "_envfile_value", lambda var: {"DEPLOYMENT_DOMAIN": "localhost"}.get(var))
    assert rec.server_office() is False


def test_an_empty_resolver_turns_the_redirect_off_on_a_real_domain(monkeypatch):
    monkeypatch.setattr(rec, "_SERVER_OFFICE", None)
    monkeypatch.setattr(rec, "_envfile_value",
                        lambda var: {"DEPLOYMENT_DOMAIN": "office.example.com", "TRAEFIK_CERTRESOLVER": ""}.get(var))
    assert rec.server_office() is False


APP = ["https-redirect"]


def test_the_redirect_router_is_rendered_for_a_server_office(tmp_path, monkeypatch):
    monkeypatch.setattr(rec, "REPO", tmp_path)
    monkeypatch.setattr(rec, "_envfile_value",
                        lambda var: {"DEPLOYMENT_DOMAIN": "office.example.com"}.get(var))
    (tmp_path / "platform-base/traefik/config").mkdir(parents=True)
    _office(monkeypatch, True)
    rec.render_https_redirect({}, APP)
    doc = (tmp_path / "platform-base/traefik/config/zz-https.yaml").read_text(encoding="utf-8")
    assert "dgo-port80:" in doc
    assert "PathPrefix(`/`) && !PathPrefix(`/.well-known/acme-challenge/`)" in doc, \
        "the ACME challenge must not be redirected"
    assert "HostRegexp(`^(?:.+\\.)?office\\.example\\.com$`)" in doc, \
        "the rule names THIS office — a bare catch-all also swallowed `<app>.localhost`"
    assert "priority: 1000000" in doc, "an app's -http router must never outrank the redirect"
    assert "address: http://https-redirect:8079" in doc
    assert "trustForwardHeader: false" in doc, "the Location comes from traefik, never from a client"
    assert "stsSeconds: 31536000" in doc


def test_the_router_needs_the_app_enabled(tmp_path, monkeypatch):
    """A forwardAuth to a container the office does not run answers 500 on EVERY port-80 request —
    a worse failure than the cleartext it replaces (the second reader's blocker, 2026-11-09)."""
    monkeypatch.setattr(rec, "REPO", tmp_path)
    monkeypatch.setattr(rec, "_envfile_value",
                        lambda var: {"DEPLOYMENT_DOMAIN": "office.example.com"}.get(var))
    (tmp_path / "platform-base/traefik/config").mkdir(parents=True)
    _office(monkeypatch, True)
    rec.render_https_redirect({}, [])
    doc = (tmp_path / "platform-base/traefik/config/zz-https.yaml").read_text(encoding="utf-8")
    assert "dgo-port80" not in doc, "no router when the answering app is not in the compiled set"
    assert "stsSeconds: 31536000" in doc


def test_the_owner_can_close_the_redirect(tmp_path, monkeypatch):
    """A name with a dot is not a certificate: an internal `.local` office, or a staging name whose
    ACME cannot issue, would 308 into an https origin nobody serves. `HTTPS_REDIRECT=off` in .env is
    the way out, and it must not take the HSTS definition with it."""
    (tmp_path / "platform-base/traefik/config").mkdir(parents=True)
    monkeypatch.setattr(rec, "REPO", tmp_path)
    monkeypatch.setattr(rec, "_envfile_value",
                        lambda var: {"DEPLOYMENT_DOMAIN": "office.example.com",
                                     "HTTPS_REDIRECT": "off"}.get(var))
    _office(monkeypatch, True)
    rec.render_https_redirect({}, APP)
    doc = (tmp_path / "platform-base/traefik/config/zz-https.yaml").read_text(encoding="utf-8")
    assert "dgo-port80" not in doc
    assert "stsSeconds: 31536000" in doc


def test_a_local_office_gets_the_middleware_but_no_router(tmp_path, monkeypatch):
    monkeypatch.setattr(rec, "REPO", tmp_path)
    (tmp_path / "platform-base/traefik/config").mkdir(parents=True)
    _office(monkeypatch, False)
    rec.render_https_redirect({}, APP)
    doc = (tmp_path / "platform-base/traefik/config/zz-https.yaml").read_text(encoding="utf-8")
    assert "stsSeconds: 31536000" in doc, "the middleware is defined everywhere: a dangling name drops a router"
    assert "dgo-port80" not in doc, "port 80 IS the office on a `.localhost` machine — nothing may redirect it"


def test_tls_routers_carry_hsts_and_plain_http_ones_do_not(monkeypatch):
    _office(monkeypatch, True)
    labels = rec.routing_labels("demo", {"host": "demo", "port": 80, "auth": "sso",
                                         "sso": {"slug": "demo", "default_host": "demo.localhost"}})
    chain = {re.match(r"traefik\.http\.routers\.([^.]+)\.middlewares=(.*)", l).group(1):
             re.match(r"traefik\.http\.routers\.([^.]+)\.middlewares=(.*)", l).group(2)
             for l in labels if ".middlewares=" in l}
    assert chain["demo-https"] == "authentik@file,hsts@file"
    assert chain["demo-http"] == "authentik@file", "hsts pins a CERTIFICATE; a plain-http router has none"
    assert chain["demo-local"] == "authentik@file"


def test_a_local_office_pins_nothing(monkeypatch):
    _office(monkeypatch, False)
    labels = rec.routing_labels("demo", {"host": "demo", "port": 80, "auth": "sso",
                                         "sso": {"slug": "demo", "default_host": "demo.localhost"}})
    assert not any("hsts" in l for l in labels)


def test_every_websecure_router_in_the_tree_carries_hsts():
    """The static half of the pin: an app that writes its own labels must not be left out."""
    missing = []
    for path in sorted((REPO / "apps").glob("*/docker-compose.yml")) + \
            sorted((REPO / "platform-base").glob("*/docker-compose.yml")):
        text = path.read_text(encoding="utf-8")
        routers = set(re.findall(r"traefik\.http\.routers\.([A-Za-z0-9_-]+)\.entrypoints=websecure", text))
        for r in routers:
            m = re.search(rf"traefik\.http\.routers\.{re.escape(r)}\.middlewares=(.*)", text)
            if not m or "hsts@file" not in m.group(1):
                missing.append(f"{path.relative_to(REPO)}: {r}")
    assert not missing, "websecure routers without hsts@file:\n  " + "\n  ".join(missing)
