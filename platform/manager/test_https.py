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
    assert chain["demo-https"] == "hsts@file,authentik@file", \
        "hsts FIRST: the sign-in's 302 ends the chain, and a header after it is never written"
    assert chain["demo-http"] == "authentik@file", "hsts pins a CERTIFICATE; a plain-http router has none"
    assert chain["demo-local"] == "authentik@file"


def test_a_local_office_pins_nothing(monkeypatch):
    _office(monkeypatch, False)
    labels = rec.routing_labels("demo", {"host": "demo", "port": 80, "auth": "sso",
                                         "sso": {"slug": "demo", "default_host": "demo.localhost"}})
    assert not any("hsts" in l for l in labels)


def test_every_websecure_router_in_the_tree_carries_hsts():
    """The static half of the pin: an app that writes its own labels must not be left out — and the pin comes
    FIRST in the chain, or a middleware that answers by itself (the sign-in's 302, a redirect) ends the chain
    before it and the visitor is never pinned (measured on vps1 2026-11-17, DGO-1595)."""
    missing = []
    for path in sorted((REPO / "apps").glob("*/docker-compose.yml")) + \
            sorted((REPO / "platform-base").glob("*/docker-compose.yml")):
        text = path.read_text(encoding="utf-8")
        routers = set(re.findall(r"traefik\.http\.routers\.([A-Za-z0-9_-]+)\.entrypoints=websecure", text))
        for r in routers:
            m = re.search(rf"traefik\.http\.routers\.{re.escape(r)}\.middlewares=(.*)", text)
            if not m or m.group(1).strip().split(",")[0] != "hsts@file":
                missing.append(f"{path.relative_to(REPO)}: {r}")
    for path in sorted((REPO / "platform-base/traefik/config").glob("*.yaml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*middlewares:\s*\[(.*)\]", line)
            if m and "hsts@file" in m.group(1) and m.group(1).split(",")[0].strip() != "hsts@file":
                missing.append(f"{path.relative_to(REPO)}: {line.strip()}")
    assert not missing, "websecure routers without hsts@file FIRST:\n  " + "\n  ".join(missing)


def _former_office(tmp_path, monkeypatch, env, server=True):
    monkeypatch.setattr(rec, "REPO", tmp_path)
    monkeypatch.setattr(rec, "_envfile_value", lambda var: env.get(var))
    (tmp_path / "platform-base/traefik/config").mkdir(parents=True)
    _office(monkeypatch, server)


def test_a_moved_office_sends_its_former_names_on(tmp_path, monkeypatch):
    """DGO-2013: vps1 moved to bina-solutions.digital-office.co.il, and every link already out names
    `*.staging.digital-office.co.il` — both entrypoints answer the old names with the redirect service."""
    _former_office(tmp_path, monkeypatch, {"DEPLOYMENT_DOMAIN": "bina-solutions.digital-office.co.il",
                                           "DGO_FORMER_DOMAINS": "staging.digital-office.co.il"})
    rec.render_https_redirect({}, APP)
    doc = (tmp_path / "platform-base/traefik/config/zz-https.yaml").read_text(encoding="utf-8")
    old = "HostRegexp(`^(?:.+\\.)?(?:" + re.escape("staging.digital-office.co.il") + ")$`)"
    assert "    dgo-former-http:\n      rule: " + old + " && PathPrefix(`/`) && !PathPrefix(`/.well-known/acme-challenge/`)" \
        in doc, "port 80 of an old name goes to https of the new one, and the ACME challenge is never redirected"
    assert "    dgo-former:\n      rule: " + old + "\n      entryPoints:\n      - websecure\n      priority: 2\n" in doc, \
        "on https the redirect is the LAST resort: a door an app still serves at its old name wins"
    assert "      - hsts\n      - port80-https\n      service: dgo-port80\n      tls: {}" in doc, \
        "hsts first; no resolver — the old names' certificates are the stored ones, which traefik renews"
    assert "    dgo-former-http:\n" in doc.split("    dgo-port80:\n")[1], "the office's own port-80 router stays, first"
    assert "priority: 1000000\n" in doc and "priority: 1000001\n" in doc
    assert "certResolver" not in doc, "a HostRegexp names no domain to order"


def test_a_former_name_never_redirects_the_office_to_itself(tmp_path, monkeypatch):
    """The office's current name, a non-name and a `.localhost` name are left out — the first would loop."""
    _former_office(tmp_path, monkeypatch, {"DEPLOYMENT_DOMAIN": "new.example.com",
                                           "DGO_FORMER_DOMAINS": "New.Example.com., bad_name, x.localhost, old.example.net, old.example.net"})
    assert rec.former_domains() == ["old.example.net"]
    rec.render_https_redirect({}, APP)
    doc = (tmp_path / "platform-base/traefik/config/zz-https.yaml").read_text(encoding="utf-8")
    assert "(?:old\\.example\\.net)" in doc and "new\\.example\\.com)$" not in doc.split("dgo-former-http")[1]


def test_a_name_the_office_moved_under_is_never_a_former_name(tmp_path, monkeypatch):
    """The second reader's loop: `example.com` as the former name of `bina.example.com` would match the office's
    own hosts at priority 2 — above drive's and esign's priority-1 UI routers — and send them to themselves."""
    _former_office(tmp_path, monkeypatch, {"DEPLOYMENT_DOMAIN": "bina.example.com",
                                           "DGO_FORMER_DOMAINS": "example.com, staging.bina.example.com"})
    assert rec.former_domains() == ["staging.bina.example.com"], "a name UNDER the current one is fine to leave"
    rec.render_https_redirect({}, APP)
    doc = (tmp_path / "platform-base/traefik/config/zz-https.yaml").read_text(encoding="utf-8")
    assert "HostRegexp(`^(?:.+\\.)?(?:staging\\.bina\\.example\\.com)$`)" in doc and "(?:example\\.com" not in doc


def test_closing_port_80s_redirect_keeps_the_former_names_where_the_app_is_enabled(tmp_path, monkeypatch):
    """`HTTPS_REDIRECT=off` stops the compiler pulling the app in; enabled by hand, it still answers the old names."""
    _former_office(tmp_path, monkeypatch, {"DEPLOYMENT_DOMAIN": "new.example.com", "HTTPS_REDIRECT": "off",
                                           "DGO_FORMER_DOMAINS": "old.example.net"})
    rec.render_https_redirect({}, APP)
    doc = (tmp_path / "platform-base/traefik/config/zz-https.yaml").read_text(encoding="utf-8")
    assert "dgo-port80:\n      rule:" not in doc and "dgo-former:" in doc and "address: http://https-redirect:8079" in doc


def test_no_former_name_without_the_answering_app_or_a_server_office(tmp_path, monkeypatch):
    env = {"DEPLOYMENT_DOMAIN": "new.example.com", "DGO_FORMER_DOMAINS": "old.example.net"}
    _former_office(tmp_path, monkeypatch, env)
    rec.render_https_redirect({}, [])
    doc = (tmp_path / "platform-base/traefik/config/zz-https.yaml").read_text(encoding="utf-8")
    assert "dgo-former" not in doc and "routers:" not in doc, "a forwardAuth to a container nobody runs is a 500"
    _office(monkeypatch, False)
    rec.render_https_redirect({}, APP)
    doc = (tmp_path / "platform-base/traefik/config/zz-https.yaml").read_text(encoding="utf-8")
    assert "dgo-former" not in doc


def test_an_office_that_never_moved_renders_what_it_did(tmp_path, monkeypatch):
    _former_office(tmp_path, monkeypatch, {"DEPLOYMENT_DOMAIN": "office.example.com"})
    rec.render_https_redirect({}, APP)
    doc = (tmp_path / "platform-base/traefik/config/zz-https.yaml").read_text(encoding="utf-8")
    assert "dgo-former" not in doc and doc.count("  routers:") == 1 and doc.count("  services:") == 1
