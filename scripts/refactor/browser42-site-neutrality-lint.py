#!/usr/bin/env python3
"""browser42-site-neutrality-lint — gate G35: incident fixtures stay out of Browser42.

    python3 scripts/refactor/browser42-site-neutrality-lint.py [--self-test]

Browser42 must browse from the task, live page inspection, and generic policies. During its native
tab-group proof, publisher-specific names and selectors entered the historical lifetime report.
One selector then leaked into a proposed generic action API. If copied into runtime, agent guidance,
or tests, that accident would quietly turn a general browser into a site adapter.

The report and observable ledger are immutable incident evidence and intentionally not scanned.
This gate covers the operative surfaces: the Browser42 app, custom agent, CLI guide, bbox entry
points, and Browser42-named scripts. Add new incident markers when a fixture is introduced; do not
add allow-list exceptions to executable surfaces.
"""

import argparse
import pathlib
import re
import sys


REPO = pathlib.Path(__file__).resolve().parents[2]
EXACT_FILES = (
    ".github/agents/browser42.agent.md",
    "ai/context/browser42-cli.md",
    "bbox",
    "bbox.cmd",
)
INCIDENT_MARKERS = (
    ("historical publisher name", re.compile(r"(?<![a-z0-9])ma" r"ko(?![a-z0-9])", re.I)),
    ("historical result selector", re.compile(r"article" r"ins", re.I)),
)


def operative_files():
    paths = [REPO / rel for rel in EXACT_FILES]
    paths.extend((REPO / "apps/browser42").rglob("*"))
    paths.extend((REPO / "scripts").glob("*browser42*"))
    return sorted(path for path in set(paths) if path.is_file())


def scan(virtual=None):
    """Return (path, line, marker, excerpt) findings; virtual data powers the self-test."""
    items = operative_files() if virtual is None else virtual.keys()
    findings = []
    for path in items:
        try:
            text = virtual[path] if virtual is not None else path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for label, pattern in INCIDENT_MARKERS:
                if pattern.search(line):
                    rel = str(path) if virtual is not None else path.relative_to(REPO).as_posix()
                    findings.append((rel, line_number, label, line.strip()[:120]))
    return findings


SELF_TEST = (
    ("publisher domain", "navigate to https://www.mako.example/path", True),
    ("publisher name in instructions", "Use Mako's result page", True),
    ("copied result selector", "container = 'li.articleins'", True),
    ("unrelated longer word", "source = 'makor-rishon'", False),
    ("generic direct URL", "navigate to https://example.com/path", False),
)


def self_test():
    failures = 0
    for label, text, should_catch in SELF_TEST:
        findings = scan({pathlib.Path("self-test.txt"): text})
        caught = bool(findings)
        if caught != should_catch:
            failures += 1
        print(f"  [{'ok ' if caught == should_catch else 'FAIL'}] "
              f"{'caught' if caught else 'allowed':<7} "
              f"({'must catch' if should_catch else 'must allow'}): {label}")
    print(f"\nG35 self-test: {len(SELF_TEST) - failures}/{len(SELF_TEST)} passed")
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    findings = scan()
    if findings:
        print(f"G35 FAIL — {len(findings)} incident-fixture reference(s) in generic Browser42 surfaces:")
        for rel, line, label, excerpt in findings:
            print(f"    {rel}:{line}  {label}")
            print(f"        {excerpt}")
        print("\nKeep sites, selectors, and workflows in task data or immutable incident evidence.")
        print("Browser42 runtime and operative guidance must derive behavior from live inspection.")
        return 1

    print(f"G35 PASS — {len(operative_files())} Browser42 operative files contain no incident fixtures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())