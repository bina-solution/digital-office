#!/usr/bin/env python3
"""
coverage_engine.py — turn raw Chromium coverage into "% of view code visible in the mockup".

THE METRIC
----------
The question is: of all the code that draws our UI, how much of it actually ran while we
were taking the screenshots that make up the big mockup image?

Two signals, collected over CDP while the capture driver walks every view:

  JS  — Profiler.takePreciseCoverage() gives byte RANGES per function with an execution
        count. Ranges with count==0 never ran. We map offsets -> line numbers against the
        real source file and get covered/uncovered lines.

  CSS — CSS.takeCoverageDelta() reports which style rules were actually APPLIED to
        rendered elements. This is the stronger "appeared on screen" signal: JS can run
        without painting anything, but a CSS rule is only used if something matched it.

We report both, and the honest headline is the pair. A file at 100% JS + 100% CSS means
every render branch ran and every style it can produce was painted at least once.

WHY THIS ALSO SOLVES STATE COVERAGE
-----------------------------------
Earlier I claimed "100% of UI states" wasn't a well-formed goal. That was wrong, and this
is why: the states ARE the branches. `if (!rows.length) renderEmpty()` is the empty state;
`catch (e) renderError()` is the error state. An uncovered branch is a state we never
photographed — so the uncovered-line report is literally the to-do list of missing
screenshots. That's the feedback loop that drives the mockup to 100%.

CAVEAT WE STATE OUT LOUD
------------------------
Precise coverage is *execution*, not *pixels*. A function can run and render nothing. That
is exactly why CSS rule usage is collected alongside it, and why the capture driver also
validates each PNG isn't blank. Three independent signals; we don't claim more than that.

Self-test:  python3 scripts/ui-coverage/coverage_engine.py --selftest
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Lines that carry no executable code — counting them would inflate the denominator
# with blank lines and comments and make 100% meaninglessly easy.
_BLANK = re.compile(r"^\s*$")
_LINE_COMMENT = re.compile(r"^\s*(//|/\*|\*|\*/|#)")
_PUNCT_ONLY = re.compile(r"^[\s{}\[\]();,]*$")


def executable_lines(source: str) -> set[int]:
    """Best-effort set of line numbers that can actually execute.

    Deliberately conservative: when unsure we EXCLUDE, because a denominator that
    quietly includes comment lines makes 100% unreachable and the metric gets ignored.
    """
    out: set[int] = set()
    in_block = False
    for i, raw in enumerate(source.splitlines(), start=1):
        ln = raw.strip()
        if in_block:
            if "*/" in ln:
                in_block = False
            continue
        if ln.startswith("/*") and "*/" not in ln:
            in_block = True
            continue
        if _BLANK.match(raw) or _LINE_COMMENT.match(raw) or _PUNCT_ONLY.match(raw):
            continue
        out.add(i)
    return out


def _offset_to_line(source: str) -> list[int]:
    """index -> line number, for mapping V8 byte offsets onto source lines."""
    line_of, line = [0] * (len(source) + 1), 1
    for i, ch in enumerate(source):
        line_of[i] = line
        if ch == "\n":
            line += 1
    line_of[len(source)] = line
    return line_of


def js_covered_lines(source: str, functions: list[dict]) -> set[int]:
    """Covered line numbers from one script's V8 precise-coverage `functions` array.

    V8 semantics: ranges nest. An outer range with count>0 plus an inner range with
    count==0 means "the function ran but that block didn't" — so we paint covered
    first, then subtract the zero-count blocks. Order matters; doing it the other way
    reports dead branches as covered, which is exactly the lie we're trying to avoid.
    """
    line_of = _offset_to_line(source)
    end = len(source)
    covered: set[int] = set()
    zero: list[tuple[int, int]] = []

    for fn in functions:
        for r in fn.get("ranges", []):
            s, e = max(0, r["startOffset"]), min(end, r["endOffset"])
            if s >= e:
                continue
            if r.get("count", 0) > 0:
                covered.update(range(line_of[s], line_of[e - 1] + 1))
            else:
                zero.append((s, e))

    for s, e in zero:
        for ln in range(line_of[s], line_of[e - 1] + 1):
            covered.discard(ln)
    return covered


@dataclass
class FileCoverage:
    path: str
    executable: set[int] = field(default_factory=set)
    covered: set[int] = field(default_factory=set)
    css_rules_total: int = 0
    css_rules_used: int = 0
    # which captured views contributed coverage to this file
    seen_in: set[str] = field(default_factory=set)

    @property
    def uncovered(self) -> list[int]:
        return sorted(self.executable - self.covered)

    @property
    def pct(self) -> float:
        if not self.executable:
            return 100.0
        return round(100.0 * len(self.covered & self.executable) / len(self.executable), 2)

    @property
    def css_pct(self):
        # No painted-rule data mapped to this file → report n/a, NOT a fake 100%.
        # (A 0-denominator "100%" is the single most misleading number a coverage tool can print.)
        if not self.css_rules_total:
            return None
        return round(100.0 * self.css_rules_used / self.css_rules_total, 2)


class CoverageAccumulator:
    """Unions coverage across every captured view — the mockup is the union, not one shot."""

    def __init__(self, include: list[str], exclude: list[str]):
        self.include, self.exclude = include, exclude
        self.files: dict[str, FileCoverage] = {}

    def _in_scope(self, rel: str) -> bool:
        if any(fnmatch.fnmatch(rel, p) for p in self.exclude):
            return False
        return any(fnmatch.fnmatch(rel, p) or rel == p for p in self.include)

    def _fc(self, rel: str, source: str) -> FileCoverage:
        fc = self.files.get(rel)
        if fc is None:
            fc = FileCoverage(path=rel, executable=executable_lines(source))
            self.files[rel] = fc
        return fc

    def add_js(self, rel: str, source: str, functions: list[dict], view: str) -> bool:
        if not self._in_scope(rel):
            return False
        fc = self._fc(rel, source)
        fc.covered |= js_covered_lines(source, functions)
        fc.seen_in.add(view)
        return True

    def add_css(self, rel: str, source: str, total: int, used: int, view: str) -> bool:
        if not self._in_scope(rel):
            return False
        fc = self._fc(rel, source)
        fc.css_rules_total = max(fc.css_rules_total, total)
        fc.css_rules_used = max(fc.css_rules_used, used)
        fc.seen_in.add(view)
        return True

    def summary(self, threshold: float = 100.0) -> dict:
        files = sorted(self.files.values(), key=lambda f: f.pct)
        ex = sum(len(f.executable) for f in files)
        cov = sum(len(f.covered & f.executable) for f in files)
        rules_t = sum(f.css_rules_total for f in files)
        rules_u = sum(f.css_rules_used for f in files)
        return {
            "overall_js_pct": round(100.0 * cov / ex, 2) if ex else 100.0,
            # None (rendered "n/a") when no CSS rules were mapped to first-party files —
            # the stylesheet→source mapping (sourceURL) isn't wired yet, so don't fake 100%.
            "overall_css_pct": round(100.0 * rules_u / rules_t, 2) if rules_t else None,
            "css_mapped": rules_t > 0,
            "executable_lines": ex,
            "covered_lines": cov,
            "css_rules_total": rules_t,
            "css_rules_used": rules_u,
            "threshold": threshold,
            "files": [
                {
                    "path": f.path, "js_pct": f.pct, "css_pct": f.css_pct,
                    "executable": len(f.executable),
                    "covered": len(f.covered & f.executable),
                    "uncovered_lines": f.uncovered[:200],
                    "seen_in": sorted(f.seen_in),
                    "below_threshold": f.pct < threshold,
                }
                for f in files
            ],
            "failing_files": [f.path for f in files if f.pct < threshold],
        }


def missing_states_report(summary: dict, source_root: Path = ROOT) -> list[dict]:
    """Turn uncovered lines into a human to-do list of un-photographed states.

    This is the payoff: an uncovered `renderEmpty()` is not an abstract coverage gap,
    it is a screenshot nobody took. We surface the actual source line so the fix is
    obvious ("add a state that hits this branch").
    """
    out = []
    for f in summary["files"]:
        if not f["uncovered_lines"]:
            continue
        p = source_root / f["path"]
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        hints = []
        for ln in f["uncovered_lines"][:40]:
            if 1 <= ln <= len(lines):
                text = lines[ln - 1].strip()
                # a render/branch keyword on an uncovered line is very likely a missing state
                if re.search(r"\b(render|show|open|draw|empty|error|catch|else|if)\b", text, re.I):
                    hints.append({"line": ln, "code": text[:120]})
        if hints:
            out.append({"path": f["path"], "js_pct": f["js_pct"], "candidates": hints[:12]})
    return out


# ── self-test: prove the coverage math, no browser required ──────────────────

def _selftest() -> int:
    src = (
        "function render(rows) {\n"        # 1
        "  if (!rows.length) {\n"          # 2
        "    return renderEmpty();\n"      # 3  <- empty state, NOT exercised
        "  }\n"                            # 4
        "  return renderRows(rows);\n"     # 5  <- exercised
        "}\n"                              # 6
        "\n"                               # 7  blank
        "// a comment\n"                   # 8  comment
        "render([1]);\n"                   # 9  exercised
    )
    ex = executable_lines(src)
    assert 7 not in ex and 8 not in ex, f"blank/comment leaked into denominator: {sorted(ex)}"
    assert {1, 2, 3, 5, 9} <= ex, f"missing executable lines: {sorted(ex)}"

    # V8 shape: whole script ran (count=1), but the empty-state block did not (count=0)
    empty_start = src.index("    return renderEmpty();")
    empty_end = src.index("\n  }\n", empty_start) + 1
    functions = [{
        "functionName": "",
        "ranges": [
            {"startOffset": 0, "endOffset": len(src), "count": 1},
            {"startOffset": empty_start, "endOffset": empty_end, "count": 0},
        ],
    }]
    covered = js_covered_lines(src, functions)
    assert 3 not in covered, "un-run empty-state branch was reported as covered (the exact lie we guard against)"
    assert 5 in covered and 9 in covered, f"executed lines missing from coverage: {sorted(covered)}"

    acc = CoverageAccumulator(include=["fake/app.js"], exclude=[])
    assert acc.add_js("fake/app.js", src, functions, view="console/dashboard")
    assert not acc.add_js("vendor/lib.min.js", src, functions, view="x"), "exclude/include scope not enforced"
    s = acc.summary(threshold=100.0)
    fc = s["files"][0]
    assert fc["uncovered"] if False else 3 in fc["uncovered_lines"], "missing state not surfaced"
    assert fc["below_threshold"] and s["failing_files"] == ["fake/app.js"]
    assert 0 < s["overall_js_pct"] < 100, f"expected partial coverage, got {s['overall_js_pct']}"

    print("coverage_engine self-test: PASS")
    print(f"  executable lines : {sorted(ex)}")
    print(f"  covered lines    : {sorted(covered)}")
    print(f"  uncovered (= un-photographed states): {fc['uncovered_lines']}")
    print(f"  overall JS coverage: {s['overall_js_pct']}%")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    ap.print_help()
