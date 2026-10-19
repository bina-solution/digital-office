#!/usr/bin/env python3
"""
hebrew-strings.py — the English strings upstream hardcodes, in Hebrew.  RUN at build time.

    RUN python3 /app/patches/hebrew-strings.py        (Dockerfile, after the bundle is unpacked)

WHY THIS EXISTS, AND WHY IT IS NOT IN `plane-he`.

`plane-he` (github.com/solomonBoltin/plane-he) translates Plane through its own i18n namespaces, and
on this deployment that catalogue is COMPLETE: measured 2026-10-08 against upstream v1.4.2, 3035
English keys and **zero** of them missing a Hebrew counterpart. What the owner still reads in Hebrew
screens — `Work Items` in the sidebar, `Search commands...` in the command palette, `Community` on
the edition badge, `Not started` / `Backlog` over the workload cards — is not a translation gap at
all: those strings are LITERALS inside the app's own JavaScript, never passed through `t()`, so no
catalogue can reach them. Fixing them at the source means editing the monorepo and rebuilding the
frontend in `plane-he`'s CI, which is the right long-term home and needs a push to that repository
(owner's credential — recorded on the work item). This patch is the same edit applied to the BUILT
bundle, so the office reads Hebrew today.

WHAT IT TOUCHES, AND WHAT IT REFUSES TO TOUCH.

`hebrew-strings.tsv` (beside this file) is `English<TAB>Hebrew`, one entry per string. A string is
replaced only where the code that follows it proves it is TEXT A PERSON READS: the 46 characters
before it must end in a React prop that renders copy — `children:`, `label:`, `title:`,
`placeholder:`, `text:`, `description:`, `message:`, `heading:`, `tooltip…`, `aria-label:`, `alt:`,
`subtitle:`. An occurrence anywhere else (`===`, `.includes(…), a comparison, a key, a URL) is left
alone and reported, because a translated VALUE that the code compares is a bug that shows up as a
feature that stopped matching — and the bundle is minified, so nothing else can tell the two apart.

The table itself was built mechanically, not by eye: every string literal of every shipped chunk was
extracted, the ones that are values of the English locale were dropped (they are already translated),
and what remained was kept only if EVERY occurrence in the bundle was a display occurrence. 501
entries came out of that first pass; a second pass took the strings whose English is ALSO an identity
somewhere else in the bundle (`January` in a date array, `Kanban` in a layout's value, the auth error
codes) and translated their display occurrences only — which is what the rule does anyway, but here
it is load-bearing. 641 entries in all. The locale chunks themselves are never touched — they are
found by parsing i18n's own `"../locales/<lang>/<ns>.json": () => import("./<file>.js")` map.

It REFUSES the build (`exit 1`) when an entry of the table matches nothing and its Hebrew is not
already there: that is the bundle being replaced by a newer one, and a table that silently stops
matching is an office that silently goes back to English. Re-run it after a `PLANE_HE_WEB_URL` bump.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

WEB = pathlib.Path(os.environ.get("PLANE_WEB_DIR") or "/app/web")
ASSETS = WEB / "assets"
TABLE = pathlib.Path(__file__).with_name("hebrew-strings.tsv")

# What may introduce a string a person reads. Deliberately does NOT include `name:`, `value:`,
# `key:` or `id:` — those are as often an identity as a label, and an identity that changed is code
# that stopped matching.
DISPLAY = re.compile(
    r"(?:children|label|placeholder|title|text|description|heading|tooltip|tooltipHeading|"
    r"tooltipContent|aria-label|alt|message|subtitle)\s*:\s*$"
)
CONTEXT = 46                      # characters of context a display prop needs to be recognised

# Strings with no prop in front of them: a ternary in a widget, the edition badge, the state groups
# the whole app labels itself from. Each one must occur EXACTLY ONCE — it is anchored by its own
# code, so a miss is upstream having rewritten that line, and the build stops rather than half-doing
# it. The state names match `patches/hebrew-states.py` (the same words the server writes into a new
# project) and `bootstrap.yaml`, so the app and the data agree.
SNIPPETS: list[tuple[str, str, int]] = [
    # the sidebar's collapse toggle
    ("`Hide`:`More`}", "`הסתר`:`עוד`}", 1),
    # the state groups' labels AND the name a NEW state is born with, matched as the one
    # object they live in
    ("label:`Unstarted`,defaultStateName:`Todo`", "label:`לביצוע`,defaultStateName:`לביצוע`", 1),
    ("label:`Started`,defaultStateName:`In Progress`", "label:`בתהליך`,defaultStateName:`בתהליך`", 1),
    ("label:`Completed`,defaultStateName:`Done`", "label:`בוצע`,defaultStateName:`בוצע`", 1),
    ("label:`Canceled`,defaultStateName:`Cancelled`", "label:`בוטל`,defaultStateName:`בוטל`", 1),
    ("label:`Backlog`,defaultStateName:`Backlog`", "label:`מלאי`,defaultStateName:`מלאי`", 1),
    # the extended sidebar's own header, and the palette's group for it
    ("title:`Projects`,quickActions:", "title:`פרויקטים`,quickActions:", 1),
    ("py-1.5 text-13 font-semibold text-tertiary`,children:`Projects`}",
     "py-1.5 text-13 font-semibold text-tertiary`,children:`פרויקטים`}", 1),
    ("title:`Projects`},workspace:", "title:`פרויקטים`},workspace:", 1),
    # the "joined" chip of a profile
    (",`Joined`]", ",`הצטרף`]", 1),
    # the workload cards (profile + project overview): two group names are written here, the rest
    # come from the state groups below
    ("e.state_group===`unstarted`?`Not started`:e.state_group===`started`?`Working on`",
     "e.state_group===`unstarted`?`לביצוע`:e.state_group===`started`?`בתהליך`", 1),
    # STATE GROUPS — the labels the app shows for a state's group, everywhere a group is named
    # (filters, the group-by menu, the workload cards). The GROUP KEYS are untouched: code branches
    # on them.
    ("{backlog:{key:`backlog`,label:`Backlog`,defaultStateName:`Backlog`,color:`#d9d9d9`},"
     "unstarted:{key:`unstarted`,label:`Unstarted`,defaultStateName:`Todo`,color:`#3f76ff`},"
     "started:{key:`started`,label:`Started`,defaultStateName:`In Progress`,color:`#f59e0b`},"
     "completed:{key:`completed`,label:`Completed`,defaultStateName:`Done`,color:`#16a34a`},"
     "cancelled:{key:`cancelled`,label:`Canceled`,defaultStateName:`Cancelled`,color:`#dc2626`}}",
     "{backlog:{key:`backlog`,label:`מלאי`,defaultStateName:`מלאי`,color:`#d9d9d9`},"
     "unstarted:{key:`unstarted`,label:`לביצוע`,defaultStateName:`לביצוע`,color:`#3f76ff`},"
     "started:{key:`started`,label:`בתהליך`,defaultStateName:`בתהליך`,color:`#f59e0b`},"
     "completed:{key:`completed`,label:`בוצע`,defaultStateName:`בוצע`,color:`#16a34a`},"
     "cancelled:{key:`cancelled`,label:`בוטל`,defaultStateName:`בוטל`,color:`#dc2626`}}", 1),
]


def locale_chunks(assets: pathlib.Path) -> set[str]:
    """The chunk files i18n's own glob map points at — the translations, never ours to rewrite."""
    found: set[str] = set()
    pat = re.compile(r'"\.\./locales/[\w\-]+/[\w\-]+\.json":\(\)=>\w+\(\(\)=>import\(`\./([\w.\-]+\.js)`\)')
    for path in assets.glob("*.js"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if '"../locales/' in text:
            found.update(pat.findall(text))
    return found


def load_table(path: pathlib.Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        english, _, hebrew = line.partition("\t")
        if english and hebrew:
            entries.append((english, hebrew))
    return entries


def apply_entry(text: str, english: str, hebrew: str) -> tuple[str, int, int]:
    """Replace the DISPLAY occurrences of `english`. Returns (text, replaced, skipped)."""
    out, replaced, skipped, i = [], 0, 0, 0
    while True:
        j = text.find(english, i)
        if j < 0:
            out.append(text[i:])
            break
        before = text[max(0, j - CONTEXT):max(0, j - 1)]
        if DISPLAY.search(before):
            out.append(text[i:j])
            out.append(hebrew)
            replaced += 1
        else:
            out.append(text[i:j + len(english)])
            skipped += 1
        i = j + len(english)
    return "".join(out), replaced, skipped


def main() -> int:
    if not ASSETS.is_dir():
        print(f"hebrew-strings: {ASSETS} is missing — the bundle is not where the Dockerfile put it")
        return 1
    table = load_table(TABLE)
    if len(table) < 100:
        print(f"hebrew-strings: the table has {len(table)} entries — that is not the table, refusing")
        return 1

    locale = locale_chunks(ASSETS)
    chunks = sorted(p for p in ASSETS.glob("*.js") if p.name not in locale)
    print(f"hebrew-strings: {len(table)} strings, {len(chunks)} app chunks "
          f"({len(locale)} translation chunks left alone)")

    # LONGEST FIRST. A short entry eats the long strings that begin with it — `Oops!` inside
    # `Oops! Something went wrong.`, `Failed to update user profile` inside `… theme` — and the long
    # one then matches nothing. Measured 2026-10-08 on the v1.4.2 bundle: 8 entries lost that way.
    table.sort(key=lambda e: -len(e[0]))

    # Stale = gone from the bundle altogether: a newer bundle under an older table. Decided from the
    # ORIGINAL bytes, before anything is rewritten.
    corpus = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in chunks)
    if not re.search(r"[\u0590-\u05FF]", corpus):
        # Upstream's own English bundle: PLANE_HE_WEB_URL is empty, and Hebrew built into an English
        # frontend is not a state anybody asked for. A no-op, said out loud.
        print("hebrew-strings: this bundle carries no Hebrew at all — upstream's English build, "
              "nothing to do")
        return 0
    absent = [e for e, he in table if e not in corpus and he not in corpus]
    if absent:
        print(f"hebrew-strings: {len(absent)} table entries match NOTHING in this bundle — this is a "
              f"newer frontend than the table was derived from; refusing, the table must be "
              f"re-derived from it:")
        for e in absent[:20]:
            print(f"    · {e}")
        return 1

    done: dict[str, int] = {english: 0 for english, _ in table}
    skipped: dict[str, int] = {}
    touched: set[str] = set()

    # FIRST the anchored snippets, ONCE for the whole bundle — before the open table, because
    # their anchors are written against the UNTOUCHED bundle and the table would eat the shorter
    # strings inside them (`label:`Backlog`` lives inside the state-groups object). Not inside the per-chunk loop: a
    # snippet lives in ONE chunk, and asking every chunk for it is what made the first version of
    # this loop skip a rewrite silently (the rail's «More» stayed English through a "successful"
    # build — found 2026-10-08 by looking at the screenshot, not by the build). Now a snippet whose
    # total is not exactly what the table expects fails the build.
    for snippet, hebrew, expect in SNIPPETS:
        hits = [p for p in chunks if snippet in p.read_text(encoding="utf-8")]
        if not hits and any(hebrew in p.read_text(encoding="utf-8") for p in chunks):
            continue                                          # a second run: already applied
        if len(hits) != expect:
            print(f"hebrew-strings: `{snippet[:56]}…` is in {len(hits)} chunk(s), expected {expect} "
                  f"— the bundle moved, refusing to guess")
            return 1
        for path in hits:
            path.write_text(path.read_text(encoding="utf-8").replace(snippet, hebrew), encoding="utf-8")
            touched.add(path.name)


    for path in chunks:
        text = original = path.read_text(encoding="utf-8")
        for english, hebrew in table:
            text, replaced, skip = apply_entry(text, english, hebrew)
            done[english] += replaced
            if skip:
                skipped[english] = skipped.get(english, 0) + skip
        if text != original:
            path.write_text(text, encoding="utf-8")
            touched.add(path.name)

    missing = sorted(e for e, n in done.items() if n == 0)
    total = sum(done.values())
    print(f"hebrew-strings: {total} replacements in {len(touched)} chunks")
    if total == 0 and touched:
        print("hebrew-strings: nothing was replaced but files changed — that cannot happen")
        return 1
    if missing and total:
        print(f"hebrew-strings: {len(missing)} entries are in the bundle but never in a display "
              f"position — left alone on purpose, and worth a look:")
        for e in missing[:20]:
            print(f"    · {e}")
    if skipped:
        print(f"hebrew-strings: {sum(skipped.values())} occurrences left alone (not a display "
              f"position): " + ", ".join(f"{e} ×{n}" for e, n in list(skipped.items())[:5]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
