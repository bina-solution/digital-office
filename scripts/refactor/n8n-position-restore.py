#!/usr/bin/env python3
"""n8n-position-restore — put every pre-existing node's canvas position back to its committed value.

    python3 scripts/refactor/n8n-position-restore.py --check     # report only, exit 1 if any file would change
    python3 scripts/refactor/n8n-position-restore.py             # restore (writes)
    python3 scripts/refactor/n8n-position-restore.py FILE...     # only these files
    python3 scripts/refactor/n8n-position-restore.py --exclude 'indoxV2Actions*'

WHY THIS EXISTS. In n8n, `nodes[].position` is not decoration — it is EXECUTION SEMANTICS. Under
`settings.executionOrder: "v1"` (every workflow here), when one node's output fans out to several
downstream nodes, n8n runs those branches in an order derived from canvas position. The load-bearing
case is a `splitInBatches` ("Loop Over Items") loop: the action lane and the lane that returns to the
loop node are two branches of the same fan-out, and their relative canvas height decides whether the
work runs per batch or whether the loop drains first and the work runs afterwards. The workflow
"succeeds" either way, so getting it wrong is silent.

`scripts/refactor/n8n-layout.py` recomputed positions for every blueprint from the graph alone. That
is a semantic rewrite of 80 committed workflows disguised as a cosmetic one. This script is the
inverse: for every node that exists in `git show HEAD:<file>`, its position is restored to the
committed literal **byte for byte** (the raw numeric text is copied, so an int stays an int and a
float keeps its spelling). Nothing else in the file is touched.

NODES ADDED SINCE HEAD keep a position, because they must have one — but it is derived in the
ORIGINAL coordinate space, anchored to the restored positions of their graph neighbours, never from
the recomputed grid (which lives in a completely different coordinate range and would scatter a new
node thousands of units away from the cluster it belongs to). Placement is: anchor on a placed
predecessor (else a placed successor), offset by the file's own median node spacing, then pushed
down in grid steps until its footprint collides with nothing. Where the anchor is a fan-out whose
other branch loops back, the new node is placed ABOVE that loop-back branch head, so it inherits the
invariant rather than breaking it.

SURGICAL WRITES. Same mechanism as n8n-layout.py: the `"position": [x, y]` numeric literals are
located in raw text in node-array order (asserted 1:1 against the parsed `nodes[]`) and only those
literals are replaced. Key order, whitespace, `parameters`, `connections`, `tags`, credentials and
notes are left untouched, so this composes safely with the other in-flight edits in these files and
can never clobber another lane's work.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import pathlib
import re
import subprocess
import sys
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.json",)

GRID = 20
FOOTPRINT_W, FOOTPRINT_H = 200, 100
DEFAULT_DX, DEFAULT_DY = 220, 140

_POSITION_RE = re.compile(
    r'("position"\s*:\s*\[\s*)(-?[0-9]+(?:\.[0-9]+)?)(\s*,\s*)(-?[0-9]+(?:\.[0-9]+)?)(\s*\])'
)


class RestoreError(Exception):
    """A file whose shape makes a safe surgical restore impossible."""


# ── raw-text position extraction ────────────────────────────────────────────
def position_literals(raw: str, doc: dict) -> dict[str, tuple[str, str]]:
    """{node name: (x_literal, y_literal)} taking the numeric text verbatim from `raw`.

    Occurrences are matched to `nodes[]` by order, which is exactly how the file serialises them;
    a count mismatch means some other `"position"` key exists in the document (e.g. inside node
    parameters) and the order mapping would be wrong, so we refuse rather than guess."""
    nodes = doc.get("nodes", []) or []
    matches = list(_POSITION_RE.finditer(raw))
    if len(matches) != len(nodes):
        raise RestoreError(
            f'{len(matches)} "position" literal(s) in the raw text but {len(nodes)} node(s) in the '
            f"parsed JSON — refusing an order-based mapping")
    return {n["name"]: (m.group(2), m.group(4)) for n, m in zip(nodes, matches)}


def rewrite_positions(raw: str, doc: dict, new_lit: dict[str, tuple[str, str]]) -> str:
    """Replace only the numeric literals inside each node's `"position": [x, y]`."""
    nodes = doc.get("nodes", []) or []
    matches = list(_POSITION_RE.finditer(raw))
    if len(matches) != len(nodes):
        raise RestoreError("position/node count mismatch at rewrite time")
    out, cursor = [], 0
    for node, m in zip(nodes, matches):
        xs, ys = new_lit[node["name"]]
        out.append(raw[cursor:m.start(2)])
        out.append(xs)
        out.append(raw[m.end(2):m.start(4)])
        out.append(ys)
        cursor = m.end(4)
    out.append(raw[cursor:])
    return "".join(out)


# ── placement for nodes that did not exist at HEAD ──────────────────────────
def main_edges(doc: dict) -> list[tuple[str, int, str]]:
    names = {n.get("name") for n in (doc.get("nodes") or [])}
    edges = []
    for src, by_type in (doc.get("connections") or {}).items():
        if src not in names:
            continue
        for out_idx, lst in enumerate(((by_type or {}).get("main")) or []):
            for c in (lst or []):
                tgt = (c or {}).get("node")
                if tgt in names:
                    edges.append((src, out_idx, tgt))
    return edges


def reaches(adj: dict[str, list[str]], start: str, goal: str, limit: int = 2000) -> bool:
    seen, stack = set(), [start]
    while stack:
        cur = stack.pop()
        if cur == goal:
            return True
        if cur in seen or len(seen) > limit:
            continue
        seen.add(cur)
        stack.extend(adj.get(cur, ()))
    return False


def median_spacing(placed: dict[str, tuple[float, float]], edges) -> tuple[int, int]:
    """The file's own idea of one hop, so new nodes match the hand-made layout's scale."""
    dxs = [abs(placed[t][0] - placed[s][0]) for s, _i, t in edges
           if s in placed and t in placed and placed[t][0] != placed[s][0]]
    dys = [abs(placed[t][1] - placed[s][1]) for s, _i, t in edges
           if s in placed and t in placed and placed[t][1] != placed[s][1]]
    dxs.sort(); dys.sort()
    dx = dxs[len(dxs) // 2] if dxs else DEFAULT_DX
    dy = dys[len(dys) // 2] if dys else DEFAULT_DY
    return int(max(160, min(dx, 600))), int(max(100, min(dy, 400)))


def place_new_nodes(doc: dict, placed: dict[str, tuple[float, float]],
                    to_place: list[str]) -> dict[str, tuple[int, int]]:
    """Position nodes absent from HEAD, in the original coordinate space, anchored on neighbours."""
    edges = main_edges(doc)
    succ: dict[str, list[str]] = defaultdict(list)
    pred: dict[str, list[str]] = defaultdict(list)
    out_of: dict[tuple[str, str], int] = {}
    for s, i, t in edges:
        succ[s].append(t)
        pred[t].append(s)
        out_of[(s, t)] = i

    dx, dy = median_spacing(placed, edges)
    result: dict[str, tuple[int, int]] = {}
    occupied = dict(placed)

    def collides(x: float, y: float) -> bool:
        return any(abs(x - ox) < FOOTPRINT_W and abs(y - oy) < FOOTPRINT_H
                   for ox, oy in occupied.values())

    def settle(x: float, y: float) -> tuple[int, int]:
        for step in range(0, 60):
            cy = y + step * GRID * 4
            if not collides(x, cy):
                return int(round(x)), int(round(cy))
        return int(round(x)), int(round(y + 60 * GRID * 4))

    remaining = list(to_place)
    progress = True
    while remaining and progress:
        progress = False
        for name in list(remaining):
            anchors_p = [p for p in pred.get(name, []) if p in occupied]
            anchors_s = [s for s in succ.get(name, []) if s in occupied]
            if anchors_p:
                a = anchors_p[0]
                ax, ay = occupied[a]
                base_x, base_y = ax + dx, ay
                # loop-lane invariant: if the anchor also fans out to a branch that returns to it,
                # this new node is an action lane and must sit ABOVE that loop-back branch head.
                sib = [t for t in succ.get(a, []) if t != name and t in occupied]
                loopers = [t for t in sib
                           if t == a or reaches(succ, t, a)]
                if loopers:
                    top = min(occupied[t][1] for t in loopers)
                    base_y = min(base_y, top - dy)
            elif anchors_s:
                a = anchors_s[0]
                ax, ay = occupied[a]
                base_x, base_y = ax - dx, ay
            else:
                continue
            pos = settle(base_x, base_y)
            result[name] = pos
            occupied[name] = pos
            remaining.remove(name)
            progress = True

    if remaining:
        # islands with no committed neighbour at all — a row below everything, in file order
        base_x = min((x for x, _ in occupied.values()), default=0)
        base_y = max((y for _, y in occupied.values()), default=0) + 2 * FOOTPRINT_H
        for i, name in enumerate(sorted(remaining)):
            pos = (int(base_x + i * (FOOTPRINT_W + 40)), int(base_y))
            result[name] = pos
            occupied[name] = pos
    return result


# ── per-file driver ─────────────────────────────────────────────────────────
def head_text(rel: str) -> str | None:
    p = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=REPO,
                       capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def structural_fingerprint(doc: dict) -> str:
    """Everything except node position — proves the rewrite changed nothing else."""
    d = json.loads(json.dumps(doc))
    for n in d.get("nodes", []) or []:
        n.pop("position", None)
    return json.dumps(d, sort_keys=True)


def process(path: pathlib.Path, check_only: bool) -> tuple[str, str]:
    try:
        rel = path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return "error", "outside the repo"

    ht = head_text(rel)
    if ht is None:
        return "skip", "not in HEAD (new file — nothing committed to restore to)"

    try:
        cur_raw = path.read_text(encoding="utf-8")
        cur = json.loads(cur_raw)
        old = json.loads(ht)
    except (OSError, ValueError) as e:
        return "error", f"cannot read/parse: {e}"

    if not isinstance(cur, dict) or "nodes" not in cur:
        return "skip", "not a single-workflow document"

    try:
        cur_lit = position_literals(cur_raw, cur)
        old_lit = position_literals(ht, old)
    except RestoreError as e:
        return "error", str(e)

    old_num = {n["name"]: (n["position"][0], n["position"][1])
               for n in (old.get("nodes") or []) if isinstance(n.get("position"), list)}

    cur_names = [n["name"] for n in (cur.get("nodes") or [])]
    preexisting = [n for n in cur_names if n in old_lit]
    added = [n for n in cur_names if n not in old_lit]

    drifted = [n for n in preexisting if cur_lit[n] != old_lit[n]]
    if not drifted:
        return "unchanged", f"{len(preexisting)} pre-existing node(s) already at their committed position"

    if check_only:
        return "would-change", (f"{len(drifted)} pre-existing node(s) moved away from HEAD; "
                                f"{len(added)} node(s) added since HEAD")

    new_lit = dict(cur_lit)
    for n in preexisting:
        new_lit[n] = old_lit[n]

    detail_added = ""
    if added:
        restored_num = {n: (float(old_num[n][0]), float(old_num[n][1]))
                        for n in preexisting if n in old_num}
        newpos = place_new_nodes(cur, restored_num, added)
        for n, (x, y) in newpos.items():
            new_lit[n] = (str(x), str(y))
        detail_added = f"; {len(added)} added node(s) placed in the original coordinate space"

    try:
        out_raw = rewrite_positions(cur_raw, cur, new_lit)
    except RestoreError as e:
        return "error", str(e)

    # ── proofs, before anything is written ──
    try:
        out_doc = json.loads(out_raw)
    except ValueError as e:
        return "error", f"internal: rewrite produced invalid JSON ({e}) — NOT writing"
    if structural_fingerprint(out_doc) != structural_fingerprint(cur):
        return "error", "internal: rewrite changed something other than position — NOT writing"
    if len(out_doc.get("nodes") or []) != len(cur.get("nodes") or []):
        return "error", "internal: node count changed — NOT writing"
    if json.dumps(out_doc.get("connections"), sort_keys=True) != json.dumps(cur.get("connections"), sort_keys=True):
        return "error", "internal: connections changed — NOT writing"
    out_lit = position_literals(out_raw, out_doc)
    mismatched = [n for n in preexisting if out_lit[n] != old_lit[n]]
    if mismatched:
        return "error", f"internal: {len(mismatched)} node(s) not byte-identical to HEAD — NOT writing"

    path.write_text(out_raw, encoding="utf-8")
    return "restored", f"{len(drifted)} pre-existing node(s) restored to HEAD{detail_added}"


def collect(args: list[str], exclude: list[str]) -> list[pathlib.Path]:
    if args:
        paths = [pathlib.Path(a) for a in args]
    else:
        paths = []
        for pat in BLUEPRINT_GLOBS:
            paths.extend(sorted(REPO.glob(pat)))
    if exclude:
        paths = [p for p in paths if not any(fnmatch.fnmatch(p.name, e) for e in exclude)]
    return paths


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report only; exit 1 if any pre-existing node has drifted from HEAD")
    ap.add_argument("--exclude", action="append", default=[],
                    help="skip files whose basename matches this glob (repeatable)")
    ap.add_argument("files", nargs="*")
    a = ap.parse_args()

    counts = defaultdict(int)
    for path in collect(a.files, a.exclude):
        try:
            rel = path.resolve().relative_to(REPO).as_posix()
        except ValueError:
            rel = str(path)
        status, detail = process(path, a.check)
        counts[status] += 1
        if status in ("restored", "would-change"):
            print(f"  {'RESTORED ' if status == 'restored' else 'DRIFTED  '} {rel}  ({detail})")
        elif status == "error":
            print(f"  ERROR     {rel}: {detail}")
        elif status == "skip":
            print(f"  skip      {rel}: {detail}")

    print()
    print(f"n8n-position-restore: {counts['restored']} restored, {counts['would-change']} drifted, "
          f"{counts['unchanged']} already at HEAD, {counts['skip']} skipped, {counts['error']} error(s)")
    if a.check:
        return 1 if (counts["would-change"] or counts["error"]) else 0
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
