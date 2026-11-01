#!/usr/bin/env python3
"""issue-file-lint — gate G75: every issue file under issues/ is one its own schema accepts.

    python3 scripts/refactor/issue-file-lint.py              # exit 1 if a file is refused
    python3 scripts/refactor/issue-file-lint.py --self-test

WHY THIS EXISTS. `issues/*.yaml` is where a defect is measured, argued and closed, and it has
readers that are programs: the hub's plan is generated from these files (title, status, the task
list with its `done` flags), and a session decides what is left to do from them. `issues/schema.json`
says what a file must be — and nothing ever asked a file whether it is. A status spelled `done`, a
task without `done:`, a tab in the wrong place: each is a file the next reader takes at its word, or
silently skips. The files are edited by hand and by scripts, many times a day.

WHAT IT CHECKS. Each `issues/*.yaml` must parse, and must satisfy `issues/schema.json` — the schema
is READ, not restated here, so the two cannot drift: required keys, no unknown keys, the enums
(`status`, `severity`, `category`), the date's shape, every task a `{text, done}` with a boolean.
YAML reads `opened: 2026-10-04` as a date, and that is the string the schema means.

It validates the subset of JSON Schema the file uses (type, required, enum, pattern, minLength,
additionalProperties: false, items) and REFUSES a schema keyword it does not implement — a
validator that ignores a rule it cannot check is the defect this gate exists to stop.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import sys

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool}
#: Keywords that say nothing a file can break.
SILENT = {"description", "title", "$schema", "$id", "format"}
KNOWN = SILENT | {"type", "required", "properties", "additionalProperties", "items", "enum", "pattern",
                  "minLength"}


def problems(value, schema: dict, where: str = "") -> list[str]:
    """What `value` breaks in `schema`, as sentences. An unimplemented keyword is itself a problem."""
    out = [f"{where or 'the file'}: the schema uses `{k}`, which this gate does not check"
           for k in schema if k not in KNOWN]
    if isinstance(value, (datetime.date, datetime.datetime)):
        value = value.isoformat()[:10]
    want = TYPES.get(schema.get("type"))
    if want and (not isinstance(value, want) or (want is not bool and isinstance(value, bool))):
        return out + [f"{where or 'the file'} must be a {schema['type']}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{where}: {value!r} is not one of {', '.join(schema['enum'])}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            out.append(f"{where} is empty")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{where}: {value!r} does not look like {schema['pattern']}")
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        out += [f"{where + '.' if where else ''}{k} is required" for k in schema.get("required", []) if k not in value]
        if schema.get("additionalProperties") is False:
            out += [f"{where + '.' if where else ''}{k} is not a key an issue file has" for k in value if k not in props]
        for k, v in value.items():
            if k in props:
                out += problems(v, props[k], f"{where + '.' if where else ''}{k}")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            out += problems(v, schema["items"], f"{where}[{i}]")
    return out


def check(repo: pathlib.Path) -> int:
    schema = json.loads((repo / "issues" / "schema.json").read_text(encoding="utf-8"))
    files = sorted((repo / "issues").glob("*.yaml"))
    if not files:
        print("issue-file-lint — G75: no issue file found under issues/ — a search that finds none has measured nothing")
        return 1
    bad = 0
    for f in files:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
            found = [f"does not parse: {str(e).splitlines()[0][:140]}"]
        else:
            found = problems(doc, schema)
        if found:
            bad += 1
            print(f"FAIL  issues/{f.name}")
            for p in found[:6]:
                print(f"        {p}")
    print(f"issue-file-lint — G75: {len(files) - bad}/{len(files)} issue files are what issues/schema.json says"
          + ("" if not bad else f" — {bad} refused"))
    return 1 if bad else 0


def self_test() -> int:
    schema = json.loads((REPO / "issues" / "schema.json").read_text(encoding="utf-8"))
    good = {"title": "t", "opened": datetime.date(2026, 10, 6), "severity": "high", "status": "open",
            "summary": "s", "tasks": [{"text": "x", "done": False}]}
    cases = [
        ("a well-formed file", good, 0),
        ("a status the schema does not have", {**good, "status": "done"}, 1),
        ("a task without `done`", {**good, "tasks": [{"text": "x"}]}, 1),
        ("`done` as a word, not a boolean", {**good, "tasks": [{"text": "x", "done": "yes"}]}, 1),
        ("a key no issue file has", {**good, "owner": "me"}, 1),
        ("a required key missing", {k: v for k, v in good.items() if k != "summary"}, 1),
        ("a date that is not one", {**good, "opened": "last week"}, 1),
        ("not a mapping at all", ["title"], 1),
    ]
    failed = 0
    for name, doc, want in cases:
        got = len(problems(doc, schema))
        ok = (got == 0) if want == 0 else (got >= 1)
        failed += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got} problem(s)")
    unknown = problems(good, {**schema, "maxProperties": 3})
    ok = any("does not check" in p for p in unknown)
    failed += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} a schema keyword this gate cannot check is refused, not ignored")
    print("issue-file-lint self-test:", "PASS" if not failed else f"{failed} FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else check(REPO))
