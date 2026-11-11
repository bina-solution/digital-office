"""The vault sync — what `apps/obsidian/vault-sync.sh` puts in a vault, and what it must never do.

The compiler renders `.generated/vault/`; this script carries it into the one vault folder. It runs at
every `bbox run` and on `./bbox obsidian sync`, which makes its behaviour a rule rather than a
convenience: a sync that is wrong is wrong on every bring-up, and a sync that touches a person's notes
is a data loss the office cannot undo.

The five cases, in the order they matter:

  1. a fresh vault is filled;
  2. a second pass writes NOTHING (that is what makes running it at every bring-up safe);
  3. a changed render writes exactly the note that changed;
  4. a note a person edited is LEFT ALONE and reported — never silently overwritten;
  5. a note whose source is gone is KEPT and reported stale — knowledge that is old beats knowledge
     that vanished. Nothing is ever deleted.

And the person's own area — `Notes/`, `Operatives/` — is seeded once and then never written again.

Run: python -m pytest apps/obsidian/test_vault_sync.py -q
"""
import json
import pathlib
import shutil
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE / "vault-sync.sh"


def _render(root, notes):
    """A stand-in for `.generated/vault/`: {relative path: text}, holding EXACTLY those notes.

    It clears the folder first, because that is what `reconcile.render_vault()` does: a note whose
    source is no longer declared is removed from `.generated/` (and KEPT in the vault — that is the
    stale case this file tests).
    """
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in notes.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    man = {"notes": {rel: {"source": "ai/context/x.md", "rendered_sha256": "0" * 64}
                     for rel in notes}}
    (root / ".vault-manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    return root


def run(generated, vault, *args):
    done = subprocess.run([str(SCRIPT), "--generated", str(generated), "--vault", str(vault), *args],
                          capture_output=True, text=True, timeout=120)
    return done


def summary(done):
    """The last `summary …` line, as a dict of ints."""
    line = next(l for l in reversed(done.stdout.splitlines()) if l.startswith("summary "))
    out = {}
    for bit in line.split()[1:]:
        k, _, v = bit.partition("=")
        out[k] = int(v)
    return out


@pytest.fixture
def world(tmp_path):
    gen, vault = tmp_path / "gen", tmp_path / "vault"
    _render(gen, {
        "00 - START HERE.md": "-->\n# start\n",
        "Apps/documents.md": "-->\n# documents v1\n",
        "Office/מה זו הלשכה.md": "-->\n# office\n",
    })
    return gen, vault


def test_a_fresh_vault_is_filled(world):
    gen, vault = world
    done = run(gen, vault)
    assert done.returncode == 0, done.stderr
    assert (vault / "Apps/documents.md").read_text(encoding="utf-8").endswith("# documents v1\n")
    assert (vault / "00 - START HERE.md").is_file()
    s = summary(done)
    assert s["wrote"] == 3 and s["edited"] == 0


def test_a_second_pass_writes_nothing_at_all(world):
    """The property that makes it safe at every bring-up: an unchanged render is zero writes."""
    gen, vault = world
    run(gen, vault)
    def notes(root):
        return {p: p.stat().st_mtime_ns for p in root.rglob("*")
                if p.is_file() and ".office" not in p.parts}
    before = notes(vault)
    done = run(gen, vault)
    after = notes(vault)
    assert before == after, "a no-change sync touched files"
    assert summary(done)["wrote"] == 0


def test_only_the_changed_note_is_written(world):
    gen, vault = world
    run(gen, vault)
    _render(gen, {"00 - START HERE.md": "-->\n# start\n",
                  "Apps/documents.md": "-->\n# documents v2\n",
                  "Office/מה זו הלשכה.md": "-->\n# office\n"})
    done = run(gen, vault)
    assert summary(done)["wrote"] == 1
    assert (vault / "Apps/documents.md").read_text(encoding="utf-8").endswith("# documents v2\n")


def test_a_note_a_person_edited_is_left_alone_and_reported(world):
    """The case whose failure is unforgivable: a derived note that a person corrected."""
    gen, vault = world
    run(gen, vault)
    person = vault / "Office/מה זו הלשכה.md"
    person.write_text("-->\n# office — הערה שלי\n", encoding="utf-8")

    done = run(gen, vault)

    assert "הערה שלי" in person.read_text(encoding="utf-8"), "the sync overwrote a person's edit"
    s = summary(done)
    assert s["edited"] == 1
    assert "skip-edited Office/מה זו הלשכה.md" in done.stdout


def test_a_note_whose_source_is_gone_is_kept_and_marked_stale(world):
    gen, vault = world
    run(gen, vault)
    _render(gen, {"00 - START HERE.md": "-->\n# start\n", "Apps/documents.md": "-->\n# documents v1\n"})

    done = run(gen, vault)

    assert (vault / "Office/מה זו הלשכה.md").is_file(), "a note was deleted"
    assert summary(done)["stale"] == 1
    stale = (vault / ".office" / "stale.txt").read_text(encoding="utf-8")
    assert "Office/מה זו הלשכה.md" in stale


def test_the_persons_area_is_seeded_once_and_never_again(world):
    gen, vault = world
    run(gen, vault)
    mine = vault / "Notes/רעיון.md"
    mine.parent.mkdir(parents=True, exist_ok=True)
    mine.write_text("שלי\n", encoding="utf-8")
    (vault / "Notes/רעיון.md").write_text("שלי, ערוך\n", encoding="utf-8")

    run(gen, vault)

    assert (vault / "Notes/רעיון.md").read_text(encoding="utf-8") == "שלי, ערוך\n"
    assert (vault / "Operatives/README.md").is_file(), "the operative template is part of arriving full"
    assert (vault / "Operatives/README.md").read_text(encoding="utf-8").strip(), "an empty template"


def test_a_missing_vault_folder_is_created_and_a_missing_source_is_not_an_error(tmp_path):
    done = run(tmp_path / "nothing-here", tmp_path / "v")
    assert done.returncode == 0, done.stderr
    assert "no rendered vault" in done.stdout or summary(done)["wrote"] == 0


def test_no_manifest_means_it_does_not_guess(world):
    """Without `.vault-manifest.json` the script has no idea what it wrote last — so it refuses to
    overwrite: it reports and stops, rather than treating the vault as its own to rewrite."""
    gen, vault = world
    (gen / ".vault-manifest.json").unlink()
    done = run(gen, vault)
    assert done.returncode == 0
    assert "no manifest" in done.stdout
    assert not (vault / "Apps/documents.md").exists()
