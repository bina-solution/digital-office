#!/usr/bin/env python3
"""identity-header-lint — gate G86: enumerate every runtime consumer of the `X-authentik-*`
identity-header family MECHANICALLY, and make each one declare what it depends on.

    python3 scripts/refactor/identity-header-lint.py             # the enumeration, and the waivers
    python3 scripts/refactor/identity-header-lint.py --strict    # waivers ignored: each one is a finding
    python3 scripts/refactor/identity-header-lint.py --self-test

WHY THIS EXISTS. AGENTS.md rule 8: before an interface is tightened, every caller is enumerated
MECHANICALLY — by a gate, not by `grep` — because a hand survey silently misses whatever its pattern
misses and reports the miss as "no callers found". The interface here is the `X-authentik-*` header
family, and it is about to be tightened in the largest way available: item `core-006` replaces
authentik with a Go forward-auth service (`ai/context/core-go-forward-auth.md`; it is optimisation
phase 2 — authentik is 1132 MB across 4 containers, 24% of the platform's RAM,
`packaging/OPTIMISATION.md:39,45`). On the day the family stops being produced by authentik, every
consumer the manifests never named loses its identity SILENTLY — an app that reads no username falls
back to "owner" (`digital-assets`, `social-list`), an admin check stops matching (`indox`), a login
page comes back (`git`, `bina-ds`). Nothing in this directory enumerated them: G25
(`capability-use-lint`) compares a declared capability against the IMAGE a consumer's compose runs,
which is the right question for `sql` and the wrong one for a header.

THE GAP THIS GATE WAS WRITTEN FOR. Measured 2026-10-09, on the survey behind
`ai/context/core-go-forward-auth.md` §1.5: 24 files named the family, **10 of them runtime** — 7
readers and 3 producers/rewriters — while the `identity` capability graph in the manifests admitted
**three** consumers (`apps/my-docs` and `platform-base/console` require it, `platform-base/traefik`
wants it). A 3-vs-10 gap: a swap planned from the capability graph moves three files and breaks five.
This gate is step 0 of that migration, not a follow-up to it. It reproduces those numbers from the
tree — with one refinement it measured itself: `platform-base/console/app.py` is BOTH a reader
(:29,:80) and a rewriter (:507-508), so it is the seventh reader and a fourth producer. Ten files, of
which seven read.

WHAT IT CHECKS — four things, each of which fails the gate:

  1. THE ENUMERATION IS MECHANICAL, AND SAYS WHAT IT SCANNED (rule 8 step 2: the file count, not
     just the finding count). Every tracked file outside `legacy/` that names the family, with
     `file:line` for every match, from the same command a human would run —
     `git grep -nIiE 'x-authentik-' -- . ':!legacy'` — plus the denominator (`git ls-files`). The
     file count this gate prints is that command's count BY CONSTRUCTION, so a reader can compare it
     with a fresh grep and see a difference instead of trusting a promise.
  2. EACH NAMING FILE IS CLASSIFIED, and the classification is printed with its reason. A match that
     is only a comment or a docstring is a MENTION, not a consumer (read with `tokenize` + `ast` for
     python, by comment marker otherwise — `apps/dgo-extend/firewall.py:56` is prose inside the
     module docstring, `apps/bina-ds/harness/customize.sh:6` is a `#` comment, and neither reads
     anything). Docs, tests, plans, diagrams and one-shot tools are not code paths. A file in
     `platform-base/<x>/` whose app has no `app.json` is not an installed app.
  3. EVERY READER DECLARES IT, in its OWN manifest — `use: [{capability: "identity"}]`, or providing
     `identity` itself (`platform-base/authentik`, and the replacement's day). A reader whose
     manifest declares neither is a finding NAMING THE FILE, because that file is exactly what a swap
     planned from the graph would leave behind. Beside each reader the gate prints the routing
     declaration `platform/manager/reconcile.py` renders the edge's `authentik@file` middleware from
     (an `auth: sso` entry, and the hosts it gates): a reader behind the gate is receiving the family
     today, which is what makes its silence in the graph a defect rather than a mismatch.
  4. THE SUPPLY SIDE IS ENUMERATED, and both tables are anti-rot. Every file that writes, rewrites or
     strips the family is in `PRODUCERS` with a reason; a code path that changes the family in one of
     the shapes below and is NOT there FAILS, and a `PRODUCERS` entry that no longer names the family
     (or no longer emits it) FAILS. A `WAIVERS` entry that no longer names the family, or whose app
     has since DECLARED `identity`, FAILS — that is how this list shrinks itself as `core-006` lands
     (the G31/G34 anti-rot rule: a declaration matching nothing is stale).

WHAT IT DELIBERATELY DOES NOT CHECK.

  * The writer signs are narrow, and the gate says so rather than pretending otherwise: a line is
    treated as EMITTING the family when it is a YAML sequence item naming a header, an assignment of
    a quoted header name to a constant, an assignment onto the header key of a mapping, or a line
    carrying traefik's `customRequestHeaders` / `authResponseHeaders`. A producer using another shape
    is not recognised as one here — and is then judged as a reader (its app must declare `identity`),
    so the narrowness costs declarations, never silence.
  * Whether a reader is ENABLED in this office. `platform.state.yaml` is this deployment's choice;
    `my-docs`, `indox` and `social-list` are disabled here and are still consumers, because the
    contract belongs to the tree and every other office runs them (the gate is static and
    office-free on purpose).
  * The RENDER. The `auth: sso` fact is read from the manifest, not from `.generated/` (absent in a
    cold clone). What is actually routed is G6 (`auth-lint`) and G21 (`route-claim-lint`).
  * The `.env` surface being retired — `AUTHENTIK_BASE_URL`, `AUTHENTIK_SECRET_KEY`, the
    `AUTHENTIK_BOOTSTRAP_*` set — which is configuration, not a caller.
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import pathlib
import re
import subprocess
import sys
import textwrap
import tokenize
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]

#: The one place the family is spelled. `git grep -lIiE 'x-authentik-' -- . ':!legacy'` is the
#: command this must agree with, file for file.
GREP_CMD = ("git", "grep", "-nIiE", "x-authentik-", "--", ".", ":!legacy")

#: Files that WRITE, REWRITE or STRIP the family — the supply side, enumerated by hand and asserted
#: below (each must still name the family, and still emit it). `reads: True` marks the file that is
#: also a reader, so that it is held to the manifest declaration like every other reader.
PRODUCERS: dict[str, dict] = {
    "platform-base/traefik/config/authentik-forwardauth.yaml": {
        "reads": False,
        "reason":
            "the middleware — where the family is CREATED for every SSO-gated host: the forwardAuth's "
            "11 authResponseHeaders, and the 5 static ones written when `BBOX_SSO=off`. Referenced as "
            "`authentik@file`; a swap replaces this file's producer, not its consumers.",
    },
    "platform/manager/serve.py": {
        "reads": False,
        "reason":
            "the link door — renders a per-office identity middleware (`customRequestHeaders`, "
            "X-authentik-username = the serving office's mapped user) for a request that crossed a "
            "link. `authentik@file` runs FIRST in that chain, so the caller's own X-authentik-* is "
            "already overwritten before the mapped user is written.",
    },
    "apps/dgo-extend/link-proxy.py": {
        "reads": False,
        "reason":
            "the tunnel door — `IDENTITY_HEADER`/`IDENTITY_FAMILY`: writes `x-authentik-username` for "
            "the mapped user and REMOVES the whole `x-authentik-` family from a peer's request "
            "(another office's groups/e-mail/uid/token are that office's claims about itself, and an "
            "app here that read `X-authentik-groups` would take a peer's word for who is an "
            "administrator).",
    },
    "platform-base/console/app.py": {
        "reads": True,
        "reason":
            "the console's own door (:507-508) — drops the caller's `x-authentik-username` and writes "
            "the serving office's user before forwarding into a linked office. This is the ONE file "
            "that is both a rewriter and a reader, which is why the pair is written down.",
    },
}

#: Readers of the family whose manifest does not declare `identity`. KNOWN RED, wired anyway: each is
#: a real reader, the fix is one line of app.json, and it is `core-006`'s migration to land — a red
#: gate wired into CI would be red for every lane in the meantime, which is the owner's call and not
#: this gate's. Delete an entry the moment its app declares `identity`: the gate FAILS on a stale one.
#:
#: EMPTY since 2026-10-09: the five readers this list opened with (`indox`, `digital-assets`,
#: `social-list`, `git`, `bina-ds`) all declared `identity` in their own manifests in one commit —
#: every reading site was verified by hand first and all five are genuine readers (each routes
#: `auth: sso`, so the edge produces the family for it today). Kept as an empty dict, and kept wired:
#: the mechanism is what a future reader's warn phase needs (AGENTS.md rule 8), and the anti-rot
#: assertion below still fails on an entry whose app has since declared the capability.
WAIVERS: dict[str, str] = {}

DOC_SUFFIXES = {".md", ".svg", ".mmd", ".txt", ".rst", ".html", ".png", ".pdf"}
#: Path segments that hold something other than a code path.
NON_CODE_SEGMENTS = {"tests": "test", "test": "test", "__tests__": "test",
                     "plans": "plan", "diagrams": "diagram", "tools": "tooling"}
NON_CODE_ROOTS = {"ai": "doc", "issues": "doc", "docs": "doc"}

#: A line that EMITS the family (see the docstring for what this knowingly cannot see).
WRITE_SIGNS = (
    re.compile(r"^\s*-\s*[\"']?x-authentik-", re.I),        # a YAML list of headers to emit
    re.compile(r"=\s*b?[\"']x-authentik-", re.I),            # a constant naming the header to write
    re.compile(r"x-authentik-[a-z-]*[\"']?\]\s*=", re.I),    # fwd["X-authentik-username"] = user
    re.compile(r"customrequestheaders|authresponseheaders", re.I),
)
COMMENT_STARTS = ("#", "//", "/*", "*", "<!--", ";", "--")
#: In a workflow/compose file a match can also be a LABEL — a step's `- name:` or a `description:`,
#: which says what something is called and reads nothing. (A compose env line, `- VAR=X-authentik-…`,
#: is not this shape and stays a consumer.)
YAML_LABEL = re.compile(r"^\s*-?\s*(name|description)\s*:")

#: A checker beside the gates names the family in order to SEARCH for it — this gate included, which
#: must spell the family to enumerate it. Nothing in this directory is a service, so nothing in it
#: can consume the family; a sibling enumerator written later is exempt by the same rule, on purpose.
GATE_DIR = "scripts/refactor/"


# ── enumeration (rule 8 step 1+2) ──────────────────────────────────────────────────────────────
def enumerate_family() -> dict[str, list[tuple[int, str]]]:
    """{path: [(line, the matched line's text)]} — from the command in GREP_CMD, so the count this
    gate prints is that command's count by construction."""
    p = subprocess.run(GREP_CMD, cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode not in (0, 1):          # 1 = no matches, which is a legitimate answer
        raise SystemExit(f"G86 FAIL — could not enumerate: `{' '.join(GREP_CMD)}` exited "
                         f"{p.returncode}\n  {p.stderr.strip()[:400]}")
    found: dict[str, list[tuple[int, str]]] = {}
    for line in p.stdout.splitlines():
        m = re.match(r"^(.+?):(\d+):(.*)$", line)
        if not m:
            continue
        path, n, text = m.group(1), int(m.group(2)), m.group(3)
        if path.startswith("legacy/"):
            continue
        found.setdefault(path, []).append((n, text))
    for path in found:
        found[path].sort()
    return found


def tracked_count() -> int | None:
    """The denominator: tracked files, legacy/ excluded. None = could not read it (said, not skipped)."""
    p = subprocess.run(("git", "ls-files"), cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        return None
    return sum(1 for ln in p.stdout.splitlines() if ln and not ln.startswith("legacy/"))


# ── classification ────────────────────────────────────────────────────────────────────────────
def kind_reason(path: str) -> str | None:
    """Why this file is not a code path, or None when it may be one."""
    pure = pathlib.PurePosixPath(path)
    parts = pure.parts
    if pure.suffix.lower() in DOC_SUFFIXES:
        return "doc — a prose or asset file"
    if parts and parts[0] in NON_CODE_ROOTS:
        return f"doc — {parts[0]}/ is documentation"
    name = pure.name
    if re.match(r"^test_.*\.py$|.*_test\.go$|.*\.test\.(js|ts|tsx)$|^conftest\.py$", name):
        return "test — a test file, not a code path"
    for seg in parts:
        if seg in NON_CODE_SEGMENTS:
            return f"{NON_CODE_SEGMENTS[seg]} — a {seg}/ file"
    return None


def mention_only(text: str, suffix: str, lines: list[int]) -> bool:
    """True when EVERY match is a comment or a docstring — a mention, not a read.

    Python is read with `tokenize` (COMMENT tokens) and `ast` (the docstring line span a module,
    class or function opens with), because a module docstring is where this estate explains itself
    and a prose sentence naming the family is not a consumer. Any other language: every matched line
    must start with a comment marker."""
    if suffix != ".py":
        body = text.splitlines()
        for ln in lines:
            if not (0 < ln <= len(body)):
                return False
            line = body[ln - 1]
            if line.strip().startswith(COMMENT_STARTS):
                continue
            if suffix in (".yml", ".yaml") and YAML_LABEL.match(line):
                continue
            return False
        return True
    ment: set[int] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body_nodes = getattr(node, "body", [])
                if (body_nodes and isinstance(body_nodes[0], ast.Expr)
                        and isinstance(body_nodes[0].value, ast.Constant)
                        and isinstance(body_nodes[0].value.value, str)):
                    start = body_nodes[0].lineno
                    ment.update(range(start, (body_nodes[0].end_lineno or start) + 1))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                ment.add(tok.start[0])
    except tokenize.TokenError:
        return False
    return all(ln in ment for ln in lines)


def has_write_sign(texts: list[str]) -> bool:
    return any(sign.search(t) for t in texts for sign in WRITE_SIGNS)


def owner_of(path: str) -> tuple[str, pathlib.Path | None]:
    """(the app id that owns this file, its app.json — or None when the directory has none)."""
    parts = pathlib.PurePosixPath(path).parts
    if len(parts) > 1 and parts[0] in ("apps", "platform-base"):
        app_id = f"{parts[0]}/{parts[1]}"
        manifest = REPO / parts[0] / parts[1] / "app.json"
        return app_id, (manifest if manifest.exists() else None)
    return f"layer 0 ({parts[0] if parts else path})", None


def declares_identity(manifest: dict) -> tuple[bool, list[str]]:
    """(does it declare the dependency, what it declares it as) — the capability graph's own edge."""
    uses = [u.get("capability") for u in (manifest.get("use") or []) if isinstance(u, dict)]
    provides = [c.get("name") for c in (manifest.get("capabilities") or []) if isinstance(c, dict)]
    if "identity" in uses:
        return True, ["use: identity"]
    if "identity" in provides:
        return True, ["provides: identity"]
    return False, []


def sso_hosts(manifest: dict) -> list[str]:
    """The `auth: sso` routing entries — what `reconcile.py` renders the edge's authentik@file
    middleware from. A reader behind one of these receives the family today."""
    out: list[str] = []
    for r in (manifest.get("routing") or []):
        if not isinstance(r, dict) or r.get("auth") != "sso":
            continue
        hosts = r.get("hosts") or r.get("host") or []
        if isinstance(hosts, str):
            hosts = [hosts]
        out.extend(str(h) for h in hosts)
    return out


def load_manifest(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"G86 FAIL — {path.relative_to(REPO)} is not readable JSON: {e}")


def line_list(lines: list[int]) -> str:
    return ",".join(str(n) for n in lines)


# ── self-test (prove each rule, so a green run means something) ───────────────────────────────
def self_test() -> int:
    py_doc = '"""A module.\n\nIt mentions x-authentik-username in prose.\n"""\nA = 1\n'
    py_comment = "X = 1  # the edge writes x-authentik-username\n"
    py_code = 'u = request.headers.get("x-authentik-username") or "owner"\n'
    py_write = 'fwd["X-authentik-username"] = door["user"]\n'
    py_const = 'IDENTITY_HEADER = b"x-authentik-username"\n'
    py_read_map = "u = {k.replace('X-authentik-', ''): request.headers.get(k) for k in H}\n"
    yaml_item = "        authResponseHeaders:\n          - X-authentik-username\n"
    yaml_delegate = "      - FORGEJO__security__REVERSE_PROXY_AUTHENTICATION_USER=X-authentik-username\n"
    sh_comment = "# established (X-authentik-username, added by Traefik's forwardAuth)\n"
    manifest_ok = {"use": [{"capability": "identity"}],
                   "routing": [{"auth": "sso", "hosts": ["console"]}]}
    manifest_silent = {"use": [{"capability": "secrets"}],
                       "routing": [{"auth": "sso", "hosts": ["git", "forge"]}]}
    manifest_provider = {"capabilities": [{"name": "identity"}]}

    cases: list[tuple[str, object, object]] = [
        ("a python docstring is a mention", mention_only(py_doc, ".py", [3]), True),
        ("a python comment is a mention", mention_only(py_comment, ".py", [1]), True),
        ("python code is not a mention", mention_only(py_code, ".py", [1]), False),
        ("a docstring next to code does not hide the code",
         mention_only(py_doc + py_code, ".py", [3, 6]), False),
        ("a shell comment is a mention", mention_only(sh_comment, ".sh", [1]), True),
        ("a workflow step's name: is a label, not a read",
         mention_only("      - name: every consumer of the X-authentik-* family is enumerated\n",
                      ".yml", [1]), True),
        ("a compose env line is not a label", mention_only(yaml_delegate, ".yml", [1]), False),
        ("a mapping assignment onto the header emits it", has_write_sign([py_write]), True),
        ("a constant naming the header emits it", has_write_sign([py_const]), True),
        ("a YAML header list emits it", has_write_sign(yaml_item.splitlines()), True),
        ("a reader with a fallback emits nothing", has_write_sign([py_code]), False),
        ("a read map that strips the prefix emits nothing", has_write_sign([py_read_map]), False),
        ("a compose delegation emits nothing", has_write_sign([yaml_delegate]), False),
        ("docs/tests/plans/diagrams/tools are not code paths",
         [kind_reason(p) for p in ("a/b.md", "a/tests/t.py", "a/test_x.py", "a/plans/p.yaml",
                                   "a/diagrams/d.json", "a/tools/t.py", "apps/x/app.py")],
         ["doc — a prose or asset file", "test — a tests/ file", "test — a test file, not a code path",
          "plan — a plans/ file", "diagram — a diagrams/ file", "tooling — a tools/ file", None]),
        ("a manifest that declares identity is declared",
         declares_identity(manifest_ok), (True, ["use: identity"])),
        ("the provider declares itself", declares_identity(manifest_provider), (True, ["provides: identity"])),
        ("a manifest that does not, is not", declares_identity(manifest_silent), (False, [])),
        ("auth: sso entries are the hosts the edge gates", sso_hosts(manifest_silent), ["git", "forge"]),
    ]
    bad = 0
    for name, got, want in cases:
        ok = got == want
        bad += not ok
        print(f"  [{'ok ' if ok else 'FAIL'}] {name}" + ("" if ok else f" (got {got!r}, want {want!r})"))
    print(f"identity-header-lint self-test: {len(cases) - bad}/{len(cases)} passed")
    return 1 if bad else 0


# ── the gate ──────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="G86 — consumers of the X-authentik-* header family")
    ap.add_argument("--strict", action="store_true",
                    help="ignore WAIVERS: report the known-red readers as findings (the pre-fix red)")
    ap.add_argument("--self-test", action="store_true", help="prove each rule on synthetic input")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    found = enumerate_family()
    scanned = tracked_count()
    problems: list[str] = []

    supply: list[dict] = []          # declared producers/rewriters
    readers: list[dict] = []         # code paths that read the family
    nonruntime: list[tuple[str, list[int], str]] = []
    emitted_undeclared: list[dict] = []

    for path in sorted(found):
        lines = [n for n, _ in found[path]]
        texts = [t for _, t in found[path]]
        spec = PRODUCERS.get(path)
        reason = None if spec else kind_reason(path)
        if reason:
            nonruntime.append((path, lines, reason))
            continue
        if path.startswith(GATE_DIR):
            nonruntime.append((path, lines, "a checker beside the gates — it names the family in "
                                            "order to search for it, and no service lives here"))
            continue
        text = ""
        if not spec:
            try:
                text = (REPO / path).read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                problems.append(f"{path}: names the family and could not be read ({e}) — the "
                                f"classification is incomplete, which is a failure, not a skip.")
                continue
            if mention_only(text, pathlib.PurePosixPath(path).suffix, lines):
                nonruntime.append((path, lines, "comment or docstring only — a mention, not a consumer"))
                continue

        emits = bool(spec) or has_write_sign(texts)
        owner, manifest = owner_of(path)
        if manifest is None and owner.startswith("platform-base/"):
            nonruntime.append((path, lines,
                               f"not an app — {owner}/ has no app.json, so no manifest declares "
                               f"anything here"))
            continue

        rec = {"path": path, "lines": lines, "owner": owner, "manifest": manifest,
               "emits": emits, "reads": (spec or {}).get("reads", not spec),
               "declared": False, "as": [], "sso": [], "waiver": WAIVERS.get(path, ""),
               "reason": (spec or {}).get("reason", "")}
        if manifest is not None:
            m = load_manifest(manifest)
            rec["declared"], rec["as"] = declares_identity(m)
            rec["sso"] = sso_hosts(m)
        if spec:
            supply.append(rec)
        if rec["reads"]:
            readers.append(rec)
        if emits and not spec:
            emitted_undeclared.append(rec)

    # ── findings ──────────────────────────────────────────────────────────────────────────────
    undeclared = [r for r in readers if not r["declared"]]
    findings: list[str] = []
    for r in undeclared:
        if r["waiver"] and not args.strict:
            continue
        if r["manifest"] is None:
            why = (f"'{r['owner']}' has no manifest to declare it in — a layer-0 file reading the "
                   f"family declares it to nobody")
        else:
            why = (f"'{r['owner']}/app.json' declares no `use: [{{capability: \"identity\"}}]` "
                   f"(and does not provide `identity`)")
        sso = ("routes auth: sso on " + ", ".join(r["sso"])) if r["sso"] else "routes NO auth: sso host"
        findings.append(f"{r['path']}:{line_list(r['lines'])}\n      {why}\n      it {sso} — so "
                        f"the edge produces the family for it today")
    for r in emitted_undeclared:
        findings.append(
            f"{r['path']}:{line_list(r['lines'])}\n      emits/rewrites the family and is not in "
            f"PRODUCERS — the supply side is enumerated too, because a swap moves it as well.")
    for entry in PRODUCERS:
        if entry not in found:
            problems.append(f"PRODUCERS names {entry}, which no longer names the family — stale entry "
                            f"(delete it, or say what it emits now).")
        elif not has_write_sign([t for _, t in found[entry]]):
            problems.append(
                f"PRODUCERS names {entry}, but no line of it emits the family in a shape this gate "
                f"knows ({', '.join(s.pattern for s in WRITE_SIGNS)}).\n      Either the family moved "
                f"out of it — delete the entry — or it emits it in a shape the gate cannot see, which "
                f"is a gate bug to fix, not to waive.")
    for entry, reason in WAIVERS.items():
        if entry not in found:
            problems.append(f"WAIVERS names {entry}, which no longer names the family — stale waiver "
                            f"(delete it). The reason it carried: {reason}")
            continue
        rec = next((r for r in readers if r["path"] == entry), None)
        if rec is None:
            problems.append(f"WAIVERS names {entry}, which is no longer a runtime reader — stale "
                            f"waiver (delete it).")
        elif rec["declared"]:
            problems.append(f"WAIVERS names {entry}, whose app now declares {'/'.join(rec['as'])} — "
                            f"stale waiver: delete it, and the gate enforces the declaration.")

    # ── the report ────────────────────────────────────────────────────────────────────────────
    print("G86 identity-header-lint — the X-authentik-* identity-header family, enumerated "
          "mechanically.\n")
    print(f"scanned {scanned if scanned is not None else '?'} tracked file(s) outside legacy/; "
          f"{len(found)} of them name the family ({sum(len(v) for v in found.values())} matching "
          f"line(s)).")
    if scanned is None:
        print("  the denominator could NOT be read (`git ls-files` failed) — said, not assumed zero")
    print("  this is the command it ran, and the one whose number it must equal:")
    print(f"    {' '.join(GREP_CMD)}")
    print(f"    (with -lIiE instead of -nIiE that command must print the same {len(found)} file(s))\n")

    def show(tag: str, path: str, lines: list[int], note: str) -> None:
        print(f"  {tag:<12} {path}:{line_list(lines)}")
        for chunk in ([note] if note else []):
            for part in textwrap.wrap(chunk, 100, break_long_words=False):
                print(f"               {part}")

    print(f"the supply side — {len(supply)} producer(s)/rewriter(s), enumerated by hand and asserted "
          f"by this gate:")
    for r in supply:
        note = r["reason"]
        if r["reads"]:
            note += " · " + (f"also a reader, declared by its manifest ({', '.join(r['as'])})"
                             if r["declared"] else "also a reader, UNDECLARED — a finding")
        show("producer", r["path"], r["lines"], note)
    print(f"\nthe readers — {len(readers)} code path(s) read the family; each one's manifest must "
          f"declare it:")
    for r in readers:
        if r["declared"]:
            note = f"declared by its manifest ({', '.join(r['as'])})"
        elif r["waiver"]:
            note = ("UNDECLARED — a finding (--strict)" if args.strict else
                    "UNDECLARED — waived (known red, AGENTS.md rule 8's warn phase)")
        else:
            note = "UNDECLARED — a finding"
        if r["path"] in PRODUCERS:
            note += " · also a producer/rewriter (above)"
        note += " · " + (f"auth: sso on {', '.join(r['sso'])}" if r["sso"] else "no auth: sso route")
        if r["waiver"] and not r["declared"]:
            note += f"\n         why waived: {r['waiver']}"
        show("reader", r["path"], r["lines"], note)
    print(f"\nnot consumers — {len(nonruntime)} file(s) name the family without being a code path:")
    for reason in sorted(Counter(r for _, _, r in nonruntime)):
        group = [(p, ln) for p, ln, r in nonruntime if r == reason]
        print(f"  {reason} ({len(group)}):")
        for path, lines in group:
            print(f"    {path}:{line_list(lines)}")

    runtime = len({r["path"] for r in supply} | {r["path"] for r in readers})
    if problems:
        print("\nG86 FAIL (the gate's own tables) —")
        for p in problems:
            print(f"  {p}")
        return 1
    if findings:
        print(f"\nG86 FAIL — {len(findings)} finding(s)"
              + (" (--strict: waivers ignored)" if args.strict else "")
              + ". A consumer of the family that its manifest does not name is a file a swap planned "
                "from the capability graph leaves behind, with no identity and no error:")
        for f in findings:
            print(f"  {f}")
        print("\n  Fix it in the manifest, not in this gate: add "
              "`\"use\": [{\"capability\": \"identity\"}]` to the app's app.json — that is the edge the "
              "migration reads. If the file emits the family rather than reading it, add it to "
              "PRODUCERS with what it emits.")
        return 1

    print(f"\nG86 PASS — {runtime} file(s) name the family in a code path: {len(readers)} read it, "
          f"{len(supply)} emit/rewrite it ({len({r['path'] for r in supply} & {r['path'] for r in readers})} "
          f"of them does both).")
    print(f"  readers: {len(readers) - len(undeclared)} declared by their manifest, {len(undeclared)} "
          f"undeclared and waived ({len(WAIVERS)} known red — delete a WAIVERS entry the moment its app "
          f"declares `identity`, and this gate enforces it).")
    print(f"  producers: {len(supply)} enumerated in PRODUCERS, each asserted to still emit it.")
    print(f"  the other {len(nonruntime)} file(s) name the family without consuming it — listed above "
          f"with the rule that excluded each.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
