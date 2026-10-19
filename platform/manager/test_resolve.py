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
import pathlib
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
    rc.ENVFILE.write_text("CONSOLE_BASE_URL=console.example.test:8080\n", encoding="utf-8")
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
        rc.ENVFILE.write_text(env_text, encoding="utf-8")
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
