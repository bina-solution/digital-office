"""Unit tests for the compiler's resolver — `reconcile.resolve()` and the disposition rules.

Thirteen lints guard the *apps*. `reconcile.py` itself has been guarded only by "does the stack come
up", which is a slow, expensive test that cannot distinguish "it resolved correctly" from "it
resolved wrongly and the wrong thing happened to boot". The resolver decides which apps run, in what
order, and which provider satisfies each capability — the three decisions everything downstream
inherits — so it gets tested directly.

The cases that matter most are the REFUSALS. A resolver that silently picks a provider, silently
drops one side of a conflict, or silently ignores a cycle produces a stack that boots and is wrong,
which is far more expensive than one that refuses to compile.

Every catalog here is synthetic: no manifests are read, no files are rendered, nothing is started.

Run: python -m pytest platform/manager/test_resolve.py -q
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_mod", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    """Point REPO at an empty dir so platform/legacy-capabilities.yaml cannot leak into a case.

    Without this, a test asserting "no provider is an error" would quietly pass or fail depending on
    whether the real repo happens to list that capability as legacy — the test would be measuring
    the repo, not the resolver.

    And the MACHINE's `.env` with it: ENVFILE is its own constant, so a case that renders a host read
    the office it ran on. Measured 2026-10-06: 54 passed on hp-laptop and 53 on the MacBook, whose
    `.env` carries a port (`console.localhost:8080`) — the same commit, one verdict per office.
    """
    monkeypatch.setattr(rc, "REPO", tmp_path)
    monkeypatch.setattr(rc, "ENVFILE", tmp_path / ".env")
    # ...and the product default: resolve() reads its `product_bindings:` (default_bindings), and the
    # real one binds `identity` — a case must measure the resolver, not the checkout it runs in
    monkeypatch.setattr(rc, "DEFAULT_STATE", tmp_path / "platform.state.default.yaml")
    # The module's own guard (reconcile.guard_envfile) refuses the repo's `.env` as a write target
    # until a temp REPO is named — the fixture's first line is exactly that, so every case below is
    # allowed to write, and a runner that skips this fixture is not.
    rc.guard_envfile()


def app(aid, layer=3, caps=(), use=()):
    """A manifest with only the fields resolve() reads."""
    return {"id": aid, "layer": layer, "capabilities": list(caps), "use": list(use)}


def cap(name, required_ops=(), optional_ops=()):
    return {"name": name, "required_ops": list(required_ops), "optional_ops": list(optional_ops)}


def use(capability, **kw):
    return {"capability": capability, **kw}


def catalog(*apps):
    return {a["id"]: a for a in apps}


def state(*enabled, **kw):
    st = {"apps": {aid: {"state": "enabled"} for aid in enabled}}
    st.update(kw)
    return st


def errors(diags):
    return [m for lvl, m in diags if lvl == "error"]


def test_console_websocket_passthrough_keeps_console_host_sso_and_strips_mount():
    route = {
        "service": "browser42-caddy",
        "port": 80,
        "auth": "sso",
        "emit_labels": False,
        "module": {
            "embed": True,
            "alias": "browser42",
            "passthrough": [{"path": "/websockify", "transport": "websocket"}],
        },
    }
    labels = rc.console_passthrough_labels("browser42", route, {"host": "console"})

    assert any("Host(`console.localhost`) && Path(`/a/browser42/websockify`)" in label
               for label in labels)
    assert any("Host(`${CONSOLE_BASE_URL:-console.${DEPLOYMENT_DOMAIN:-localhost}}`)" in label
               for label in labels)
    assert any(label.endswith("middlewares=browser42-console-websocket-0-strip,authentik@file")
               for label in labels)
    assert "traefik.http.middlewares.browser42-console-websocket-0-strip.stripprefix.prefixes=/a/browser42" in labels
    assert "traefik.http.services.browser42-caddy.loadbalancer.server.port=80" in labels

    # an office on a PORT: traefik matches Host() without the port, so the host is a literal there
    rc.envfile_write("CONSOLE_BASE_URL=console.example.test:8080\n")
    ported = rc.console_passthrough_labels("browser42", route, {"host": "console"})
    assert any("Host(`console.example.test`) && Path(`/a/browser42/websockify`)" in label for label in ported)
    assert not any("CONSOLE_BASE_URL" in label or ":8080" in label for label in ported)


def test_console_registry_contains_only_enabled_embedded_modules(tmp_path, monkeypatch):
    manifest = {
        "id": "cloud-tool",
        "routing": [{"module": {
            "name": "Cloud tool",
            "icon": "monitor",
            "group": "עסק",
            "alias": "cloud-tool",
            "embed": True,
            "url": "http://cloud-tool:8080/",
        }}],
    }
    monkeypatch.setattr(rc, "GEN", tmp_path / ".generated")

    rc.render_registries({"cloud-tool": manifest}, ["cloud-tool"])
    enabled = (tmp_path / ".generated" / "registry" / "console.modules.yaml").read_text(
        encoding="utf-8"
    )
    assert "id: cloud-tool" in enabled
    assert "group: עסק" in enabled
    assert "embed: /a/cloud-tool/" in enabled

    rc.render_registries({"cloud-tool": manifest}, [])
    disabled = (tmp_path / ".generated" / "registry" / "console.modules.yaml").read_text(
        encoding="utf-8"
    )
    assert "id: cloud-tool" not in disabled


def test_an_app_whose_edge_owns_a_path_of_the_console_origin_is_published_as_its_own_host(tmp_path, monkeypatch):
    """The catalog is what a PEER reads, and `embedded` there means "frame me under a path of YOUR
    console" — true only where this office's own console could.

    A passthrough is a route of THIS office's edge on the console's own host (browser42's
    `/websockify`), and a peer has no such route and no declaration to write one from: on the
    MacBook's console, hp-laptop's browser tile arrived as an unstyled `vnc.html` with every
    `/a/browser42.hp-laptop/app/…` asset empty and its websocket unanswered (measured 2026-10-09).
    On a host of its own, that page, its assets and its websocket are one origin — so this is how the
    app is published, and an app with no passthrough is unaffected.
    """
    cat = {
        "browser42": {"id": "browser42", "routing": [{"port": 80, "module": {
            "name": "דפדפן הלשכה", "icon": "monitor", "group": "עסק", "alias": "browser42",
            "embed": True, "url": "http://browser42-caddy:80/view/",
            "passthrough": [{"path": "/websockify", "transport": "websocket",
                             "strip_mount_prefix": True}]}}]},
        "drive": {"id": "drive", "routing": [{"port": 8975, "module": {
            "name": "דרייב", "icon": "folder", "group": "עסק", "alias": "drive", "embed": True}}]},
    }
    monkeypatch.setattr(rc, "GEN", tmp_path / ".generated")
    rc.render_registries(cat, ["browser42", "drive"])
    rows = json.loads((tmp_path / ".generated/registry/office.apps.json").read_text(encoding="utf-8"))
    kind = {r["alias"]: r["module"]["kind"] for r in rows["apps"]}
    assert kind == {"browser42": "external", "drive": "embedded"}


def test_an_app_framed_on_its_own_host_is_asked_before_it_is_framed(tmp_path, monkeypatch):
    """The tile names the sign-in question and the edge answers it on that host — where the host is
    a nested one, whose sign-in a frame cannot show. hp-laptop, 2026-10-06: the Plane window of an
    owner whose sign-in had run out was the browser's "refused to connect" page."""
    cat = {"console": {"id": "console", "routing": [{"host": "console", "port": 8000}]},
           "plane": {"id": "plane", "layer": 3, "routing": [{"host": "plane", "port": 80, "auth": "sso", "module": {
               "name": "Plane", "icon": "check", "group": "עסק", "alias": "plane", "embed": True, "external": True}}]}}
    order = ["console", "plane"]
    monkeypatch.setattr(rc, "GEN", tmp_path / ".generated")
    edge = tmp_path / "platform-base/traefik/config/zz-serve.yaml"
    edge.parent.mkdir(parents=True)

    def office(env_text):
        rc.envfile_write(env_text)
        rc.render_serve(cat, [], rc.framed_hosts(cat, order))
        rc.render_registries(cat, order)
        return ((tmp_path / ".generated/registry/console.modules.yaml").read_text(encoding="utf-8"),
                edge.read_text(encoding="utf-8") if edge.exists() else "")

    tile, routes = office("DEPLOYMENT_DOMAIN=localhost\n")
    assert "signed_in: /.dgo/signed-in" in tile and "enter: /.dgo/enter" in tile
    assert "Host(`plane.console.localhost`) && Path(`/.dgo/signed-in`)" in routes
    assert "Host(`plane.console.localhost`) && PathPrefix(`/.dgo/enter`)" in routes
    tile, routes = office("DEPLOYMENT_DOMAIN=example.co.il\n")      # beside the console: one site
    assert "signed_in" not in tile and "enter" not in tile and routes == ""


def test_on_a_real_domain_a_framed_tile_carries_the_origin_its_routers_serve(tmp_path, monkeypatch):
    """DGO-1274, staging 2026-11-03: the Meet tile framed `meet-start.console.<domain>` — the nested host
    the shell derives — which no router serves (traefik's default certificate, a broken frame), while
    the app's own routers serve `meet-start.<domain>`. On a real domain the tile names that origin: the
    declared host variable when there is one, else the router's own default; on `.localhost` it names
    none, and the shell keeps deriving (the frame port differs per browser there)."""
    cat = {"console": {"id": "console", "routing": [{"host": "console", "port": 8000}]},
           "meet": {"id": "meet", "layer": 3, "routing": [{"host": "meet-start", "port": 8080, "auth": "sso",
               "url_env": "MEET_START_BASE_URL", "sso": {"slug": "meet-start", "base_url_env": "MEET_START_BASE_URL"},
               "module": {"name": "פגישות וידאו", "icon": "monitor", "group": "עסק", "alias": "meet", "id": "meet",
                          "embed": True, "external": True, "url_env": "MEET_START_URL"}}]}}
    order = ["console", "meet"]
    monkeypatch.setattr(rc, "GEN", tmp_path / ".generated")

    def tile(env_text):
        rc.envfile_write(env_text)
        rc.render_registries(cat, order)
        mods = rc.yaml.safe_load((tmp_path / ".generated/registry/console.modules.yaml").read_text(encoding="utf-8"))
        return next(m for m in mods if m["id"] == "meet")

    assert tile("DEPLOYMENT_DOMAIN=staging.example.co.il\n")["url"] == "https://meet-start.staging.example.co.il"
    assert tile("DEPLOYMENT_DOMAIN=staging.example.co.il\nMEET_START_BASE_URL=meet.office.example\n")["url"] \
        == "https://meet.office.example"                                   # the declared host wins
    assert "url" not in tile("DEPLOYMENT_DOMAIN=localhost\n")              # derived by the shell there


# ── ordering ──────────────────────────────────────────────────────────────────

def test_provider_is_ordered_before_its_consumer():
    cat = catalog(app("db", caps=[cap("sql")]), app("web", use=[use("sql")]))
    order, diags = rc.resolve(cat, state("db", "web"))
    assert errors(diags) == []
    assert order.index("db") < order.index("web")


def test_hard_use_pulls_the_provider_in_even_when_not_enabled():
    """`requires` is a statement about the graph. An operator who enables `web` has, by saying so,
    asked for whatever `web` cannot run without."""
    cat = catalog(app("db", caps=[cap("sql")]), app("web", use=[use("sql")]))
    order, diags = rc.resolve(cat, state("web"))
    assert set(order) == {"db", "web"}
    assert any("pulled in as provider" in m for lvl, m in diags if lvl == "info")


def test_wants_does_not_pull_anything_in():
    """`wants` is the difference between "I need this" and "I'd use this if it were here". If it
    pulled providers in, nothing could ever express an optional integration."""
    cat = catalog(app("metrics", caps=[cap("host-metrics")]),
                  app("web", use=[use("host-metrics", strength="wants")]))
    order, diags = rc.resolve(cat, state("web"))
    assert order == ["web"]
    assert errors(diags) == []


def test_roots_seeds_the_closure_without_touching_state():
    """A CI lane wants "indox and whatever indox needs" — a question about the graph, which must not
    be answered by editing the persisted disposition."""
    cat = catalog(app("db", caps=[cap("sql")]), app("web", use=[use("sql")]), app("other"))
    order, _ = rc.resolve(cat, state("other"), roots=["web"])
    assert set(order) == {"db", "web"}


def test_unknown_root_is_fatal_not_a_diagnostic():
    cat = catalog(app("web"))
    with pytest.raises(SystemExit):
        rc.resolve(cat, state(), roots=["nope"])


# ── missing providers ─────────────────────────────────────────────────────────

def test_missing_provider_for_a_hard_use_is_an_error():
    cat = catalog(app("web", use=[use("sql")]))
    _, diags = rc.resolve(cat, state("web"))
    assert any("requires capability 'sql'" in e for e in errors(diags))


def test_legacy_capability_is_information_not_an_error(tmp_path, monkeypatch):
    """The bridge for un-migrated services. It must not fail the plan, and it must not add a node —
    the legacy lane already starts those."""
    (tmp_path / "platform").mkdir()
    (tmp_path / "platform" / "legacy-capabilities.yaml").write_text("sql: old-postgres\n",
                                                                   encoding="utf-8")
    monkeypatch.setattr(rc, "REPO", tmp_path)
    cat = catalog(app("web", use=[use("sql")]))
    order, diags = rc.resolve(cat, state("web"))
    assert errors(diags) == []
    assert order == ["web"]


# ── ops negotiation ───────────────────────────────────────────────────────────

def test_provider_missing_a_required_op_is_refused_by_name():
    """"It provides `mail`" is not enough. A consumer that calls `sendDocument` against a provider
    that has no such op fails at runtime, in production, on someone's real mail."""
    cat = catalog(app("thin", caps=[cap("mail", required_ops=["send"])]),
                  app("web", use=[use("mail", ops=["send", "sendDocument"])]))
    _, diags = rc.resolve(cat, state("web"))
    errs = errors(diags)
    assert any("lacks ops ['sendDocument']" in e for e in errs)


def test_optional_ops_count_toward_satisfying_a_consumer():
    cat = catalog(app("full", caps=[cap("mail", required_ops=["send"], optional_ops=["sendDocument"])]),
                  app("web", use=[use("mail", ops=["send", "sendDocument"])]))
    order, diags = rc.resolve(cat, state("web"))
    assert errors(diags) == []
    assert set(order) == {"full", "web"}


# ── provider selection: the ambiguity must never be guessed ───────────────────

def test_two_eligible_providers_with_no_rule_fails_and_names_both():
    """This is the case the old `ok[:1]` answered by picking whichever the dict yielded first —
    silent, non-deterministic, and unauditable."""
    cat = catalog(app("a", caps=[cap("llm-local")]), app("b", caps=[cap("llm-local")]),
                  app("web", use=[use("llm-local")]))
    order, diags = rc.resolve(cat, state("web"))
    errs = errors(diags)
    assert any("2 eligible providers" in e and "a, b" in e for e in errs)
    assert "a" not in order and "b" not in order      # nothing is guessed in


def test_state_binding_selects_the_provider():
    cat = catalog(app("a", caps=[cap("llm-local")]), app("b", caps=[cap("llm-local")]),
                  app("web", use=[use("llm-local")]))
    st = state("web"); st["bindings"] = {"llm-local": {"provider": "b"}}
    order, diags = rc.resolve(cat, st)
    assert errors(diags) == []
    assert "b" in order and "a" not in order


def test_a_binding_naming_an_ineligible_provider_is_an_error_not_a_fallback():
    """Falling back to "some other provider" would apply a configuration the operator never chose,
    which is worse than refusing: they would never learn their binding was wrong."""
    cat = catalog(app("a", caps=[cap("llm-local")]), app("b", caps=[cap("llm-local")]),
                  app("web", use=[use("llm-local")]))
    st = state("web"); st["bindings"] = {"llm-local": "ollama-typo"}
    order, diags = rc.resolve(cat, st)
    assert any("which is not " in e for e in errors(diags))
    assert "a" not in order and "b" not in order


def test_default_provider_breaks_the_tie_when_there_is_no_binding():
    cat = catalog(app("a", caps=[cap("llm-local")]), app("b", caps=[cap("llm-local")]),
                  app("web", use=[use("llm-local", default_provider="a")]))
    order, diags = rc.resolve(cat, state("web"))
    assert errors(diags) == []
    assert "a" in order and "b" not in order


def test_binding_outranks_default_provider():
    """The admin's recorded choice is the durable half of the decision; the app author's preference
    is a default. A default that could override the admin would not be a default."""
    cat = catalog(app("a", caps=[cap("llm-local")]), app("b", caps=[cap("llm-local")]),
                  app("web", use=[use("llm-local", default_provider="a")]))
    st = state("web"); st["bindings"] = {"llm-local": {"provider": "b"}}
    order, _ = rc.resolve(cat, st)
    assert "b" in order and "a" not in order


def _product_binds(tmp_path, provider):
    (tmp_path / "platform.state.default.yaml").write_text(
        f"schema_version: 1\nproduct_bindings:\n  llm-local: {provider}\napps: {{}}\n", encoding="utf-8")


def test_the_products_binding_decides_when_the_office_state_names_none(tmp_path):
    """An office upgraded from before a capability had a second provider binds nothing for it. The
    product's choice (platform.state.default.yaml `product_bindings:`) decides, and the plan says which
    rule chose — measured 2026-10-22: every upgrading office refused to plan until its state was edited."""
    _product_binds(tmp_path, "b")
    cat = catalog(app("a", caps=[cap("llm-local")]), app("b", caps=[cap("llm-local")]),
                  app("web", use=[use("llm-local")]))
    order, diags = rc.resolve(cat, state("web"))
    assert errors(diags) == []
    assert "b" in order and "a" not in order
    assert ("info", "llm-local: bound to 'b' by platform.state.default.yaml "
                    "(this office's platform.state.yaml binds none)") in diags


def test_the_office_binding_and_the_consumers_default_outrank_the_product(tmp_path):
    _product_binds(tmp_path, "b")
    cat = catalog(app("a", caps=[cap("llm-local")]), app("b", caps=[cap("llm-local")]),
                  app("web", use=[use("llm-local")]))
    st = state("web"); st["bindings"] = {"llm-local": "a"}
    order, _ = rc.resolve(cat, st)
    assert "a" in order and "b" not in order
    cat["web"] = app("web", use=[use("llm-local", default_provider="a")])
    order, _ = rc.resolve(cat, state("web"))
    assert "a" in order and "b" not in order


def test_a_product_binding_to_no_eligible_provider_decides_nothing(tmp_path):
    _product_binds(tmp_path, "zz")
    cat = catalog(app("a", caps=[cap("llm-local")]), app("b", caps=[cap("llm-local")]),
                  app("web", use=[use("llm-local")]))
    order, diags = rc.resolve(cat, state("web"))
    assert any("2 eligible providers" in e for e in errors(diags))
    assert "a" not in order and "b" not in order


def test_the_one_provider_the_office_runs_decides_before_the_product(tmp_path):
    """An office that enabled one provider chose it — a pre-release office running forward-auth alone
    keeps it, whatever the product binds."""
    _product_binds(tmp_path, "b")
    cat = catalog(app("a", caps=[cap("llm-local")]), app("b", caps=[cap("llm-local")]),
                  app("web", use=[use("llm-local")]))
    order, diags = rc.resolve(cat, state("web", "a"))
    assert errors(diags) == []
    assert "a" in order and "b" not in order
    assert ("info", "llm-local: 'a' is the one eligible provider this office runs") in diags
    # running both, the product's choice decides between them
    order, diags = rc.resolve(cat, state("web", "a", "b"))
    assert errors(diags) == []
    assert ("info", "llm-local: bound to 'b' by platform.state.default.yaml "
                    "(this office's platform.state.yaml binds none)") in diags


def test_a_provider_that_names_the_capability_twice_is_one_provider_it_runs(tmp_path):
    """Nothing refuses a manifest that lists one capability twice; counted twice, the one provider an
    office runs fell through to the product's binding (the second reader of b030bb32)."""
    _product_binds(tmp_path, "b")
    cat = catalog(app("a", caps=[cap("llm-local"), cap("llm-local")]), app("b", caps=[cap("llm-local")]),
                  app("web", use=[use("llm-local")]))
    order, diags = rc.resolve(cat, state("web", "a"))
    assert errors(diags) == []
    assert "a" in order and "b" not in order
    assert ("info", "llm-local: 'a' is the one eligible provider this office runs") in diags


def test_the_product_never_starts_a_provider_the_office_switched_off(tmp_path):
    """The second reader's case (2026-10-22): an office that runs neither, having switched the product's
    choice off, is refused as before — the product's binding never undoes the office's `enabled: false`."""
    _product_binds(tmp_path, "b")
    cat = catalog(app("a", caps=[cap("llm-local")]), app("b", caps=[cap("llm-local")]),
                  app("web", use=[use("llm-local")]))
    st = state("web"); st["apps"]["b"] = {"enabled": False}
    order, diags = rc.resolve(cat, st)
    assert any("2 eligible providers" in e for e in errors(diags))
    assert "a" not in order and "b" not in order
    # ...and running the other one, that one decides; the switched-off one stays off
    st["apps"]["a"] = {"state": "enabled"}
    order, diags = rc.resolve(cat, st)
    assert errors(diags) == []
    assert "a" in order and "b" not in order


def test_an_unmeetable_office_binding_is_refused_whatever_the_product_binds(tmp_path):
    """The office's own choice, when wrong, is reported — never quietly replaced by the product's."""
    _product_binds(tmp_path, "b")
    cat = catalog(app("a", caps=[cap("llm-local")]), app("b", caps=[cap("llm-local")]),
                  app("web", use=[use("llm-local")]))
    st = state("web"); st["bindings"] = {"llm-local": "zz"}
    order, diags = rc.resolve(cat, st)
    assert any("binds 'zz', which is not " in e for e in errors(diags))
    assert "a" not in order and "b" not in order


def test_ops_filtering_can_collapse_ambiguity_to_one_candidate():
    """Two providers, one of which cannot do the job, is not ambiguous."""
    cat = catalog(app("thin", caps=[cap("mail", required_ops=["send"])]),
                  app("full", caps=[cap("mail", required_ops=["send", "sendDocument"])]),
                  app("web", use=[use("mail", ops=["sendDocument"])]))
    order, diags = rc.resolve(cat, state("web"))
    # the thin provider is reported as unsuitable, but the plan still resolves to the full one
    assert "full" in order and "thin" not in order
    assert not any("eligible providers" in e for e in errors(diags))


# ── conflicts ─────────────────────────────────────────────────────────────────

def test_conflict_fails_the_plan_and_names_both_apps():
    """Gateway API is explicit that an implementation MUST NOT pick a winner. Dropping one side
    silently produces a stack the operator did not ask for and cannot see."""
    cat = catalog(app("edge-a", caps=[cap("edge")], use=[use("edge-b", strength="conflicts")]),
                  app("edge-b", caps=[cap("edge")]))
    order, diags = rc.resolve(cat, state("edge-a", "edge-b"))
    errs = errors(diags)
    assert any("edge-a" in e and "edge-b" in e and "conflict" in e for e in errs)
    assert "edge-a" in order and "edge-b" in order     # neither is silently dropped


def test_conflict_against_a_capability_catches_every_provider_of_it():
    cat = catalog(app("mine", use=[use("edge", strength="conflicts")]),
                  app("theirs", caps=[cap("edge")]))
    _, diags = rc.resolve(cat, state("mine", "theirs"))
    assert any("'mine' and 'theirs'" in e for e in errors(diags))


def test_a_conflict_with_an_absent_app_is_silent():
    cat = catalog(app("mine", use=[use("edge", strength="conflicts")]))
    _, diags = rc.resolve(cat, state("mine"))
    assert errors(diags) == []


# ── cycles ────────────────────────────────────────────────────────────────────

def test_cycle_is_reported_with_the_path_and_the_way_out():
    cat = catalog(app("a", caps=[cap("ca")], use=[use("cb")]),
                  app("b", caps=[cap("cb")], use=[use("ca")]))
    _, diags = rc.resolve(cat, state("a", "b"))
    errs = errors(diags)
    assert any("dependency CYCLE" in e and "weak" in e for e in errs)


def test_weak_dependency_breaks_the_cycle_without_removing_the_app():
    """The escape hatch has to actually work, or `dependency:'weak'` is advice the error message
    gives that the resolver ignores."""
    cat = catalog(app("a", caps=[cap("ca")], use=[use("cb")]),
                  app("b", caps=[cap("cb")], use=[use("ca", dependency="weak")]))
    order, diags = rc.resolve(cat, state("a", "b"))
    assert errors(diags) == []
    assert set(order) == {"a", "b"}


def test_after_false_drops_the_ordering_edge_but_keeps_the_dependency():
    cat = catalog(app("db", caps=[cap("sql")]), app("web", use=[use("sql", after=False)]))
    order, diags = rc.resolve(cat, state("web"))
    assert errors(diags) == []
    assert set(order) == {"db", "web"}        # still pulled in — `after` is about ORDER only


# ── dispositions ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entry,expected", [
    (None, "disabled"),
    ({}, "disabled"),
    ({"state": "enabled"}, "enabled"),
    ({"state": "ENABLED"}, "enabled"),          # case is not a disposition
    ({"state": " archived "}, "archived"),
    ({"state": "nonsense"}, "disabled"),        # an unknown word must never mean "run it"
    ({"enabled": True}, "enabled"),             # the legacy form still parses
    ({"enabled": False}, "disabled"),
    ({"state": "archived", "enabled": True}, "archived"),   # explicit state wins
])
def test_disposition(entry, expected):
    assert rc.disposition(entry) == expected


def test_archived_apps_do_not_run():
    """Archived keeps the data and the tile; it must not keep the container. If archived resolved as
    enabled, "reclaim the disk" would silently do nothing."""
    cat = catalog(app("a"), app("b"))
    st = {"apps": {"a": {"state": "enabled"}, "b": {"state": "archived"}}}
    assert rc.enabled_ids(st, cat) == {"a"}


def test_state_entries_with_no_manifest_are_reported_not_resolved():
    cat = catalog(app("a"))
    order, diags = rc.resolve(cat, state("a", "ghost"))
    assert order == ["a"]
    assert any("not yet migrated" in m for lvl, m in diags if lvl == "info")


# ── determinism ───────────────────────────────────────────────────────────────

def test_order_is_deterministic_across_catalog_insertion_order():
    """A render that reorders services between runs makes every diff unreadable and every rollback
    a guess. The resolver sorts at both the seed and the edge level; this proves it."""
    a = app("db", caps=[cap("sql")])
    b = app("cache", caps=[cap("kv")])
    c = app("web", use=[use("sql"), use("kv")])
    first, _ = rc.resolve({x["id"]: x for x in (a, b, c)}, state("web"))
    second, _ = rc.resolve({x["id"]: x for x in (c, b, a)}, state("web"))
    assert first == second


def test_the_diagnostics_come_in_the_twins_order_whatever_order_the_enabled_set_yields(monkeypatch):
    """The closure is walked from a SORTED seed, as the Go twin walks it (`sort.Strings(frontier)`, then
    pop from the end). Seeded from the set `enabled_ids` returns, the order of the `info` lines followed
    the order that set happened to yield, which is the process's string hashing (PYTHONHASHSEED): on the
    HP's state Python printed three `identity: bound to …` lines, the `n8n: pulled in …` line, then the
    fourth, while Go always printed its own, and `TestReadVerbsMatchPythonOnThisCheckout` failed on
    `services` (DGO-1000). The set is made to yield three different orders here, in-process, and every
    one must give the twin's order exactly — not merely one order (the second reader of DGO-1000)."""
    consumers = ["agent", "board", "chat", "drive", "mail", "site"]
    cat = catalog(app("authentik", caps=[cap("identity")]), app("forward-auth", caps=[cap("identity")]),
                  app("n8n", caps=[cap("workflow")]),
                  *[app(c, use=[use("identity")] + ([use("workflow")] if c == "chat" else []))
                    for c in consumers])
    st = state(*consumers, bindings={"identity": {"provider": "authentik"}})
    bound = "identity: bound to 'authentik' by platform.state.yaml"
    # sorted, popped from the end: site (pulls authentik in), mail, drive, chat (pulls n8n in), board, agent
    twin = [bound, "authentik: pulled in as provider of 'identity' for site", bound, bound, bound,
            "n8n: pulled in as provider of 'workflow' for chat", bound, bound]

    class Yields(set):
        """A set that yields its members in a chosen order — what a hash seed does to a real one."""
        def __init__(self, members, order):
            super().__init__(members)
            self.order = order

        def __iter__(self):
            return iter(self.order)

    for order in (consumers, consumers[::-1], consumers[3:] + consumers[:3]):
        monkeypatch.setattr(rc, "enabled_ids", lambda state, cat, _o=order: Yields(consumers, _o))
        plan, diags = rc.resolve(cat, st)
        assert [m for lvl, m in diags if lvl == "info"] == twin, order
        assert [m for lvl, m in diags if lvl == "error"] == []
        assert "authentik" in plan and "n8n" in plan and "forward-auth" not in plan


# ── the `remote:` block: what linked offices give this one ─────────────────────
#
# It arrives from ANOTHER office (dgo-extend's projection builds it from a peer's catalog), it is
# written into the file every render reads, and a block the planner refuses stops the whole office
# from compiling. So the writer is tested for the three things that keep that safe: nothing else in
# the file moves, a refused block is never written, and an unchanged one is not a write.

STATE_TEXT = """# the office's desired state — these comments ARE the documentation
apps:
  console:          { enabled: true }   # the shell

# what linked offices give this one (written by the control plane, never by hand)
remote:
- office: an-older-link
  apps: []
"""


def _block(office="macbook", alias="drive"):
    return [{"office": office, "label": {"he": "מקבוק", "en": "MacBook"}, "link": office,
             "address": "10.79.4.2", "commit": "", "fetched": 1, "link_port": 9004,
             "apps": [{"app": alias, "alias": alias, "port": 8975, "name": "קבצים", "name_en": "Drive",
                       "icon": "folder", "group": "כלים", "desc": "", "order": 5,
                       "module": {"kind": "embedded"}, "health": "/healthz"}]}]


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    path = tmp_path / "platform.state.yaml"
    path.write_text(STATE_TEXT, encoding="utf-8", newline="\n")
    monkeypatch.setattr(rc, "STATE", path)
    monkeypatch.setattr(rc, "load_catalog", lambda: {"console": {"routing": [{"host": "console"}]}})
    return path


def test_the_remote_block_is_replaced_and_every_other_byte_is_left_alone(state_file):
    changed, errs = rc.set_remote(_block())
    text = state_file.read_text(encoding="utf-8")
    assert (changed, errs) == (True, [])
    assert rc.remote_block() == _block()
    assert "an-older-link" not in text and text.count("remote:") == 1
    head = STATE_TEXT.split("remote:")[0]
    assert text.startswith(head)                       # the apps block and BOTH comments, untouched


def test_writing_the_block_that_is_already_there_is_not_a_write(state_file):
    rc.set_remote(_block())
    before = state_file.read_bytes()
    assert rc.set_remote(_block()) == (False, [])
    # ...and neither is the same declaration read a minute later: `fetched` is when a catalog was
    # read, not something this office declares, and it is new on every pass.
    later = _block()
    later[0]["fetched"] = 2
    assert rc.set_remote(later) == (False, [])
    assert state_file.read_bytes() == before
    moved = _block()
    moved[0]["link_port"] = 9002
    assert rc.set_remote(moved) == (True, [])              # a door that moved IS a change


@pytest.mark.parametrize("bad", [
    [{"office": "MAC BOOK", "apps": []}],                                   # not an office id
    [{"office": "macbook", "apps": "drive"}],                               # apps is not a list
    _block() + _block(),                                                    # one office twice
    {"office": "macbook"},                                                  # not a list at all
])
def test_a_block_the_planner_would_refuse_is_never_written(state_file, bad):
    changed, errs = rc.set_remote(bad)
    assert changed is False and errs, "a refusal names its reason"
    assert state_file.read_text(encoding="utf-8") == STATE_TEXT             # byte for byte


def test_an_empty_block_takes_the_declaration_away_and_keeps_the_rest(state_file):
    assert rc.set_remote([]) == (True, [])
    text = state_file.read_text(encoding="utf-8")
    assert "remote:" not in text.replace("# what linked", "") and "console:" in text
    assert rc.remote_block() == []


def test_a_legacy_serve_block_goes_with_the_block_it_was_replaced_by(state_file):
    state_file.write_text(STATE_TEXT + "\nserve:\n- office: vps1\n  apps: []\n", encoding="utf-8", newline="\n")
    assert rc.set_remote(_block()) == (True, [])
    assert "\nserve:" not in state_file.read_text(encoding="utf-8")


def test_nothing_on_stdin_is_an_error_and_never_an_empty_block(state_file, monkeypatch):
    """`remote-get | remote-set` with the reader dead erased a whole office's block once
    (2026-10-05). Empty input is a failed upstream; taking the declaration away is the JSON `[]`."""
    import io
    monkeypatch.setattr(sys, "argv", ["reconcile.py", "remote-set"])
    for nothing in ("", "   \n"):
        monkeypatch.setattr(sys, "stdin", io.StringIO(nothing))
        assert rc.main() == 2
        assert state_file.read_text(encoding="utf-8") == STATE_TEXT
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert rc.main() == 2 and state_file.read_text(encoding="utf-8") == STATE_TEXT
    monkeypatch.setattr(sys, "stdin", io.StringIO("[]"))
    assert rc.main() == 0 and rc.remote_block() == []


# ── this machine's .env, as the compiler reads it ──────────────────────────────

def test_an_env_value_is_read_with_its_references_resolved(tmp_path, monkeypatch):
    """The template spells hosts as `<name>.${DEPLOYMENT_DOMAIN}`, and every reader of .env resolves
    that — compose, lib.sh, the archiver. This one handed the raw text on, and a host derived from it
    reached authentik as `http://plane.console.${DEPLOYMENT_DOMAIN}` (hp-laptop, 2026-10-05)."""
    env = tmp_path / ".env"
    env.write_text("DEPLOYMENT_DOMAIN=example.test\n"
                   "CONSOLE_BASE_URL=console.${DEPLOYMENT_DOMAIN}\n"
                   "WITH_DEFAULT=${NOT_SET:-fallback}.x\n"
                   "NO_SUCH=a${NOT_SET}b\n"
                   "ITSELF=${ITSELF}\n"
                   "PLAIN='quoted value'\n", encoding="utf-8")
    monkeypatch.setattr(rc, "ENVFILE", env)
    assert rc._envfile_value("CONSOLE_BASE_URL") == "console.example.test"
    assert rc._envfile_value("WITH_DEFAULT") == "fallback.x"
    assert rc._envfile_value("NO_SUCH") == "ab"
    assert rc._envfile_value("PLAIN") == "quoted value"
    assert rc._envfile_value("ABSENT") is None
    assert "$" not in (rc._envfile_value("ITSELF") or "")        # ends, and leaves no reference behind
    cat = {"console": {"routing": [{"host": "console"}]}}
    assert rc.console_framed_host(cat, "plane") == "plane.console.example.test"


# ── the one writer of compiled files ───────────────────────────────────────────

def test_a_render_that_changes_nothing_writes_nothing(tmp_path):
    """Whatever watches a compiled file cannot tell a rewrite from a change: the sign-in worker
    re-applied its whole generated blueprint, twice, on every render (hp-laptop, 2026-10-05)."""
    import os
    out = tmp_path / "compiled.yaml"
    rc.write(out, "a: 1\nb: 2\n")
    assert out.read_bytes() == b"a: 1\nb: 2\n"                    # LF, whatever the platform
    os.utime(out, ns=(1_000, 1_000))                              # a time no write leaves behind
    rc.write(out, "a: 1\nb: 2\n")
    assert out.stat().st_mtime_ns == 1_000
    rc.write(out, "a: 1\n")
    assert out.read_bytes() == b"a: 1\n" and out.stat().st_mtime_ns != 1_000


def test_a_compiled_file_another_user_left_is_replaced(tmp_path):
    """The control plane compiles as root inside its container, and the owner's `bbox run` then met
    `remote.macbook.security.json` it could not open for writing (the Dell, 2026-11-01, DGO-1080).
    A file this user may not write, in a directory it owns, is replaced rather than refused."""
    import os
    import pytest
    if os.name != "posix" or os.geteuid() == 0:
        pytest.skip("root writes a 0444 file anyway, and Windows refuses to remove a read-only one")
    out = tmp_path / "remote.macbook.security.json"
    out.write_bytes(b"{}\n")
    out.chmod(0o444)                                              # as a root-owned 644 file is to its owner
    try:
        rc.write(out, '{"id": "security.macbook"}\n')
        assert out.read_bytes() == b'{"id": "security.macbook"}\n'
        assert os.access(out, os.W_OK)                            # the next render writes it in place
    finally:
        if out.exists():
            out.chmod(0o644)


# ── who cannot run without an app ──────────────────────────────────────────────

def test_an_app_is_required_by_the_enabled_apps_that_cannot_run_without_it():
    """drive requires supabase's object store; the office keeps supabase's services compiled while
    its own line says disabled — and the control plane has to be able to ask who that is for."""
    cat = catalog(app("store", caps=[cap("object-storage")]),
                  app("files", caps=[cap("drive")], use=[use("object-storage")]),
                  app("inbox", use=[use("drive")]),
                  app("notes", use=[use("object-storage", strength="wants")]),
                  app("alone"))
    assert rc.required_by("store", cat, state("files", "inbox", "notes", "alone")) == ["files", "inbox"]
    # through a provider that is itself switched off: inbox still pulls files, and files pulls store
    assert rc.required_by("store", cat, state("inbox")) == ["inbox"]
    # a soft use does not hold an app up, and nobody requires an app nobody uses
    assert rc.required_by("store", cat, state("notes", "alone")) == []
    assert rc.required_by("alone", cat, state("files", "inbox")) == []
    # an app does not require itself, and a line for an app that has no manifest is not a requirer
    assert rc.required_by("files", cat, {"apps": {"files": {"state": "enabled"}, "ghost": {"state": "enabled"}}}) == []


def test_the_required_by_verb_answers_one_json_list_and_refuses_an_app_it_does_not_know(monkeypatch, capsys):
    """The verb is what the control plane calls. Its first version read the catalog before it was
    loaded and crashed on every call — which the function's own test could not see."""
    cat = catalog(app("store", caps=[cap("object-storage")]), app("files", use=[use("object-storage")]))
    monkeypatch.setattr(rc, "load_catalog", lambda: cat)
    monkeypatch.setattr(rc, "load_state", lambda: state("files"))
    monkeypatch.setattr(sys, "argv", ["reconcile.py", "required-by", "--app", "store"])
    assert rc.main() == 0 and capsys.readouterr().out.strip() == '["files"]'
    monkeypatch.setattr(sys, "argv", ["reconcile.py", "required-by", "--app", "files"])
    assert rc.main() == 0 and capsys.readouterr().out.strip() == "[]"
    for argv in (["reconcile.py", "required-by", "--app", "ghost"], ["reconcile.py", "required-by"]):
        monkeypatch.setattr(sys, "argv", argv)
        assert rc.main() == 2 and capsys.readouterr().out == ""


# ── the sign-in outpost is given ONE provider for a host ───────────────────────

COMMITTED_BP = """\
version: 1
entries:
  - id: provider-console
    model: authentik_providers_proxy.proxyprovider
    identifiers: { name: Console Provider }
    attrs:
      mode: forward_single
      external_host: !Format ["%s://%s", !Env [AUTH_PROTOCOL, https], !Env [CONSOLE_BASE_URL, console.localhost]]
  - id: app-console
    model: authentik_core.application
    identifiers: { slug: console }
    attrs: { name: Console, provider: !KeyOf provider-console }
  - id: provider-console-local
    model: authentik_providers_proxy.proxyprovider
    identifiers:
      name: Console Local Provider
    attrs:
      mode: forward_single
      external_host: http://console.localhost
  - id: provider-elsewhere
    model: authentik_providers_proxy.proxyprovider
    identifiers: { name: Elsewhere Provider }
    attrs: { external_host: !Context a_host_this_compiler_cannot_tell }
  - id: provider-elsewhere-too
    model: authentik_providers_proxy.proxyprovider
    identifiers: { name: Elsewhere Too Provider }
    attrs: { external_host: !Context a_host_this_compiler_cannot_tell }
"""


def _office(tmp_path, monkeypatch, env_text):
    """A four-app office whose .env is `env_text`, with its sign-in blueprint compiled:
    (catalog, order, the generated blueprint's text)."""
    bp = tmp_path / "platform-base/authentik/blueprints"
    bp.mkdir(parents=True, exist_ok=True)
    (bp / "deployment-apps.yaml").write_text(COMMITTED_BP, encoding="utf-8")
    (bp.parent / "docker-compose.yml").write_text(
        "services:\n"
        "  authentik-server: {volumes: ['./blueprints:/blueprints/custom']}\n"
        "  authentik-worker: {volumes: [{type: bind, source: ./blueprints, target: /blueprints/custom}]}\n"
        "  authentik-postgres: {volumes: ['db:/var/lib/postgresql/data']}\n"
        "volumes:\n  db: {}\n", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text(env_text, encoding="utf-8")
    monkeypatch.setattr(rc, "ENVFILE", env)
    monkeypatch.setattr(rc, "COMMITTED_AUTHENTIK_BP", bp / "deployment-apps.yaml")
    cat = {
        "authentik": {"id": "authentik", "layer": 1, "compose": "docker-compose.yml", "_dir": bp.parent},
        # owned by the committed blueprint: nothing is generated for it, but its host is published
        "console": {"id": "console", "layer": 1, "routing": [{"host": "console", "auth": "sso", "port": 8000}]},
        # a base app the committed blueprint does not own: the compiler emits its pair
        "notes": {"id": "notes", "layer": 2, "title": {"he": "פתקים", "en": "Notes"},
                  "routing": [{"host": "notes", "auth": "sso", "port": 80}]},
        # an installable app that declares its own provider block
        "hello": {"id": "hello", "layer": 3, "routing": [{
            "host": "hello", "auth": "sso", "port": 80,
            "sso": {"slug": "hello", "display_name": "Hello", "base_url_env": "HELLO_BASE_URL",
                    "default_host": "hello.localhost", "local_twin": True}}]},
    }
    order = ["authentik", "console", "notes", "hello"]
    rc.render_authentik(cat, order)
    return cat, order, (bp / "zz-generated-apps.yaml").read_text(encoding="utf-8")


def _signin(tmp_path, monkeypatch, env_text):
    """(generated provider ids, the outpost's provider list as written) of that office."""
    text = _office(tmp_path, monkeypatch, env_text)[2]
    ids = [ln.split("provider-", 1)[1] for ln in text.splitlines() if ln.startswith("  - id: provider-")]
    bound = [ln.strip()[2:] for ln in text.split("      providers:\n", 1)[1].splitlines() if ln.strip()]
    return ids, bound


def _find(name):
    return f'!Find [authentik_providers_proxy.proxyprovider, [name, "{name}"]]'


def test_an_office_without_authentik_gets_no_sign_in_blueprint(tmp_path, monkeypatch):
    """forward-auth in its place (release 0.3.0): nobody would apply the file, so none is written, and
    the one an earlier render left is removed. The same office with authentik had one."""
    cat, order, _text = _office(tmp_path, monkeypatch, "DEPLOYMENT_DOMAIN=localhost\nAUTH_PROTOCOL=http\n")
    generated = tmp_path / "platform-base/authentik/blueprints/zz-generated-apps.yaml"
    assert generated.exists()
    assert rc.render_authentik(cat, [a for a in order if a != "authentik"]) == 0
    assert not generated.exists()


def test_an_office_on_localhost_port_80_gets_one_sign_in_provider_for_a_host(tmp_path, monkeypatch):
    """The app's own variable and its -local twin are the SAME host there, and two providers for one
    host freeze the outpost's refresh for ever (authentik 2024.12: the second one stops an
    application that is already stopped). hp-laptop, 2026-10-06: 15 such hosts, and no host declared
    after start-up was ever served without restarting the sign-in server."""
    ids, bound = _signin(tmp_path, monkeypatch, "DEPLOYMENT_DOMAIN=localhost\nAUTH_PROTOCOL=http\n")
    assert ids == ["notes", "hello"]                              # no twin is even written
    assert bound == [_find("Console Provider"),                   # the app's own, before its twin
                     _find("Elsewhere Provider"), _find("Elsewhere Too Provider"),
                     "!KeyOf provider-notes", "!KeyOf provider-hello"]
    # …and the same when the template spells the host through the domain, or names it outright
    for env in ("DEPLOYMENT_DOMAIN=localhost\nCONSOLE_BASE_URL=console.${DEPLOYMENT_DOMAIN}\n"
                "NOTES_BASE_URL=notes.${DEPLOYMENT_DOMAIN}\nHELLO_BASE_URL=hello.localhost\n", ""):
        assert _signin(tmp_path, monkeypatch, env) == (ids, bound)


def test_an_office_whose_hosts_differ_from_their_twins_keeps_both(tmp_path, monkeypatch):
    """A Mac's edge is on :8080 and a real office has a domain: there the twin is another host, a
    browser really arrives on it, and nothing about that office's blueprint may change."""
    both = (["notes", "notes-local", "hello", "hello-local"],
            [_find("Console Provider"), _find("Console Local Provider"),
             _find("Elsewhere Provider"), _find("Elsewhere Too Provider"),
             "!KeyOf provider-notes", "!KeyOf provider-notes-local",
             "!KeyOf provider-hello", "!KeyOf provider-hello-local"])
    mac = ("DEPLOYMENT_DOMAIN=localhost\nCONSOLE_BASE_URL=console.localhost:8080\n"
           "NOTES_BASE_URL=notes.localhost:8080\nHELLO_BASE_URL=hello.localhost:8080\n")
    assert _signin(tmp_path, monkeypatch, mac) == both
    assert _signin(tmp_path, monkeypatch, "DEPLOYMENT_DOMAIN=office.example\nAUTH_PROTOCOL=https\n") == both


def test_an_apps_host_is_written_into_the_blueprint_and_no_container_is_asked_for_it(tmp_path, monkeypatch):
    """Three containers apply the blueprint, and a new app's variable reached only the ones
    re-created since — the worker, first to apply, gave the new provider its `.localhost` default:
    the wrong host on an office with a domain, and the same host as the app's own twin. So the host
    is resolved once, by the compiler, and the sign-in containers carry no variable per app."""
    import yaml
    cat, order, text = _office(tmp_path, monkeypatch,
                               "DEPLOYMENT_DOMAIN=office.example\nHELLO_BASE_URL=hi.office.example:8443\n")
    assert '      external_host: !Format ["%s://%s", !Env [AUTH_PROTOCOL, https], "notes.office.example"]' in text
    assert '      external_host: !Format ["%s://%s", !Env [AUTH_PROTOCOL, https], "hi.office.example:8443"]' in text
    assert "      external_host: http://notes.localhost" in text       # the twin, another host here
    assert "_BASE_URL" not in text
    env = yaml.safe_load(rc.render_routing(cat, order))["services"]
    only = ["CONSOLE_BASE_URL=${CONSOLE_BASE_URL:-console.${DEPLOYMENT_DOMAIN:-localhost}}"]
    assert env["authentik-server"]["environment"] == only == env["authentik-worker"]["environment"]
    assert "authentik-postgres" not in env          # the database applies no blueprint, and is given nothing
    # …and switching an app off changes nothing about the sign-in containers
    without = yaml.safe_load(rc.render_routing(cat, ["authentik", "console"]))["services"]
    assert without["authentik-server"] == env["authentik-server"] and "authentik-postgres" not in without


def _gated(text):
    import json
    return json.loads(text.split("  gated_hosts: ", 1)[1].splitlines()[0])


def test_the_blueprint_states_the_hosts_it_gates(tmp_path, monkeypatch):
    """The readiness probe asks the outpost about the hosts of THIS render. It used to ask the
    database which hosts the last apply had bound — so a host compiled a second ago was not in the
    list, and "every gated host is served" was said of a render nobody had applied."""
    text = _office(tmp_path, monkeypatch, "DEPLOYMENT_DOMAIN=localhost\n")[2]
    assert _gated(text) == ["console.localhost", "hello.localhost", "notes.localhost"]
    assert text.index("context:") < text.index("  gated_hosts: ") < text.index("entries:")
    # one line per host the outpost is bound to — a Mac's ports and twins are hosts of their own,
    # and a provider whose host cannot be told (it stays bound) is not something to ask about
    mac = ("DEPLOYMENT_DOMAIN=localhost\nCONSOLE_BASE_URL=console.localhost:8080\n"
           "NOTES_BASE_URL=notes.localhost:8080\nHELLO_BASE_URL=hello.localhost:8080\n")
    assert _gated(_office(tmp_path, monkeypatch, mac)[2]) == [
        "console.localhost", "console.localhost:8080", "hello.localhost", "hello.localhost:8080",
        "notes.localhost", "notes.localhost:8080"]


def test_the_sentinel_is_recreated_for_what_only_it_applies_not_for_every_app(tmp_path, monkeypatch):
    """Its recreate trigger is a digest of its inputs. The compiled blueprint was one of them, so
    every app switched on re-created the sentinel and re-applied every blueprint: four of the
    4 min 22 s of an app's bring-up, minutes after its host was already being served."""
    a = tmp_path / "platform-base/authentik"
    (a / "blueprints").mkdir(parents=True)
    for name, body in (("bootstrap.sh", "one"), ("outpost-ready.py", "one"),
                       ("blueprints/deployment-apps.yaml", "one"), ("blueprints/zz-generated-apps.yaml", "one")):
        (a / name).write_text(body, encoding="utf-8")
    (tmp_path / ".generated").mkdir()
    monkeypatch.setattr(rc, "GEN", tmp_path / ".generated")
    monkeypatch.setattr(rc, "_compiled_services", lambda: {"authentik-bootstrap"})
    digest = lambda: rc._bootstrap_inputs_overlay().read_text(encoding="utf-8").split("bootstrap-inputs: ")[1]
    first = digest()
    (a / "blueprints/zz-generated-apps.yaml").write_text("an app was switched on", encoding="utf-8")
    assert digest() == first
    for name in ("bootstrap.sh", "outpost-ready.py", "blueprints/deployment-apps.yaml"):
        before = digest()
        (a / name).write_text("two", encoding="utf-8")
        assert digest() != before, name


def test_the_host_a_provider_is_on_this_machine(tmp_path, monkeypatch):
    """What the outpost files a provider under: host[:port], whatever the scheme — resolved the way
    the container that applies the blueprint will see it."""
    env = tmp_path / ".env"
    env.write_text("DEPLOYMENT_DOMAIN=office.example\nSET_BASE_URL=Set.Example:8443\n", encoding="utf-8")
    monkeypatch.setattr(rc, "ENVFILE", env)
    given = {"GIVEN_BASE_URL": "given.${DEPLOYMENT_DOMAIN:-localhost}", "SET_BASE_URL": "never-read.localhost"}
    fmt = lambda *a: ["%s://%s", ["AUTH_PROTOCOL", "https"], *a]
    assert rc.sso_host_here("http://plain.localhost", given) == "plain.localhost"
    assert rc.sso_host_here("https://plain.localhost/path", given) == "plain.localhost"
    assert rc.sso_host_here(fmt(["SET_BASE_URL", "x.localhost"]), given) == "set.example:8443"      # .env wins
    assert rc.sso_host_here(fmt(["GIVEN_BASE_URL", "x.localhost"]), given) == "given.office.example"  # then what the container is given
    assert rc.sso_host_here(fmt(["NOBODYS_BASE_URL", "x.localhost"]), given) == "x.localhost"         # then the blueprint's own default
    assert rc.sso_host_here(fmt("literal.console.localhost:8080"), given) == "literal.console.localhost:8080"
    # what cannot be told is "" — and the caller never drops a provider over it
    for unknown in (None, "", "no-scheme.localhost", ["%s://%s://%s", "a"], [], 7):
        assert rc.sso_host_here(unknown, given) == ""


def test_a_manifest_that_states_its_own_agent_door_is_believed():
    """The one door the derivation cannot find, stated by the app that has it (lnk-037/DGO-570).

    A linked office's `b42 task` is answered by browser42's task runner on 8766 (`/v1/task`), while
    the app's ONLY capability is its MCP on 8931 — so the derived door was 8931, a port that does not
    answer `/v1/task`, and every office that derived it opened a door onto nothing. The manifest is
    read from the real file on purpose: this is a claim about what `apps/browser42/app.json` says,
    and a copy of it here would go on passing after the field was deleted from the real one."""
    man = json.loads((HERE.parent.parent / "apps/browser42/app.json").read_text(encoding="utf-8"))
    assert ":8931" in man["capabilities"][0]["endpoint"]      # the browser MCP — not the door
    assert rc._agent_door(man, 80) == 8766                    # the task runner


def test_an_app_that_states_no_door_keeps_the_capability_derivation_exactly():
    """Every other app: the stated door is additive, so the derivation must not move at all."""
    bina_ds = app("bina-ds", caps=[{"name": "office-agent", "type": "protocol",
                                    "endpoint": "http://bina-ds:3081"}])
    assert rc._agent_door(bina_ds, 3080) == 3081
    assert rc._agent_door(bina_ds, 3081) == 0    # a capability on the UI's own port is no second door
    assert rc._agent_door(app("plain"), 80) == 0  # no capability at all, no door
    # A door that is not a port publishes NO door rather than the derived one: a linked office that
    # dials the wrong port is the failure this field exists to end.
    for broken in ("8766", 8766.0, True, 0, 65536, []):
        assert rc._agent_door({**app("x", caps=[{"name": "c", "endpoint": "http://x:8931"}]),
                               "agent_api_port": broken}, 80) == 0


def test_the_registry_names_who_answers_an_agent_door_when_the_app_states_it():
    """Sharing an app shares its screen, its API and its CLI out of the box (the owner, DGO-1018). The
    link delivers the agent port to a SERVICE, and the registry gave it only the UI's: browser42's
    API is its task runner, so a far `bbox b42 task` reached nothing (502). The app STATES who answers
    (the real browser42 manifest does), and it is never inferred: an endpoint's host would have named
    mail's mailapi, an API with no authentication of its own, and handed it to every office given mail
    (the second reader of DGO-1018). A row names it only when it is not the UI's own service."""
    man = json.loads((HERE.parent.parent / "apps/browser42/app.json").read_text(encoding="utf-8"))
    assert rc._agent_service(man) == "browser42-task-runner"
    bina_ds = app("bina-ds", caps=[{"name": "office-agent", "type": "protocol", "endpoint": "http://bina-ds:3081"}])
    assert rc._agent_service(bina_ds) == ""
    mail = app("mail", caps=[{"name": "mail", "endpoint": "http://mailapi:8970"}])
    assert rc._agent_service(mail) == ""                      # never inferred from the endpoint
    assert rc._agent_service(app("plain")) == ""
    stated = {**app("x", caps=[{"name": "c", "endpoint": "http://x-mcp:8931"}]), "agent_api_port": 8766}
    assert rc._agent_service(stated) == ""
    assert rc._agent_service({**stated, "agent_api_service": "x-runner"}) == "x-runner"
    # a name the link would refuse, and the link's own namespace, are never a delivery target
    for bad in ("1runner", "run_ner", "-runner", "run ner", "r", "localhost", 7, ["x"]):
        assert rc._agent_service({**stated, "agent_api_service": bad}) == "", bad
    # …and in the registry: the row carries it only where it differs from `service`
    routed = lambda m, svc, port: {**m, "routing": [{"host": m["id"], "port": port, "auth": "sso", "service": svc,
                                                     "module": {"alias": m["id"]}}]}
    rows = {r["app"]: r for r in rc._office_apps({"browser42": routed(man, "browser42-caddy", 80),
                                                    "bina-ds": routed(bina_ds, "bina-ds", 3080)},
                                                   ["browser42", "bina-ds"])["apps"]}
    assert (rows["browser42"]["agent_api_port"], rows["browser42"]["agent_api_service"]) == (8766, "browser42-task-runner")
    assert rows["bina-ds"]["agent_api_port"] == 3081 and "agent_api_service" not in rows["bina-ds"]


# ── DGO-945: an app's doors for linked offices, and where its workflows run ───────────────────────

def test_a_linked_capability_is_a_door_with_no_tile_and_never_the_agent_api():
    """The Dell's transcriber is offered to the HP as `speech`, a row with no tile; and a capability
    offered that way is not ALSO derived as the app's agent API (meet's recordings door would have
    become Meet's second door)."""
    asr = {"name": "speech", "type": "protocol", "endpoint": "http://apitools-asr:8987", "link": True}
    man = app("apitools", caps=[asr])
    rows = rc._link_rows("apitools", man)
    assert rows == [{"app": "apitools", "alias": "speech", "port": 8987, "service": "apitools-asr",
                     "health": "/healthz"}]
    assert rc._agent_door(man, 8080) == 0
    # …and in the registry the doors are a list of their own: `apps`, which everything that draws a
    # tile reads, is exactly what it was
    cat = {"apitools": {**man, "routing": [{"host": "apitools", "port": 8080, "auth": "sso"}]}}
    doc = rc._office_apps(cat, ["apitools"])
    assert doc["apps"] == [] and doc["services"] == rows
    assert "services" not in rc._office_apps({"x": app("x")}, ["x"])
    assert rc._link_rows("x", app("x", caps=[{**asr, "link": False}])) == []
    assert rc._link_rows("x", app("x", caps=[{**asr, "endpoint": "not a url"}])) == []


def test_a_workflow_reaches_an_app_of_a_linked_office_by_its_door_and_a_local_one_by_its_name():
    """The HP runs Plane and n8n; Meet runs on vps1 and the transcriber on the Dell. The Meet workflow
    imported into the HP's n8n reaches the Dell's `speech` and vps1's `recordings` through their link
    doors, and the HP's own Plane by its own name."""
    cat = {
        "apitools": app("apitools", caps=[{"name": "speech", "endpoint": "http://apitools-asr:8987", "link": True}]),
        "meet": app("meet", caps=[{"name": "recordings", "endpoint": "http://meet-start:8001", "link": True}]),
        "project-pln": {**app("project-pln"), "routing": [{"host": "plane", "port": 80,
                        "module": {"alias": "plane", "url": "http://project-pln:80"}}]},
    }
    served = [{"office": "dell", "link_port": 9005, "apps": [{"app": "ollama", "alias": "ollama", "port": 11434}],
               "services": [{"app": "apitools", "alias": "speech", "port": 8987}]},
              {"office": "vps1", "link_port": 9003, "apps": [{"app": "project-pln", "alias": "plane", "port": 80}],
               "services": [{"app": "meet", "alias": "recordings", "port": 8001}]}]
    assert rc.link_endpoints(cat, {"project-pln"}, served) == {
        "http://apitools-asr:8987": "http://speech.dell:9005",
        "http://meet-start:8001": "http://recordings.vps1:9003",
    }
    # …a capability not offered to links is never rewritten, and nothing is invented without a door
    assert rc.link_endpoints(cat, set(), []) == {}
    # An app that runs HERE keeps its own name — unless its entry names the office its link
    # capabilities are used from (`linked`): then those go there, and only to that office's door.
    assert "http://apitools-asr:8987" not in rc.link_endpoints(cat, {"apitools"}, served)
    assert rc.link_endpoints(cat, {"apitools", "meet", "project-pln"}, served,
                             {"apitools": {"state": "enabled", "linked": "dell"}}) == {
        "http://apitools-asr:8987": "http://speech.dell:9005"}
    assert rc.link_endpoints(cat, {"apitools"}, served, {"apitools": {"linked": "vps1"}}).get(
        "http://apitools-asr:8987") is None
    assert rc.linked_from({"linked": "Dell"}) == "dell" and rc.linked_from({"linked": "a b"}) == ""
    # …and with the app NOT running here, two offices giving the same door: the named one, not the first
    both = [{"office": "macbook", "link_port": 9002, "apps": [],
             "services": [{"app": "apitools", "alias": "speech", "port": 8987}]}] + served
    assert rc.link_endpoints(cat, set(), both)["http://apitools-asr:8987"] == "http://speech.macbook:9002"
    assert rc.link_endpoints(cat, set(), both, {"apitools": {"state": "disabled", "linked": "dell"}})[
        "http://apitools-asr:8987"] == "http://speech.dell:9005"
    # …and a named office that stops giving it is not replaced by another: the address stays, said once
    notes = []
    gone = [e for e in both if e["office"] != "dell"]
    got = rc.link_endpoints(cat, set(), gone, {"apitools": {"state": "disabled", "linked": "dell"}}, notes)
    assert "http://apitools-asr:8987" not in got and len(notes) == 1 and "dell gives no `speech`" in notes[0]


def test_a_provider_pulled_in_here_is_never_pointed_at_a_linked_office(monkeypatch):
    """Second reader, DGO-945: n8n declared disabled, INDOX enabled — INDOX pulls n8n in, so it runs
    here, and INDOX's calls to `n8n-webhook` must stay here although a linked office publishes its
    own `workflow-hooks`."""
    cat = {
        "n8n": app("n8n", caps=[{"name": "workflow", "type": "protocol", "endpoint": "http://n8n:5678"},
                                {"name": "workflow-hooks", "type": "protocol",
                                 "endpoint": "http://n8n-webhook:5678", "link": True}]),
        "indox": app("indox", use=[{"capability": "workflow", "strength": "requires"}]),
    }
    state = {"apps": {"n8n": {"state": "disabled"}, "indox": {"state": "enabled"}}}
    served = [{"office": "vps1", "link_port": 9003, "apps": [{"app": "bina-ds", "alias": "bina", "port": 3080}],
               "services": [{"app": "n8n", "alias": "workflow-hooks", "port": 5678}]}]
    monkeypatch.setattr(rc.serve, "plan", lambda st, c: (served, []))
    assert rc.link_endpoint_map(cat, state) == ({}, [])
    # …and once n8n really does not run here, the door is used
    state = {"apps": {"n8n": {"state": "disabled"}}}
    assert rc.link_endpoint_map(cat, state) == ({"http://n8n-webhook:5678": "http://workflow-hooks.vps1:9003"}, [])
    # a refused remote plan is an error, never an empty map that pushes the local names
    monkeypatch.setattr(rc.serve, "plan", lambda st, c: ([], ["remote[0]: refused"]))
    assert rc.link_endpoint_map(cat, state) == ({}, ["remote[0]: refused"])


def test_where_an_apps_workflows_run_is_each_offices_own_half():
    """Absent: where the app runs (the refusal that kept 69 INDOX workflows off an office without
    INDOX). `here`: an app of a linked office. Another office's name: not here although it runs here."""
    assert rc.workflows_here({"state": "enabled"}) is True
    assert rc.workflows_here({"state": "disabled"}) is False
    assert rc.workflows_here(None) is False
    assert rc.workflows_here({"state": "disabled", "workflows": "here"}) is True
    assert rc.workflows_here({"state": "enabled", "workflows": "hp-laptop"}) is False
    assert rc.workflows_here({"enabled": True}) is True


def test_the_state_writer_keeps_the_keys_it_does_not_own(tmp_path, monkeypatch):
    """Second reader, DGO-945: `bbox apps enable meet` rewrote `{…}` as `{ state, by }` and dropped
    `workflows: hp-laptop` — vps1 would then import Meet's workflows again beside the HP's."""
    path = tmp_path / "platform.state.yaml"
    path.write_text("apps:\n  meet:             { state: disabled, by: user, workflows: hp-laptop }   # note\n"
                    "  drive:            { enabled: true }\n", encoding="utf-8")
    monkeypatch.setattr(rc, "STATE", path)
    assert rc.set_disposition("meet", "enabled", by="cli") is True
    assert rc.set_disposition("drive", "disabled") is True
    assert path.read_text(encoding="utf-8") == (
        "apps:\n  meet:             { state: enabled, by: cli, workflows: hp-laptop }   # note\n"
        "  drive:            { state: disabled, by: user }\n")
    assert rc.workflows_here({"state": "enabled", "workflows": "hp-laptop"}) is False


def test_capability_provider_answers_with_a_provider_that_is_only_pulled_in(tmp_path):
    """DGO-993: the clean install of the public copy (2026-10-22) ran n8n only because bina-ds pulls it
    in (disabled in the state). `capability-provider --capability workflow` asked the enabled set, found
    no provider, and app-management never imported the agent's workflows. The verb answers from the
    resolved closure; an app that is disabled and pulled in by nobody still answers nothing. Asked of
    the real main(), as a process, in an office of its own (the compiler finds it from its own path)."""
    repo = tmp_path / "office"
    (repo / "platform" / "manager").mkdir(parents=True)
    (repo / "platform" / "schema").mkdir(parents=True)
    for f in ("reconcile.py", "serve.py"):
        shutil.copy(HERE / f, repo / "platform" / "manager" / f)
    shutil.copy(HERE.parent / "schema" / "app.schema.json", repo / "platform" / "schema" / "app.schema.json")
    for aid, extra in (("agent", {"use": [{"capability": "workflow"}]}),
                       ("engine", {"capabilities": [{"name": "workflow", "type": "service"}]}),
                       ("spare", {"capabilities": [{"name": "spare-cap", "type": "service"}]})):
        (repo / "apps" / aid).mkdir(parents=True)
        (repo / "apps" / aid / "app.json").write_text(json.dumps(
            {"id": aid, "layer": 3, "title": {"he": "x"}, "kind": "service", **extra}), encoding="utf-8")
    (repo / "platform.state.yaml").write_text(
        "schema_version: 1\napps:\n  agent: { enabled: true }\n  engine: { state: disabled, by: user }\n"
        "  spare: { state: disabled }\n", encoding="utf-8")

    def ask(capability):
        return subprocess.run([sys.executable, str(repo / "platform" / "manager" / "reconcile.py"),
                               "capability-provider", "--capability", capability],
                              cwd=repo, capture_output=True, text=True, env={**os.environ, "PYTHONUTF8": "1"})

    r = ask("workflow")
    assert (r.returncode, r.stdout) == (0, "engine\n")
    r = ask("spare-cap")
    assert (r.returncode, r.stdout) == (1, "")
    # ...and a REFUSED plan answers nothing, as enabled-apps refuses it (the second reader): the agent also
    # requires what nothing provides, and the closure would still name the engine
    (repo / "apps" / "agent" / "app.json").write_text(json.dumps(
        {"id": "agent", "layer": 3, "title": {"he": "x"}, "kind": "service",
         "use": [{"capability": "workflow"}, {"capability": "nothing-provides-this"}]}), encoding="utf-8")
    r = ask("workflow")
    assert (r.returncode, r.stdout) == (1, "") and "  ERROR " in r.stderr


def test_blueprints_lists_the_workflows_of_the_engine_where_it_is_only_pulled_in(tmp_path):
    """DGO-1001: `blueprints` asked whether an app is ENABLED, so n8n — pulled in by bina-ds, off in the
    state — was left out, and its own workflows never reached a fresh install (the clean install of the
    public copy measured 0 of 4). The workflow engine's own workflows follow it where the plan runs it.
    Another app the plan only pulls in (a library here; INDOX for chat on the HP) keeps its automations
    off, as does a disabled app nobody pulls in and an app whose state row names another office; a refused
    plan pulls nothing in. Asked of the real main(), as a process, in an office of its own."""
    repo = tmp_path / "office"
    (repo / "platform" / "manager").mkdir(parents=True)
    (repo / "platform" / "schema").mkdir(parents=True)
    for f in ("reconcile.py", "serve.py"):
        shutil.copy(HERE / f, repo / "platform" / "manager" / f)
    shutil.copy(HERE.parent / "schema" / "app.schema.json", repo / "platform" / "schema" / "app.schema.json")

    def app(aid, **extra):
        (repo / "apps" / aid / "flows").mkdir(parents=True, exist_ok=True)
        (repo / "apps" / aid / "app.json").write_text(json.dumps(
            {"id": aid, "layer": 3, "title": {"he": "x"}, "kind": "service", "blueprints": {"n8n": "flows"},
             **extra}), encoding="utf-8")
    app("agent", use=[{"capability": "workflow"}, {"capability": "lib-api"}])
    app("engine", capabilities=[{"name": "workflow", "type": "service"}])
    app("lib", capabilities=[{"name": "lib-api", "type": "service"}])
    app("spare")
    app("remote")
    (repo / "platform.state.yaml").write_text(
        "schema_version: 1\napps:\n  agent: { enabled: true }\n  engine: { state: disabled, by: user }\n"
        "  lib: { state: disabled, by: cli }\n  spare: { state: disabled }\n"
        "  remote: { state: enabled, workflows: vps1 }\n", encoding="utf-8")

    def ask():
        return subprocess.run([sys.executable, str(repo / "platform" / "manager" / "reconcile.py"), "blueprints"],
                              cwd=repo, capture_output=True, text=True, env={**os.environ, "PYTHONUTF8": "1"})

    r = ask()
    assert (r.returncode, r.stdout) == (0, "agent\tapps/agent/flows\nengine\tapps/engine/flows\n"), r.stderr
    # ...and a REFUSED plan keeps the enabled apps: its closure would name the engine, which only the
    # refused plan pulls in
    app("agent", use=[{"capability": "workflow"}, {"capability": "lib-api"}, {"capability": "nothing-provides-this"}])
    r = ask()
    assert (r.returncode, r.stdout) == (0, "agent\tapps/agent/flows\n"), r.stderr
