"""The office's language is declared once and compiled once (DGO-971, ai/context/platform-language.md).

    python3 platform/manager/test_language.py      (or: python -m pytest platform/manager/test_language.py -q)

`language:` at the top of platform.state.yaml is the office's one language variable, and
`.generated/registry/locale.json` is what every screen reads. What is held here:
  * no declaration is the default (Hebrew, rtl), and a declared one is compiled with its direction;
  * the code is read as reconcile.py reads every value: trimmed, any case;
  * a code no dictionary has is refused BY NAME before anything renders, and is never handed to a caller;
  * `available` is the registry in its order, so a switcher renders it rather than a pair of its own.
The native twin (packaging/dgo internal/compiler) writes the same file and says the same line; its parity
tests compare the two compilers byte for byte.
"""
import importlib.util
import json
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_language", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_language"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()
AVAILABLE = [{"code": "he", "label": "עברית", "label_en": "Hebrew", "dir": "rtl"},
             {"code": "en", "label": "English", "label_en": "English", "dir": "ltr"}]


def test_no_declaration_is_hebrew_right_to_left():
    for st in (None, {}, {"schema_version": 1}, {"language": None}, {"language": ""}, {"language": False}):
        assert rc.state_language(st) == "he", st
        assert rc.language_errors(st) == [], st
        assert rc.locale_doc(st) == {"active": "he", "default": "he", "dir": "rtl", "available": AVAILABLE}, st


def test_a_declared_language_is_compiled_with_its_direction():
    for raw in ("en", " EN ", "En"):
        assert rc.language_errors({"language": raw}) == [], raw
        doc = rc.locale_doc({"language": raw})
        assert (doc["active"], doc["default"], doc["dir"]) == ("en", "en", "ltr"), (raw, doc)


def test_a_code_no_dictionary_has_is_refused_by_name_and_never_handed_on():
    for raw, said in (("eng", "eng"), ("Hebrew", "hebrew"), (1, "1"), (True, "true"), (["en"], "['en']")):
        errs = rc.language_errors({"language": raw})
        assert errs == [f"platform.state.yaml: language '{said}' is not a language this platform has a dictionary "
                        f"for (expected one of en, he)"], (raw, errs)
        assert rc.state_language({"language": raw}) == "he", raw          # the default, never the typo


def test_the_render_writes_locale_json_beside_the_tiles():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dgo971-"))
    old = rc.GEN
    rc.GEN = tmp / ".generated"
    try:
        rc.render_registries({}, [], None, {"schema_version": 1, "language": "en"})
        text = (tmp / ".generated" / "registry" / "locale.json").read_text(encoding="utf-8")
    finally:
        rc.GEN = old
        shutil.rmtree(tmp, ignore_errors=True)
    # the bytes themselves (the Go twin's parity test holds its own file to these): two-space indent, UTF-8 as
    # written, keys in the registry's order, one newline
    assert text == ('{\n  "active": "en",\n  "default": "en",\n  "dir": "ltr",\n  "available": [\n'
                    '    {\n      "code": "he",\n      "label": "עברית",\n      "label_en": "Hebrew",\n'
                    '      "dir": "rtl"\n    },\n    {\n      "code": "en",\n      "label": "English",\n'
                    '      "label_en": "English",\n      "dir": "ltr"\n    }\n  ]\n}\n'), text


def _with_state(text, fn):
    """Run fn() against a throwaway platform.state.yaml holding `text`; answer (fn's answer, the file after)."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dgo971-state-"))
    old = rc.STATE
    throwaway = tmp / "platform.state.yaml"
    throwaway.write_bytes(text.encode("utf-8"))   # the test's own file, written before reconcile is pointed at it
    rc.STATE = throwaway
    try:
        try:
            got = fn()
        except Exception as e:   # noqa: BLE001 — the refusal is part of the answer
            got = e
        return got, throwaway.read_text(encoding="utf-8")
    finally:
        rc.STATE = old
        shutil.rmtree(tmp, ignore_errors=True)


HEAD = "# the office's desired state — comments are the model, and stay\nschema_version: 1\napps:\n  drive: { state: enabled, by: user }\n"


def test_the_writer_puts_the_line_under_schema_version_and_keeps_every_comment():
    changed, after = _with_state(HEAD, lambda: rc.set_language("EN", by="console"))
    assert changed is True, changed
    assert after == HEAD.replace("schema_version: 1\n", "schema_version: 1\n\nlanguage: en   # by console\n"), after
    assert rc.state_language(rc.yaml.safe_load(after)) == "en"


def test_the_writer_replaces_the_line_in_place_and_a_same_write_is_no_change():
    st = HEAD.replace("apps:", "language: he   # by cli\napps:")
    changed, after = _with_state(st, lambda: rc.set_language("en", by="cli"))
    assert changed is True and after == st.replace("language: he   # by cli", "language: en   # by cli"), after
    same, again = _with_state(after, lambda: rc.set_language("en", by="cli"))
    assert same is False and again == after, again
    nested = HEAD + "office:\n  language: notes\n"                  # an indented key is not the declaration
    changed, after = _with_state(nested, lambda: rc.set_language("en"))
    assert after.count("language:") == 2 and "  language: notes" in after and changed is True, after


def test_the_writer_refuses_what_no_dictionary_has_and_writes_nothing():
    for bad in ("eng", "", "he; rm", None):
        got, after = _with_state(HEAD, lambda: rc.set_language(bad))
        assert isinstance(got, ValueError) and "expected one of en, he" in str(got), (bad, got)
        assert after == HEAD, (bad, after)
    got, after = _with_state("apps: {}\n", lambda: rc.set_language("en"))
    assert isinstance(got, ValueError) and after == "apps: {}\n", got     # no schema_version: nothing guessed


def test_a_declaration_the_writer_cannot_replace_is_refused_and_the_file_is_kept():
    """The second reader of slice 4: shapes of `language:` that YAML reads but the line surgery does not replace.
    The first was written into a file PyYAML could no longer parse; the others were written and changed nothing."""
    shapes = {
        "the value on the next line": HEAD.replace("apps:", "language:\n  he\napps:"),
        "a space before the colon": HEAD.replace("apps:", "language : he\napps:"),
        "a quoted key": HEAD.replace("apps:", "\"language\": he\napps:"),
        "a second declaration further down": HEAD.replace("apps:", "language: he\napps:") + "language: he\n",
        # the third reader: the first line already says the code, the file still reads the other
        "the first already the code, a second one not": HEAD.replace("apps:", "language: en   # by cli\napps:") + "language: he\n",
    }
    for name, st in shapes.items():
        got, after = _with_state(st, lambda: rc.set_language("en", by="cli"))
        assert isinstance(got, ValueError) and "nothing written" in str(got), (name, got)
        assert after == st, (name, after)
        rc.yaml.safe_load(after)   # and it still parses


def test_who_wrote_it_is_one_harmless_comment():
    changed, after = _with_state(HEAD, lambda: rc.set_language("en", by="x\n#evil: y"))
    assert "language: en   # by x__evil__y\n" in after and "#evil" not in after, after


def main():
    fails = 0
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)):
        try:
            fn()
            print("PASS  " + name)
        except Exception as e:   # noqa: BLE001 — every failure is reported, then the next test runs
            fails += 1
            print(f"FAIL  {name}\n        {type(e).__name__}: {e}")
    print("\nall passed" if not fails else f"\n{fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
