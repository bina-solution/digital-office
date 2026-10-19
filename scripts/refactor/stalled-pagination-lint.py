#!/usr/bin/env python3
"""stalled-pagination-lint — gate G49: an auto-advancing pager cannot loop on a page that
returns nothing.

    python3 scripts/refactor/stalled-pagination-lint.py [--self-test]

WHY THIS GATE EXISTS (caught in review, 2026-08-06, in this gate author's OWN change):

`SyncBoard.tsx` grew infinite scrolling: a `useEffect` fires the next page as the viewport nears
the end of the loaded set, and "is there more?" was

    const hasMore = total != null && rows.length < total;

That predicate is advanced by exactly one thing — rows arriving. A page that returns **zero** rows
leaves `rows.length` unchanged and `total` unchanged, so `hasMore` stays true, so the effect that
just fired fires again, forever, against a server that keeps answering "none". A client hammering
an endpoint several times a second, and a column that never stops spinning.

It is the mirror image of G36. G36 is the SERVER under-reporting (one page returned as if it were
the whole set); this is the CLIENT unable to notice that the server has run out. Both come from
treating a count as authoritative about a fetch that has its own opinion.

THE RULE: if a component fetches the next page WITHOUT the user asking — a `useEffect`/observer
that calls a loader — then its "more?" predicate must be falsifiable by the RESPONSE, not only by
arithmetic over a declared total. In practice that means one of:
  * a short-page flag  (`exhausted` — the page came back smaller than the page size),
  * a server-supplied continuation (`nextOffset` / `nextCursor` / `hasNext`),
  * or an explicit zero-length check on what just arrived.

A pager driven ONLY by a button the user presses is not flagged: a human who stops seeing new rows
stops pressing. The loop is what makes the missing guard dangerous.

WHAT IS FLAGGED: a scope that has (1) an automatic next-page trigger, (2) a length-vs-total "more"
predicate, and (3) no exhaustion signal anywhere in it.
"""
import argparse
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Where infinite scrolling actually lives. Tight scope, same reasoning as G36: a repo-wide sweep
#: for `.length < total` would drown in unrelated arithmetic and the gate would stop being read.
SCOPE_GLOBS = (
    "apps/*/app/webapp/src/**/*.tsx",
    "apps/*/app/webapp/src/**/*.ts",
    "platform-base/*/webapp/src/**/*.tsx",
)

EXEMPT = {
    "scripts/refactor/stalled-pagination-lint.py",   # this file
}

#: (1) something advances the pager with no user gesture
AUTO_TRIGGER = re.compile(
    r"""useEffect\s*\(|IntersectionObserver|onScrollEnd|onEndReached""")
#: ...and it actually calls a loader
LOADER_CALL = re.compile(
    r"""\b(?:load|fetch|get|request)(?:More|Next|Page|NextPage)\s*\(|"""
    r"""\bon(?:LoadMore|FetchMore|EndReached)\s*\(""")
#: (2) "is there more?" is pure arithmetic over a declared total
LENGTH_VS_TOTAL = re.compile(
    r"""\.length\s*<\s*[^;\n]*\b(?:total|count)\b"""
    r"""|\b(?:total|count)\w*\s*>\s*[^;\n]*\.length""",
    re.IGNORECASE)
#: (3) an exhaustion signal — anything that lets the RESPONSE end the loop
EXHAUSTION = re.compile(
    r"""\bexhausted\b|\bhasNext\b|\bhas_next\b|\bnextOffset\b|\bnext_offset\b"""
    r"""|\bnextCursor\b|\bnext_cursor\b|\bnextPageToken\b|\bnoMore\b|\bno_more\b"""
    r"""|\bendReached\b|\batEnd\b|\bisDone\b"""
    # "did anything actually arrive?" — in any of the forms people write it. `!== 0` / `> 0` are
    # the same guard as `=== 0` with the branches swapped, and omitting them made this gate fail
    # a correct pager, which is the failure mode that gets a gate deleted rather than fixed.
    r"""|\.length\s*(?:===|==|!==|!=|<|>)\s*0"""
    r"""|\.length\s*<\s*(?:PAGE|PAGE_SIZE|LIMIT|limit|pageSize)\b""",  # short page
    re.IGNORECASE)


#: a `const hasMore = <expr>;` style declaration — the RHS is what must carry the guard
PREDICATE_DECL = re.compile(r"""\b(?:const|let|var)\s+(\w+)\s*=\s*([^;]*);""")


def _effect_bodies(text):
    """Every `useEffect(...)` / observer-callback body, by paren matching from the call site.

    NOT scope-wide: the FIRST version of this gate asked whether an exhaustion signal appeared
    anywhere in the enclosing component, and that is exactly the check that let the real defect
    through. `SyncBoard.tsx` mentions `exhausted` three lines below the broken predicate, in an
    unrelated `shortfall` expression, so a component-level search found it and passed the file
    while the auto-fetch loop was live. The guard has to be on the predicate that DRIVES the
    fetch; anything coarser measures vocabulary rather than behaviour.
    """
    for m in AUTO_TRIGGER.finditer(text):
        i = text.find("(", m.end() - 1)
        if i < 0:
            continue
        depth, j = 0, i
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield text[i:j + 1]


def scan_text(rel, text):
    if rel in EXEMPT:
        return []
    # Which predicates are fragile: derived from length-vs-total, with no exhaustion signal in
    # the DECLARATION ITSELF.
    fragile = {}
    for m in PREDICATE_DECL.finditer(text):
        name, rhs = m.group(1), m.group(2)
        if not LENGTH_VS_TOTAL.search(rhs) or EXHAUSTION.search(rhs):
            continue
        fragile[name] = text[:m.start()].count("\n") + 1
    if not fragile:
        return []
    out = []
    for body in _effect_bodies(text):
        # an effect that both fires a loader AND gates on a fragile predicate is the loop
        if not LOADER_CALL.search(body):
            continue
        if EXHAUSTION.search(body):        # the effect guards itself — fine
            continue
        for name, line_no in fragile.items():
            if re.search(rf"\b{re.escape(name)}\b", body):
                out.append((rel, line_no, name))
    return sorted(set(out))


def _in_scope(rel):
    p = pathlib.PurePosixPath(rel)
    return any(p.match(g) for g in SCOPE_GLOBS)


def scan(overrides=None):
    overrides = overrides or {}
    findings, seen = [], set()
    for glob in SCOPE_GLOBS:
        for p in sorted(REPO.glob(glob)):
            rel = p.relative_to(REPO).as_posix()
            if "node_modules" in rel or "/dist/" in rel:
                continue
            seen.add(rel)
            text = overrides.get(rel)
            if text is None:
                try:
                    text = p.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
            findings += scan_text(rel, text)
    for rel, text in overrides.items():
        if rel not in seen and _in_scope(rel):
            findings += scan_text(rel, text)
    return findings


BOARD = "apps/indox/app/webapp/src/pages/SyncBoard.tsx"

SELF_TEST = [
    # THE ACTUAL DEFECT — auto-prefetch, "more?" is length < total, nothing can end it.
    ("the real 2026-08-06 defect", BOARD,
     'function Column({ col, onLoadMore }) {\n'
     '  const known = col.total != null;\n'
     '  const hasMore = known && rows.length < col.total;\n'
     '  useEffect(() => {\n'
     '    if (!hasMore || col.loading) return;\n'
     '    if (last >= rows.length - PREFETCH_ROWS) onLoadMore();\n'
     '  }, [last, hasMore, rows.length]);\n'
     '}\n', True),

    # the fix — a short page ends it
    ("short-page guard", BOARD,
     'function Column({ col, onLoadMore }) {\n'
     '  const hasMore = col.total != null && rows.length < col.total && !col.exhausted;\n'
     '  useEffect(() => {\n'
     '    if (!hasMore) return;\n'
     '    if (last >= rows.length - PREFETCH_ROWS) onLoadMore();\n'
     '  }, [last, hasMore, rows.length]);\n'
     '}\n', False),
    # server-supplied continuation is just as good
    ("server cursor", BOARD,
     'function Feed({ page, loadMore }) {\n'
     '  const hasMore = page.items.length < page.total && page.nextCursor != null;\n'
     '  useEffect(() => { if (hasMore) loadMore(); }, [hasMore]);\n'
     '}\n', False),
    # an explicit zero-length check on what arrived
    ("zero-length check", BOARD,
     'function Feed({ rows, total, loadMore, lastBatch }) {\n'
     '  const hasMore = rows.length < total;\n'
     '  useEffect(() => { if (hasMore && lastBatch.length !== 0) loadMore(); }, [hasMore]);\n'
     '}\n', False),

    # MANUAL pager — a human presses it, a human stops. Not a loop.
    ("button-only pager", BOARD,
     'function Column({ col, onLoadMore }) {\n'
     '  const hasMore = col.total != null && rows.length < col.total;\n'
     '  return <button onClick={onLoadMore}>{hasMore ? "more" : "done"}</button>;\n'
     '}\n', False),
    # auto-trigger, but the predicate is not length-vs-total arithmetic
    ("effect without the fragile predicate", BOARD,
     'function Column({ col, onLoadMore }) {\n'
     '  useEffect(() => { if (col.more) onLoadMore(); }, [col.more]);\n'
     '}\n', False),
    # no pagination at all
    ("unrelated component", BOARD,
     'function Toast({ msg }) {\n'
     '  useEffect(() => { const t = setTimeout(hide, 2600); return () => clearTimeout(t); }, []);\n'
     '  return <div>{msg}</div>;\n'
     '}\n', False),
    # same shape, outside the scoped webapps
    ("out of scope path", "digital-office/sim/apps/indox/src/pages/SyncBoard.tsx",
     'function Column({ col, onLoadMore }) {\n'
     '  const hasMore = rows.length < col.total;\n'
     '  useEffect(() => { if (hasMore) onLoadMore(); }, [hasMore]);\n'
     '}\n', False),
]


def self_test():
    bad = 0
    for label, rel, text, should in SELF_TEST:
        got = bool(scan_text(rel, text)) if _in_scope(rel) else False
        if got != should:
            bad += 1
        print(f"  [{'ok ' if got == should else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} "
              f"({'must catch' if should else 'must allow'}): {label}")
    print(f"\nG49 self-test: {len(SELF_TEST) - bad}/{len(SELF_TEST)} passed")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    findings = scan()
    if findings:
        print(f"G49 FAIL — {len(findings)} auto-advancing pager(s) with no exhaustion signal:")
        for rel, line_no, name in findings:
            print(f"    {rel}:{line_no}  in {name}()")
        print("\n  'More?' is decided by arithmetic over a declared total, and the fetch that")
        print("  advances it can return zero rows — so the effect re-fires forever against a")
        print("  server answering 'none'. Add a short-page flag, a server cursor, or a")
        print("  zero-length check on the batch that just arrived.")
        return 1
    print("G49 PASS — every auto-advancing pager can be stopped by its own response.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
