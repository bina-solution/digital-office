#!/usr/bin/env python3
"""vault-sources-lint — gate G112: every `ai/context` document is either published to the office's vault or
excluded BY NAME, with a reason.

    python3 scripts/refactor/vault-sources-lint.py [--json]

`apps/obsidian/vault.yaml` is the one declaration of what a fresh vault holds (DGO-1642). A vault is
what an agent reads first in a session, so the two ways it goes wrong are both silent:

  * a document that should be in it is not — the agent answers from a vault it believes is complete;
  * a document that should NOT be in it is — a client's vault carries the business's own herd, or a
    draft nobody meant to publish.

Neither is visible by reading the vault, so this gate makes the DECISION the thing that cannot be
forgotten: a new `ai/context/*.md` fails here until it is either `notes:`-declared, `herd_docs:`-
declared, or `excluded:` with a `why`. A new file is therefore always seen by a person once, at the
moment it is added, and never leaks by default.

The same rule as G9 (the directory is the layer) and G27 (one palette names every colour): the
declaration is the artifact, and the gate is what keeps the declaration honest.

Exit 0 = every document is accounted for. Exit 1 = at least one is not (each is named on its own line).
"""
import argparse
import fnmatch
import json
import pathlib
import sys

try:
    import yaml
except ImportError:                                  # the repo's other gates assume it too
    sys.exit("PyYAML required")

REPO = pathlib.Path(__file__).resolve().parents[2]
CONTEXT = REPO / "ai" / "context"
MANIFEST = REPO / "apps" / "obsidian" / "vault.yaml"
#: The directories under ai/context that are scanned. A directory is scanned by its .md files, and a
#: declaration may name the directory itself (`ai/context/research`), which covers everything in it.
SKIP_DIRS = {"archive"}


def load(manifest=MANIFEST):
    if not manifest.is_file():
        return None
    try:
        return yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        return {"__error__": f"vault.yaml does not parse: {error}"}


def patterns(man):
    """Every path the manifest accounts for: declared notes, herd docs, and exclusions."""
    out = []
    for row in (man.get("notes") or []) + (man.get("herd_docs") or []):
        frm = (row or {}).get("from")
        if frm:
            out.append(("declared", str(frm)))
    for row in (man.get("excluded") or []):
        if isinstance(row, dict) and row.get("path"):
            out.append(("excluded", str(row["path"])))
    return out


def covered(rel, pats):
    """Is `rel` (repo-relative, e.g. ai/context/dgo-herd.md) accounted for by one of `pats`?

    A pattern matches its exact path, anything UNDER it (a directory), or a glob. Matching is on the
    repo-relative posix path, and a patterns list is read as "…and everything below", because that is
    what a person means by naming a directory.
    """
    for kind, pat in pats:
        pat = pat.rstrip("/")
        if rel == pat or fnmatch.fnmatch(rel, pat) or rel.startswith(pat + "/"):
            return kind
    return None


def documents(root=CONTEXT):
    """Every .md under `root`, named the way the manifest names things: repo-relative when the tree
    is the repository's own (the normal case, and the only form a human writes), absolute when a test
    points the gate at a temp tree — so the gate can be exercised without a repository."""
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        yield p.relative_to(REPO).as_posix() if p.is_relative_to(REPO) else p.as_posix()


def main(argv=None):
    ap = argparse.ArgumentParser(description="every ai/context doc is published or excluded by name")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--context", default=str(CONTEXT))
    args = ap.parse_args(argv)

    manifest = pathlib.Path(args.manifest)
    man = load(manifest)
    if man is None:
        print(f"FAIL  no vault manifest at {manifest.relative_to(REPO) if manifest.is_relative_to(REPO) else manifest}\n"
              f"      the vault's sources are undeclared, so nothing can be checked")
        return 1
    if man.get("__error__"):
        print(f"FAIL  {man['__error__']}")
        return 1

    pats = patterns(man)
    root = pathlib.Path(args.context)
    rows, missing = [], []
    for rel in documents(root):
        kind = covered(rel, pats)
        rows.append({"doc": rel, "accounted": kind})
        if not kind:
            missing.append(rel)

    # The other direction: a declaration that names a file nobody has is a stale promise.
    declared = []
    for row in (man.get("notes") or []) + (man.get("herd_docs") or []):
        frm = (row or {}).get("from")
        if frm and "*" not in frm:
            p = pathlib.Path(str(frm)) if pathlib.Path(str(frm)).is_absolute() else REPO / str(frm)
            if not p.exists():
                declared.append(str(frm))

    if args.json:
        print(json.dumps({"scanned": len(rows), "undeclared": missing,
                          "missing_sources": declared, "rows": rows}, indent=2, ensure_ascii=False))
    else:
        where = root.relative_to(REPO).as_posix() if root.is_relative_to(REPO) else root.as_posix()
        print(f"vault-sources-lint — scanned {len(rows)} document(s) under {where}")
        for rel in missing:
            print(f"  UNDECLARED {rel}")
            print(f"             → add it to apps/obsidian/vault.yaml under notes:/herd_docs:, or under")
            print(f"               excluded: with a `why`, and say which in the commit")
        for rel in declared:
            print(f"  MISSING    {rel} (declared in vault.yaml, not in the repository)")
        ok = not missing and not declared
        print(("OK    every document is published or excluded by name"
               if ok else f"FAIL  {len(missing)} undeclared, {len(declared)} declared-but-missing"))
    return 0 if not missing and not declared else 1


if __name__ == "__main__":
    sys.exit(main())
