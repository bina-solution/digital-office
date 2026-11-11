"""The vault-sources gate — it must FAIL on a document nobody declared, and pass on one that is.

A gate that cannot be shown to fail is not a gate (AGENTS.md, rule 8: prove it finds the problem in the
pre-fix tree and none after). These cases do exactly that, on temp directories, so the answer is the
gate's and not the repository's:

  * an undeclared document → exit 1, and the document is named;
  * the same document excluded with a reason → exit 0;
  * the same document declared as a note → exit 0;
  * a declaration pointing at a file nobody has → exit 1 (the other direction);
  * no manifest at all → exit 1 (undeclared sources cannot be checked).

Run: python -m pytest scripts/refactor/test_vault_sources_lint.py -q
"""
import importlib.util
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]

spec = importlib.util.spec_from_file_location("vsl", HERE / "vault-sources-lint.py")
vsl = importlib.util.module_from_spec(spec)
sys.modules["vsl"] = vsl
spec.loader.exec_module(vsl)

#: A source that really exists, so a "declared" case is not a false failure on the missing-source check.
REAL = "ai/context/README.md"


@pytest.fixture
def world(tmp_path):
    """Two documents, one of which a manifest below will declare and one it will not."""
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "known.md").write_text("# known\n", encoding="utf-8")
    (ctx / "extra.md").write_text("# extra\n", encoding="utf-8")
    return ctx


def manifest(tmp_path, text):
    p = tmp_path / "vault.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def run(tmp_path, ctx, man):
    return vsl.main(["--manifest", str(man), "--context", str(ctx)])


def test_an_undeclared_document_fails(world, tmp_path, capsys):
    man = manifest(tmp_path, f"""
version: 1
notes:
  - {{ to: "Office/known.md", from: {world.as_posix()}/known.md }}
excluded: []
""")
    rc = run(tmp_path, world, man)
    out = capsys.readouterr().out
    assert rc == 1
    assert "UNDECLARED" in out and "extra.md" in out
    assert "known.md" not in out.split("UNDECLARED")[1], "a declared document was also reported"


def test_the_same_document_excluded_with_a_reason_passes(world, tmp_path, capsys):
    man = manifest(tmp_path, f"""
version: 1
notes:
  - {{ to: "Office/known.md", from: {world.as_posix()}/known.md }}
excluded:
  - path: {world.as_posix()}/extra.md
    why: "a draft nobody meant to publish"
""")
    rc = run(tmp_path, world, man)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "OK" in out


def test_both_declared_passes(world, tmp_path, capsys):
    man = manifest(tmp_path, f"""
version: 1
notes:
  - {{ to: "Office/known.md", from: {world.as_posix()}/known.md }}
  - {{ to: "Office/extra.md", from: {world.as_posix()}/extra.md }}
excluded: []
""")
    assert run(tmp_path, world, man) == 0, capsys.readouterr().out


def test_a_declaration_whose_file_is_gone_fails(tmp_path, capsys):
    man = manifest(tmp_path, """
version: 1
notes:
  - { to: "Office/ghost.md", from: ai/context/never-written.md }
excluded: []
""")
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = run(tmp_path, empty, man)
    assert rc == 1
    assert "MISSING" in capsys.readouterr().out


def test_no_manifest_is_a_failure_not_a_pass(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = vsl.main(["--manifest", str(tmp_path / "nope.yaml"), "--context", str(empty)])
    assert rc == 1
    assert "no vault manifest" in capsys.readouterr().out


def test_the_offices_own_manifest_is_green():
    """The repository's own declaration, checked as it stands — the gate this commit turns on."""
    assert vsl.main(["--manifest", str(REPO / "apps/obsidian/vault.yaml"),
                     "--context", str(REPO / "ai/context")]) == 0
