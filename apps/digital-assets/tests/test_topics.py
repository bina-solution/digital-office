"""the topics log (DGO-818): content/topics.yaml keeps every subject in the words it was said in, and each one ends
as a work item or is declined with its reason. topics.py lists the open entries and refuses a log that breaks the
rules. Runs on the real log and on scratch logs.

    python3 apps/digital-assets/tests/test_topics.py
"""
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "content"))
import topics  # noqa: E402

FAIL: list = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def run(argv) -> tuple[int, str]:
    out = io.StringIO()
    try:
        with redirect_stdout(out):
            rc = topics.main(argv)
    except Exception as e:                                # noqa: BLE001 — a crash is a failure, said as one
        return f"crash {e!r}", out.getvalue()
    return rc, out.getvalue()


def scratch(text: str) -> str:
    f = Path(tempfile.mkdtemp(prefix="topics-")) / "topics.yaml"
    f.write_text(text, encoding="utf-8")
    return str(f)


def test_the_real_log() -> None:
    rc, out = run(["--check"])
    check(rc == 0 and "0 problem(s)" in out, f"the committed log keeps its own rules: {out}")
    entries = topics.load()
    check(len(entries) >= 52 and all(t["source"] == "owner" and t["item"].startswith("DGO-") for t in entries[:52]),
          "the first 52 entries are the owner's SEO request, each with the item it became")
    check(entries[0]["where"] == "DGO-659", "…said on DGO-659, where his words are kept word for word")


def test_the_rules() -> None:
    bad = scratch("""topics:
  - { id: t001, date: 2026-11-10, source: owner, words: "a", state: item }
  - { id: t001, date: 2026-11-10, source: owner, words: "b", state: open }
  - { id: x2, date: "someday", source: rumour, words: "", state: open, item: DGO-1 }
  - { id: t004, date: 2026-11-10, source: user, words: "c", state: declined }
  - { id: t005, date: 2026-11-10, source: search, words: "d", state: maybe }
  - { id: t0001, date: 2026-11-10, source: owner, words: "e", state: open }
  - { id: t007, date: "2026-11-10", source: owner, words: ["a", "list"], state: declined, why: x, item: DGO-1 }
  - { id: t008, date: 2099-01-01, source: owner, words: "f", state: item, item: "DGO-6\\n" }
  - { id: "t٠٠٩", date: 2026-11-10, source: owner, words: "g", state: item, item: "DGO-١٢" }
  - { id: t010, date: 2026-11-10, source: owner, words: "h", state: declined, item: DGO-9 }
""")
    rc, out = run(["--check", "--file", bad])
    for what, needle in (("an item names its item", "t001: state item names its item"),
                         ("an id is never reused", "t001: id used twice"),
                         ("t0001 is t001", "t0001: id used twice"),
                         ("an id is tNNN", "x2: id is tNNN"),
                         ("a real date", "x2: date is a day"),
                         ("a quoted date is not a day", "t007: date is a day"),
                         ("not in the future", "t008: date 2099-01-01 is in the future"),
                         ("an item ref with a trailing newline", "t008: state item names its item"),
                         ("words are one text", "t007: the words are kept, verbatim, as one text"),
                         ("a declined entry has no item", "t007: a declined entry has no item"),
                         ("ids and refs are ASCII digits", "t٠٠٩: id is tNNN"),
                         ("…the ref too", "t٠٠٩: state item names its item"),
                         ("a declined entry: both rules said", "t010: a declined entry has no item"),
                         ("…and why is missing", "t010: a declined entry says why"),
                         ("a known source", "x2: source is one of"),
                         ("the words are kept", "x2: the words are kept"),
                         ("an open entry has no item", "x2: an open entry has no item yet"),
                         ("a declined entry says why", "t004: a declined entry says why"),
                         ("a known state", "t005: state is one of")):
        check(needle in out, f"{what}: {out}")
    check(rc == 1, f"a log that breaks a rule is refused (exit 1): {rc}")
    rc, out = run(["--check", "--file", scratch("- { id: t001 }\n")])
    check(rc == 1, f"a log that is a bare list is refused by name, not a crash: {rc}")


def test_open_entries_are_listed() -> None:
    log = scratch("""topics:
  - { id: t001, date: 2026-10-19, source: owner, where: DGO-659, words: "done already", item: DGO-661, state: item }
  - { id: t002, date: 2026-11-10, source: search, where: "Search Console", words: "מה זה חשבונית ישראל", state: open }
  - { id: t003, date: 2026-11-10, source: user, words: "not ours", state: declined, why: "no DGO angle" }
""")
    rc, out = run(["--file", log])
    check(rc == 0 and "t002" in out and "מה זה חשבונית ישראל" in out and "t001" not in out and "t003" not in out,
          f"only the open entry is listed, in its words: {out}")
    check("1 open of 3" in out and "tasks new DGO" in out, f"…with how it becomes an item: {out}")
    rc, out = run(["--json", "--file", log])
    doc = json.loads(out)
    check(doc["counts"] == {"open": 1, "item": 1, "declined": 1} and doc["problems"] == [], f"--json: {doc['counts']}")


def main() -> int:
    test_the_real_log()
    test_the_rules()
    test_open_entries_are_listed()
    for f in FAIL:
        print("FAIL:", f)
    print(f"test_topics: {'OK' if not FAIL else f'{len(FAIL)} failure(s)'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
