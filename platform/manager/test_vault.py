"""The vault compiler — `reconcile.render_vault()` and the one rule it must never break.

The office's Obsidian vault is what an agent (and a person) reads first in a session, so a wrong
vault is worse than an empty one: it is believed. Three properties carry the whole item, and each
one is a case here:

  1. it is DERIVED and DETERMINISTIC — same declarations in, byte-identical notes out, so a diff is
     always a real change and never noise;
  2. it is SCOPED — a client office's vault holds that office and nothing else. The herd documents
     (the business's four machines, their addresses, every security finding) are `scope: herd` and
     render only where `DGO_OFFICE_ID` is one of the business's own offices (`herd.yaml:offices`);
     absent, unmatched, or an unreadable herd all mean OFFICE SCOPE ONLY. This fails closed;
  3. it carries no secret — `.env` is never read into a note, and the case plants a canary value in a
     temporary `.env` and asserts it reaches nothing.

Plus the two shapes the sync depends on: one note per ENABLED app, and a loud placeholder when a
declared source is missing (silence is how a vault gets quietly wrong).

Every catalog here is synthetic; nothing is started, and no real app manifest is read.

Run: python -m pytest platform/manager/test_vault.py -q
"""
import importlib.util
import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_mod_vault", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_mod_vault"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()

#: A value that exists nowhere else, planted in a temporary `.env` by the leak case.
CANARY = "canary-8f3e1d-should-never-be-in-a-note"


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    """The vault is rendered from a temp REPO and a temp `.env` — never the office it runs on.

    Without this a case that asserts "the herd is absent" would pass or fail depending on whether the
    machine happens to be one of the business's own offices, which is the exact question the scoping
    rule answers: a test that reads the machine tests the machine.
    """
    monkeypatch.setattr(rc, "REPO", tmp_path)
    monkeypatch.setattr(rc, "ENVFILE", tmp_path / ".env")
    monkeypatch.setattr(rc, "GEN", tmp_path / ".generated")
    rc.guard_envfile()
    yield tmp_path


# ── helpers: a synthetic repo, catalog and order ────────────────────────────────────────────────

def _app_dir(repo, aid):
    d = repo / "apps" / aid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _brief(repo, aid, text):
    d = _app_dir(repo, aid)
    (d / "AGENT.md").write_text(text, encoding="utf-8")
    return d


def _app(repo, aid, title="אפליקציה", layer=3, caps=(), alias=None, brief="brief"):
    d = _brief(repo, aid, f"# {aid}\n\n{brief}\n")
    routing = []
    if alias:
        routing = [{"module": {"alias": alias, "embed": True}}]
    return {"id": aid, "title": {"he": title}, "layer": layer, "_dir": d,
            "agent": {"context": "AGENT.md"}, "capabilities": list(caps), "routing": routing}


def _src(repo, rel, text="# doc\n\nbody\n"):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _manifest(repo, *, notes=(), herd=False, excluded=None):
    """The declaration the compiler reads. Written as YAML text, so the file format is tested too."""
    lines = ["version: 1", "notes:"]
    for to, frm, *rest in notes:
        scope = rest[0] if rest else "office"
        lines += [f'  - to: "{to}"', f"    from: {frm}", f"    scope: {scope}"]
    if not notes:
        del lines[1:]
    lines.append("generated: [index, inventory, apps, diagrams]")
    if herd:
        lines.append("herd_docs:")
        lines.append("  - { to: \"Herd/העדר.md\", from: ai/context/dgo-herd.md }")
    lines.append("excluded:")
    for path, why in (excluded or [("ai/context/research", "research drafts")]):
        lines += [f"  - path: {path}", f'    why: "{why}"']
    p = repo / "apps" / "obsidian"
    p.mkdir(parents=True, exist_ok=True)
    (p / "vault.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p / "vault.yaml"


def _herd(repo, offices=("hp-laptop", "macbook", "dell", "vps1")):
    p = repo / "apps" / "computers"
    p.mkdir(parents=True, exist_ok=True)
    text = ["offices:"]
    for o in offices:
        text += [f"  {o}:", f"    label: {o}"]
    (p / "herd.yaml").write_text("\n".join(text) + "\n", encoding="utf-8")
    return p / "herd.yaml"


def _env(repo, **kv):
    (repo / ".env").write_text("".join(f"{k}={v}\n" for k, v in kv.items()), encoding="utf-8")


def _tree(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


# ── 1. derived, deterministic, one note per enabled app ─────────────────────────────────────────

def test_render_is_deterministic_and_never_carries_a_clock(_hermetic):
    repo = _hermetic
    _src(repo, "ai/context/what-it-is.md")
    _manifest(repo, notes=[("Office/מה זו הלשכה.md", "ai/context/what-it-is.md")])
    cat = {"documents": _app(repo, "documents", alias="documents")}

    first = rc.render_vault(cat, ["documents"])
    first = {p: (rc.GEN / "vault" / p).read_bytes() for p in _tree(rc.GEN / "vault")}
    second = rc.render_vault(cat, ["documents"])
    second = {p: (rc.GEN / "vault" / p).read_bytes() for p in _tree(rc.GEN / "vault")}

    assert first == second, "two renders of the same declarations produced different bytes"
    # A wall-clock stamp in a note would make every diff a lie; the time lives on the vault side.
    for path, body in first.items():
        text = body.decode("utf-8")
        assert not any(k in text for k in ("T00:", "T12:", "generated_at")), path


def test_one_note_per_enabled_app_and_none_for_a_disabled_one(_hermetic):
    repo = _hermetic
    _manifest(repo, notes=[])
    cat = {
        "documents": _app(repo, "documents", title="מסמכים", alias="documents"),
        "esign": _app(repo, "esign", title="חתימות", alias="esign"),
        "indox": _app(repo, "indox", title="מסמכים נכנסים", alias="incoming"),
    }

    n = rc.render_vault(cat, ["documents", "esign"])          # indox is NOT in order = not enabled

    apps = [p for p in _tree(rc.GEN / "vault") if p.startswith("Apps/")]
    assert len(apps) == 2
    assert n["apps"] == 2
    joined = "\n".join((rc.GEN / "vault" / p).read_text(encoding="utf-8") for p in apps)
    assert "חתימות" in joined and "מסמכים" in joined
    assert "מסמכים נכנסים" not in joined, "a disabled app's brief reached the vault"
    assert rc.GEN.joinpath("vault/Apps/documents.md").is_file()


def test_a_generated_note_says_where_it_came_from(_hermetic):
    repo = _hermetic
    src = _src(repo, "ai/context/what-it-is.md", "# כותרת\n\nגוף המסמך\n")
    _manifest(repo, notes=[("Office/מה זו הלשכה.md", "ai/context/what-it-is.md")])

    rc.render_vault({"documents": _app(repo, "documents")}, ["documents"])

    note = (rc.GEN / "vault/Office/מה זו הלשכה.md").read_text(encoding="utf-8")
    assert note.startswith("---\n")
    assert "generated: true" in note
    assert "source: ai/context/what-it-is.md" in note
    assert any(line.startswith("source_sha: ") for line in note.splitlines())
    assert "גוף המסמך" in note                    # the body is verbatim, not summarised
    # The sha is the SOURCE's, so a reader can tell which revision of the doc it is holding.
    import hashlib
    assert hashlib.sha256(src.read_bytes()).hexdigest()[:16] in note


def test_a_manifest_is_written_that_names_every_note(_hermetic):
    repo = _hermetic
    _src(repo, "ai/context/what-it-is.md")
    _manifest(repo, notes=[("Office/מה זו הלשכה.md", "ai/context/what-it-is.md")])

    n = rc.render_vault({"documents": _app(repo, "documents")}, ["documents"])

    man = json.loads((rc.GEN / "vault/.vault-manifest.json").read_text(encoding="utf-8"))
    rendered = [p for p in _tree(rc.GEN / "vault") if p != ".vault-manifest.json"]
    assert sorted(man["notes"]) == rendered, "the manifest and the tree disagree"
    for path, row in man["notes"].items():
        assert len(row["rendered_sha256"]) == 64
        assert "source" in row
    assert n["notes"] == len(rendered)


# ── 2. scope: a client office gets no herd ──────────────────────────────────────────────────────

def test_the_herd_renders_on_a_business_office(_hermetic):
    repo = _hermetic
    _src(repo, "ai/context/dgo-herd.md", "# העדר\n\nvps1 הוא ההוב.\n")
    _herd(repo)
    _env(repo, DGO_OFFICE_ID="hp-laptop", DEPLOYMENT_NAME="hp")
    _manifest(repo, notes=[], herd=True)

    rc.render_vault({"documents": _app(repo, "documents")}, ["documents"])

    assert (rc.GEN / "vault/Herd/העדר.md").is_file()


@pytest.mark.parametrize("office_id", [None, "", "exampleu"])
def test_a_client_office_gets_no_herd_note_whatever_its_id_says(_hermetic, office_id):
    """The positive case above is what makes this one mean something: it is not passing by accident."""
    repo = _hermetic
    _src(repo, "ai/context/dgo-herd.md", "# העדר\n\nvps1 הוא ההוב.\n")
    _herd(repo)
    _env(repo, **({"DGO_OFFICE_ID": office_id} if office_id is not None else {"DEPLOYMENT_NAME": "x"}))
    _manifest(repo, notes=[], herd=True)

    rc.render_vault({"documents": _app(repo, "documents")}, ["documents"])

    assert not (rc.GEN / "vault/Herd").exists(), "a herd note reached a machine that is not in the herd"


def test_an_unreadable_herd_means_office_scope_only(_hermetic):
    repo = _hermetic
    _src(repo, "ai/context/dgo-herd.md")
    (repo / "apps" / "computers").mkdir(parents=True, exist_ok=True)
    (repo / "apps/computers/herd.yaml").write_text("this: is: not: a: list\n", encoding="utf-8")
    _env(repo, DGO_OFFICE_ID="hp-laptop")
    _manifest(repo, notes=[], herd=True)

    rc.render_vault({"documents": _app(repo, "documents")}, ["documents"])

    assert not (rc.GEN / "vault/Herd").exists()


def test_no_herd_document_reaches_a_client_vault(_hermetic):
    """Precise on purpose: what the scope rule keeps out is the herd DOCUMENTS — the business's four
    machines, their roles, their addresses and every security finding. An app's own brief may still
    name an office as an example (it is the app's authored text and it sits in the same checkout the
    client runs), and pretending otherwise would be a promise this gate cannot keep."""
    repo = _hermetic
    _src(repo, "ai/context/what-it-is.md", "# מה זו הלשכה\n\nהכלל: כל אפליקציה היא שירות.\n")
    _src(repo, "ai/context/dgo-herd.md", "# העדר\n\nmacbook 10.79.5.2 · vps1 · dell\n")
    _herd(repo)
    _env(repo, DGO_OFFICE_ID="exampleu")               # a client office
    _manifest(repo, notes=[("Office/מה זו הלשכה.md", "ai/context/what-it-is.md")], herd=True)

    rc.render_vault({"documents": _app(repo, "documents")}, ["documents"])

    tree = "\n".join((rc.GEN / "vault" / p).read_text(encoding="utf-8")
                     for p in _tree(rc.GEN / "vault"))
    for leak in ("macbook", "vps1", "10.79.5.2", "dell"):
        assert leak not in tree, f"a herd document reached a client's vault ({leak})"


# ── 3. no secret ───────────────────────────────────────────────────────────────────────────────

def test_no_env_value_reaches_a_note(_hermetic):
    repo = _hermetic
    _src(repo, "ai/context/what-it-is.md")
    _herd(repo)
    _env(repo, DGO_OFFICE_ID="hp-laptop", DEPLOYMENT_NAME="hp",
         CONNECTIONS_ROOT_KEY=CANARY, N8N_ENCRYPTION_KEY=CANARY)
    _manifest(repo, notes=[("Office/מה זו הלשכה.md", "ai/context/what-it-is.md")], herd=True)

    rc.render_vault({"documents": _app(repo, "documents")}, ["documents"])

    tree = "\n".join((rc.GEN / "vault" / p).read_text(encoding="utf-8")
                     for p in _tree(rc.GEN / "vault"))
    assert CANARY not in tree
    # …while the facts a person needs ARE there: which office this is.
    assert "hp" in tree


# ── 4. loud on a missing source, quiet on a good one ────────────────────────────────────────────

def test_a_missing_declared_source_is_a_loud_placeholder_not_a_gap(_hermetic):
    repo = _hermetic
    _manifest(repo, notes=[("Office/חסר.md", "ai/context/never-written.md")])

    rc.render_vault({"documents": _app(repo, "documents")}, ["documents"])

    note = (rc.GEN / "vault/Office/חסר.md").read_text(encoding="utf-8")
    assert "never-written.md" in note
    assert "חסר" in note or "missing" in note.lower()
    assert "generated: true" in note


def test_an_app_with_no_brief_is_named_and_does_not_abort_the_render(_hermetic):
    repo = _hermetic
    _manifest(repo, notes=[])
    d = _app_dir(repo, "silent")                     # no AGENT.md at all
    cat = {"silent": {"id": "silent", "title": {"he": "שותק"}, "layer": 3, "_dir": d,
                      "agent": {"context": "AGENT.md"}, "capabilities": [], "routing": []},
           "documents": _app(repo, "documents", alias="documents")}

    rc.render_vault(cat, ["silent", "documents"])

    note = (rc.GEN / "vault/Apps/silent.md").read_text(encoding="utf-8")
    assert "AGENT.md" in note and "שותק" in note
    assert (rc.GEN / "vault/Apps/documents.md").is_file()


def test_the_index_names_the_office_and_the_hand_written_area(_hermetic):
    repo = _hermetic
    _env(repo, DGO_OFFICE_ID="hp-laptop", DEPLOYMENT_NAME="hp")
    _manifest(repo, notes=[])

    rc.render_vault({"documents": _app(repo, "documents", alias="documents")}, ["documents"])

    start = (rc.GEN / "vault/00 - START HERE.md").read_text(encoding="utf-8")
    assert "hp" in start
    assert "Notes/" in start                       # where a person writes
    assert "Apps/documents.md" in start            # the reading order
    assert ".office/stale.txt" in start            # where a note that lost its source is listed
