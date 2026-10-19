"""Unit tests for the compiler's `office:` writer — `reconcile.set_office()` / `office_block()`.

The install wizard writes ONE record about the office (its name, animal, hue, the terms it accepted,
when it was installed) and the console decides from it whether a visitor meets the wizard or the
shell. The writer is the compiler's, like `set_disposition` and `set_remote`, so the three things
those two promise are asserted here for this block too: validated before anything is written, text
surgery that keeps every comment, and a no-op that says so.

Every file here is synthetic — a temp state file, a temp palette, a temp icon set.

Run: python -m pytest platform/manager/test_office.py -q
"""
import importlib.util
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_office_mod", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_office_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()

STATE_TEXT = """# platform.state.yaml — DESIRED STATE. The only file the console writes.
#
# a comment that explains the model and must survive every write
schema_version: 1

apps:
  # ── layer 1 ──
  traefik:          { enabled: true }   # the edge
  console:          { enabled: true }
"""


@pytest.fixture
def office(tmp_path, monkeypatch):
    """A repo with a state file, a palette that declares three hues, and an icon set with two animals."""
    (tmp_path / "platform-base/bina-ui").mkdir(parents=True)
    (tmp_path / "platform-base/bina-ui/theme-tokens.css").write_text(
        ":root{--bg:#f3f5f7;--olive:#56693f;--lime:#a9b84c;--muted:#6a7068}\n", encoding="utf-8")
    (tmp_path / "platform-base/bina-ui/bina-icons.js").write_text(
        "const BINA_ICONS = {\n  home:      '<path d=\"M3 10\"/>',\n"
        "  elephant:  '<circle cx=\"12\" cy=\"10\" r=\"6\"/>',\n  deer:      '<path d=\"M12 21\"/>',\n"
        "  'file-text': '<path d=\"M15 2\"/>',\n};\n", encoding="utf-8")
    state = tmp_path / "platform.state.yaml"
    state.write_text(STATE_TEXT, encoding="utf-8")
    monkeypatch.setattr(rc, "REPO", tmp_path)
    monkeypatch.setattr(rc, "STATE", state)
    return state


GOOD = {"name": "הלשכה בחיפה", "animal": "deer", "hue": "lime",
        "terms_version": "2026-10-09.1", "terms_accepted_at": "2026-10-09T18:00:00Z",
        "installed_at": "2026-10-09T18:01:00Z"}


def test_an_office_that_never_ran_its_wizard_has_no_record(office):
    assert rc.office_block() == {}


def test_the_wizard_writes_the_record_and_every_comment_survives(office):
    changed, errs = rc.set_office(GOOD)
    assert (changed, errs) == (True, [])
    text = office.read_text(encoding="utf-8")
    assert "# a comment that explains the model and must survive every write" in text
    assert "traefik:          { enabled: true }   # the edge" in text
    assert rc.office_block() == GOOD
    # the compiler's own reader still sees the apps block exactly as before
    assert rc.load_state()["apps"]["console"] == {"enabled": True}


def test_a_second_write_replaces_the_block_and_keeps_what_it_was_not_told(office):
    rc.set_office(GOOD)
    changed, errs = rc.set_office({"animal": "elephant", "hue": "muted"})
    assert (changed, errs) == (True, [])
    rec = rc.office_block()
    assert rec["animal"] == "elephant" and rec["hue"] == "muted"
    assert rec["terms_accepted_at"] == GOOD["terms_accepted_at"]      # kept, not asked about
    assert office.read_text(encoding="utf-8").count("\noffice:") == 1   # one block, not two


def test_writing_what_is_already_there_changes_nothing(office):
    rc.set_office(GOOD)
    before = office.read_text(encoding="utf-8")
    assert rc.set_office(GOOD) == (False, [])
    assert office.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("fields, said", [
    ({"colour": "#ff0000"}, "unknown field"),
    ({"hue": "red"}, "not one of the palette's families"),
    ({"hue": "plum"}, "not one of the palette's families"),        # a legal name the palette does not declare
    ({"animal": "unicorn"}, "not a glyph"),
    ({"animal": "Deer"}, "not a glyph"),
    ({"terms_accepted_at": "2026-10-09T18:00:00Z"}, "names no terms_version"),
    ({"terms_version": "1", "terms_accepted_at": "yesterday"}, "UTC time"),
    ({"name": "x" * 61}, "at most 60"),
])
def test_a_record_the_compiler_cannot_stand_behind_is_refused_and_nothing_is_written(office, fields, said):
    before = office.read_text(encoding="utf-8")
    changed, errs = rc.set_office(fields)
    assert changed is False and any(said in e for e in errs), errs
    assert office.read_text(encoding="utf-8") == before


def test_an_office_installed_before_the_wizard_existed_is_installed_without_a_terms_record(office):
    # the three offices of 2026-10-09 are seeded this way: name, the owner's animal + hue, installed
    # now — and NO terms_accepted_at, because nobody clicked one
    changed, errs = rc.set_office({"name": "בינה סלושנס", "animal": "elephant", "hue": "muted",
                                   "installed_at": "2026-10-09T17:30:00Z"})
    assert (changed, errs) == (True, [])
    assert rc.office_block()["installed_at"] == "2026-10-09T17:30:00Z"
    assert "terms_accepted_at" not in rc.office_block()


def test_the_record_is_not_a_list(office):
    assert rc.set_office(["name"]) == (False, ["office: a JSON object of fields"])


def test_whitespace_in_a_name_is_one_space_and_blanks_are_not_values(office):
    changed, errs = rc.set_office({"name": "  הלשכה   בחיפה ", "animal": "", "hue": None,
                                   "terms_version": "1", "terms_accepted_at": "2026-10-09T18:00:00Z"})
    assert (changed, errs) == (True, [])
    assert rc.office_block() == {"name": "הלשכה בחיפה", "terms_version": "1",
                                 "terms_accepted_at": "2026-10-09T18:00:00Z"}
