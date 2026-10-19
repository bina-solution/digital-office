#!/usr/bin/env python3
"""endpoint-credential-lint — gate G55: every call site of one endpoint uses the same credential.

    python3 scripts/refactor/endpoint-credential-lint.py [--self-test] [--verbose]

WHY THIS EXISTS — and why it is deliberately shaped as a CONSISTENCY gate.

By 2026-08-06 this repo had produced the same defect seven times, and the seventh is this one:

  1. trigger schemas      — caller sends a field the sub-workflow trigger never declared (G39)
  2. gate registry        — GATES.md and the scripts' own docstrings each claimed a number
  3. driver allowlist     — decide function returns a literal the switch has no case for (G41/G51)
  4. completion flags     — `Select Base` stamps BASE_EXTRACTION_COMPLETED while the decider reads
                            FIGURE_COMPANY_COMPLETED / FIGURE_TYPE_COMPLETED, so every document ran
                            both the consolidated step and the two it replaced
  5. TYPE casing          — one writer emitting `invoice` into a column six years of rows spell
                            `INVOICE`; routing normalised, every literal consumer silently skipped
                            those rows (G52)
  6. worker pin           — `wsl-10g` named in one place and not the other
  7. endpoint credentials — THIS: two nodes calling the same URL, one authenticated, one not

Every one is the same shape: **two places must agree about one fact, and nothing checks that they
do.** They are not seven incidents; they are one missing habit. The generalisable form — and the
reason this gate is worth more than a fix to the three files that prompted it — is:

    derive an equivalence class from the code, then assert every member agrees.

That form is cheap to instantiate and catches the *next* instance rather than the last one. G39,
G41, G51 and G52 are already instances of it; this is the fifth. When you find defect #8 of this
shape, add a class here rather than a bespoke script.

WHAT THIS GATE ASSERTS. Group every `n8n-nodes-base.httpRequest` node by the endpoint it addresses
— **(host, first path segment)**, not host alone. Host alone is too coarse to be useful here:
`n8n:5678` legitimately serves both `Settings Auth`-protected and `Incoming Documents`-protected
webhooks, so a host-level rule would be permanently red and teach people to ignore it. Within one
endpoint group, every call site must carry the same credential (same type and same name), or none.

A group where SOME sites authenticate and others do not is the interesting case: it means either a
node is missing auth it needs (it will 401 at runtime, and n8n reports that as a node error buried
in a batch), or the endpoint is not actually protected and the credential is cargo-culted.

ONLY LITERAL URLs are grouped. A URL built from an expression cannot be resolved statically, so it
is skipped rather than guessed at — false negatives by design, no false positives.
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys
# [2026-08-23] Blueprints are code (.workflow.ts) since 52b32aa4. This gate globbed *.json,
# matched zero files on disk, and reported PASS while checking nothing. n8n_blueprint is the
# ONE reader — see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.workflow.ts",)
HTTP_NODE = "n8n-nodes-base.httpRequest"
URL_RE = re.compile(r"^\s*=?\s*https?://(?P<host>[^/\s\"'{}]+)(?P<path>/[^\s\"'{}?]*)?")

# Endpoint groups that are known-mixed for a real reason. Each needs a justification.
ALLOW: dict[tuple[str, str], str] = {}


def endpoint_of(url: str) -> tuple[str, str] | None:
    """(host, first TWO path segments) for a literal URL; None if it is expression-built.

    Two segments, not one: every n8n webhook shares `/webhook` as its first segment, so a
    one-segment key lumps `/webhook/extract-base` together with `/webhook/settings-get` and the
    gate is permanently red on a distinction that is entirely legitimate. Two segments is the
    coarsest key that still names an actual endpoint here."""
    m = URL_RE.match(url or "")
    if not m:
        return None
    # an expression anywhere in the host or the matched path makes the target unknowable
    if "{{" in (url[:m.end()] or ""):
        return None
    path = (m.group("path") or "/").strip("/")
    segs = [s for s in path.split("/") if s][:2]
    return (m.group("host"), "/".join(segs))


def cred_of(node: dict) -> tuple:
    creds = node.get("credentials") or {}
    return tuple(sorted((k, str(v.get("name") or v.get("id"))) for k, v in creds.items()))


def collect(docs) -> dict[tuple[str, str], list[tuple[str, str, tuple]]]:
    groups: dict[tuple[str, str], list] = collections.defaultdict(list)
    for wid, doc in docs:
        for n in doc.get("nodes", []) or []:
            if n.get("type") != HTTP_NODE:
                continue
            ep = endpoint_of(str((n.get("parameters") or {}).get("url") or ""))
            if ep is None:
                continue
            groups[ep].append((wid, str(n.get("name")), cred_of(n)))
    return groups


def divergent(groups):
    out = []
    for ep, sites in sorted(groups.items()):
        if ep in ALLOW:
            continue
        shapes = {c for _w, _n, c in sites}
        if len(shapes) > 1:
            out.append((ep, sites, shapes))
    return out


SELF_TEST = [
    ("same endpoint, one authenticated one not — must catch", True, [
        ("wfA", {"nodes": [{"type": HTTP_NODE, "name": "a",
                            "parameters": {"url": "http://n8n:5678/webhook/extract"},
                            "credentials": {"httpBasicAuth": {"name": "Incoming Documents"}}}]}),
        ("wfB", {"nodes": [{"type": HTTP_NODE, "name": "b",
                            "parameters": {"url": "http://n8n:5678/webhook/extract"}}]}),
    ]),
    ("same host, DIFFERENT first path segment, different creds — must allow", False, [
        ("wfA", {"nodes": [{"type": HTTP_NODE, "name": "a",
                            "parameters": {"url": "http://n8n:5678/webhook/extract"},
                            "credentials": {"httpBasicAuth": {"name": "Incoming Documents"}}}]}),
        ("wfB", {"nodes": [{"type": HTTP_NODE, "name": "b",
                            "parameters": {"url": "http://n8n:5678/settings/get"},
                            "credentials": {"httpBasicAuth": {"name": "Settings Auth"}}}]}),
    ]),
    ("same endpoint, same credential — must allow", False, [
        ("wfA", {"nodes": [{"type": HTTP_NODE, "name": "a",
                            "parameters": {"url": "http://apitools:8080/documentOcr"},
                            "credentials": {"httpBasicAuth": {"name": "X"}}}]}),
        ("wfB", {"nodes": [{"type": HTTP_NODE, "name": "b",
                            "parameters": {"url": "http://apitools:8080/documentOcr"},
                            "credentials": {"httpBasicAuth": {"name": "X"}}}]}),
    ]),
    ("expression-built URL — must allow (never guess at an unresolvable target)", False, [
        ("wfA", {"nodes": [{"type": HTTP_NODE, "name": "a",
                            "parameters": {"url": "=http://{{ $json.host }}/webhook/extract"},
                            "credentials": {"httpBasicAuth": {"name": "X"}}}]}),
        ("wfB", {"nodes": [{"type": HTTP_NODE, "name": "b",
                            "parameters": {"url": "=http://{{ $json.host }}/webhook/extract"}}]}),
    ]),
    ("both unauthenticated — must allow (consistent is the invariant, not 'must have auth')", False, [
        ("wfA", {"nodes": [{"type": HTTP_NODE, "name": "a",
                            "parameters": {"url": "http://drive:8080/list"}}]}),
        ("wfB", {"nodes": [{"type": HTTP_NODE, "name": "b",
                            "parameters": {"url": "http://drive:8080/list"}}]}),
    ]),
]


def self_test() -> int:
    bad = 0
    for label, should, docs in SELF_TEST:
        got = bool(divergent(collect(docs)))
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] {'caught' if got else 'allowed':<8} "
              f"({'must catch' if should else 'must allow'}): {label}")
    print(f"\nG55 self-test: {len(SELF_TEST) - bad}/{len(SELF_TEST)} passed")
    return 1 if bad else 0


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()
    verbose = "--verbose" in sys.argv[1:]

    docs = []
    for pattern in BLUEPRINT_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                docs.append((str(path.relative_to(REPO)).replace("\\", "/"),
                             load_blueprint(str(path))))
            except (OSError, ValueError, CompileError) as e:
                print(f"  ! {path}: {e}")

    # A gate that read nothing has checked nothing. Where the blueprints cannot be compiled (no
    # node, no toolchain) every load above fails, and this used to end in PASS over zero of them.
    if not docs:
        print("G55 FAIL — read ZERO blueprint workflows, so nothing was checked.\n"
              "  globs: " + ", ".join(BLUEPRINT_GLOBS))
        return 1

    groups = collect(docs)
    findings = divergent(groups)

    if verbose:
        for ep, sites in sorted(groups.items()):
            print(f"  {ep[0]}/{ep[1]}  ({len(sites)} site(s))")

    if not findings:
        print(f"G55 PASS — {len(groups)} endpoint group(s) across {len(docs)} blueprint(s): "
              f"every call site of an endpoint agrees on its credential.")
        return 0

    print(f"G55 FAIL — {len(findings)} endpoint(s) are called with DIFFERENT credentials from\n"
          f"different places. Either a site is missing auth it needs (it 401s at runtime, reported\n"
          f"as a node error inside a batch) or the credential is cargo-culted where none is needed:\n")
    for (host, seg), sites, shapes in findings:
        print(f"  {host}/{seg}   — {len(shapes)} distinct credential shapes")
        for wf, node, cred in sites:
            desc = ", ".join(f"{k}:{nm}" for k, nm in cred) if cred else "<NO CREDENTIAL>"
            print(f"      {wf.split('/')[-1]:<30} {node[:34]:<36} {desc}")
        print()
    print("  Fix the odd one out, or add the group to ALLOW with the reason it legitimately differs.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
