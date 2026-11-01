#!/usr/bin/env python3
"""n8n-layout — OPT-IN, SINGLE-FILE canvas layout helper. NOT a repo-wide pass. NOT a gate.

    python3 scripts/refactor/n8n-layout.py path/to/one.json --force   # lay out ONE named file
    python3 scripts/refactor/n8n-layout.py path/to/one.json           # dry run (default)
    python3 scripts/refactor/n8n-layout.py --self-test                # prove the invariants hold

*** READ THIS BEFORE RUNNING IT ON ANYTHING. ***

THIS TOOL CHANGES EXECUTION SEMANTICS. It was originally run repo-wide, twice, and rewrote
`nodes[].position` in **80 committed workflow blueprints**. In n8n those coordinates are not
decoration: under `settings.executionOrder: "v1"` — which every workflow here sets — the canvas
position of a fan-out's targets IS the order they execute in (top-most first; on an exact y tie,
left-most first — verified against n8n 2.17.0's own `workflow-execute.js`, see
`scripts/refactor/n8n-loop-order-lint.py` for the quoted comparator). Measured consequence of that
repo-wide run: loop-order violations went from **3 (pre-existing) to 55**, because a `splitInBatches`
loop lane and the edge that re-enters the loop landed on the same row, and the x tiebreak then put
the loop re-entry first — draining every batch before doing the per-batch work, while the workflow
still reported success. Reverted by `scripts/refactor/n8n-position-restore.py`.

THE OWNER'S STANDING RULE: **committed positions are preserved, not re-derived.** They are presumed
correct — they encode intent this tool cannot see. Tidying a canvas is a deliberate, per-workflow act
by a human looking at that workflow, never an automated sweep.

IF YOU WANT N8N'S OWN LOOK, USE N8N'S OWN BUTTON. The owner prefers it, and it is one click in the
editor ("Tidy up"). For the record, n8n 2.17.0's Tidy up is **dagre** (`@dagrejs/dagre` 1.1.4) — NOT
elkjs — invoked as `setGraph({ rankdir: 'LR', edgesep: 96, nodesep: 96, ranksep: 128 })` with dagre's
default `network-simplex` ranker and its default greedy acyclicer; n8n pre-sorts nodes top-to-bottom
then left-to-right before feeding the graph in, and does not special-case `splitInBatches`. That last
detail matters: **n8n's own Tidy up does not protect the loop-order invariant either**, so a workflow
tidied with the button still has to be checked by G45 afterwards.

GUARD RAILS NOW ENFORCED HERE (added after the incident above):
  - no glob mode — file paths are required, so a sweep cannot happen by typing one command;
  - `--force` is required to write anything; the default is a dry run;
  - a file is REFUSED, unwritten, if the computed layout would introduce any loop-order violation
    that the file does not already have (checked with the same code G45 runs).

WHAT THE ALGORITHM AIMS FOR: **never overlap, always the same output for the same graph, and read
left-to-right in execution order.** It does not, and cannot, know why a human put a node where they
did — which is exactly why it is no longer allowed to run unattended.

THE ALGORITHM (Sugiyama-style layered graph drawing, restricted to what n8n workflows need):

  1. Split nodes into three groups:
       - FLOW nodes: normal nodes connected via `main` connections.
       - ATTACHMENT nodes: nodes with zero `main` connections but at least one non-`main` connection
         (`ai_tool`, `ai_languageModel`, `ai_memory`, ...) — these are AI Agent sub-nodes (tools /
         models / memory) that n8n itself always renders clipped to their parent, not as a normal
         left-to-right hop. They get positioned directly under their parent instead of getting their
         own depth column.
       - STICKY notes (`n8n-nodes-base.stickyNote`) — free-floating annotations. Never participate in
         the flow graph; placed in a row below everything else so they cannot intersect it.

  2. FLOW nodes: depth = longest path (in hops) from a trigger, ignoring loop-back edges.
     `x = depth * H_SPACING`. Loop-backs (`splitInBatches` "done batches, go around again" edges,
     e.g. `syncV3Main0001`'s `Units Loop`) are found the standard way — a DFS from every trigger
     (sorted, so the choice of first trigger is deterministic for multi-trigger workflows like
     `mailLabelEngine01`) that classifies an edge back to a node already on the current DFS stack as
     a back-edge. Back-edges are excluded from the depth computation (so the loop body doesn't drag
     depth to infinity) but are still real connections — n8n draws them as the returning curve, this
     tool does not need to draw anything, only to not let them corrupt the column assignment.
     Any node with an in-degree of zero (across ALL edges, not just forward ones — a node inside a
     cycle always has an incoming edge from within the cycle, so it never qualifies) is a root: this
     is what makes multi-trigger workflows fan out from separate depth-0 rows instead of one.

  3. Sibling order within a depth column comes from DFS preorder (root order = sorted by name; a
     node's children are visited in `(output index, target name)` order, so an `if`/`switch` node's
     TRUE branch sorts above FALSE, and node A's fan-out is always in the same relative order). Two
     nodes in the same column get `y = rank * V_SPACING` where `rank` is their position in that
     column once sorted by DFS-preorder index. This is what keeps `errorHandler01`'s 3-way trigger
     fan-out (Telegram / GlitchTip reporter / lock-map lookup) in stable, distinct lanes.

  4. ATTACHMENT nodes are placed directly below the bottom-most FLOW node in their parent's depth
     column (not just below the parent — below everything already in that column, so an attachment
     can never land on top of a sibling flow node), stacked if a node has more than one attachment,
     ordered by `(connection type, source name)`.

  5. Everything is grid-snapped to 20 units — `H_SPACING` (280) and `V_SPACING` (160) are both
     multiples of 20 already, so this falls out of the arithmetic; it is enforced explicitly at the
     end regardless, in case a sticky note's declared width is not a multiple of 20.

WHY THIS CANNOT OVERLAP (the hard requirement — n8n's own tidy-up fails it, see errorHandler01
above). Node footprint is assumed to be at most FOOTPRINT_W x FOOTPRINT_H (200x100 — generous for a
default n8n node, which renders at roughly 100x100 plus its label). Two FLOW/ATTACHMENT nodes can
only share an x-coordinate if they are in the same depth column, and within a column every node gets
a distinct integer rank so their y-coordinates differ by at least V_SPACING (160 > FOOTPRINT_H).
Two nodes in different columns have x-coordinates that differ by at least H_SPACING (280 >
FOOTPRINT_W), which alone rules out any overlap regardless of y. Sticky notes are placed in a single
row below `max(y)` of everything else plus a margin, so they cannot intersect the flow; within that
row they are placed left-to-right using each note's own declared footprint, so they cannot intersect
each other either. This is a structural guarantee, not a search-and-fix — there is no collision
resolution step because the assignment scheme cannot produce a collision.

IDEMPOTENCE. The algorithm's only inputs are node identity (name, id, type, declared width/height)
and the connection graph — never the CURRENT position. Re-running on a file this tool already laid
out recomputes the identical graph and therefore the identical positions. Verified in `--self-test`.

SURGICAL WRITES. Only the two numbers inside each node's `"position": [x, y]` are rewritten in the
file's raw text — every other byte (key order, spacing, `parameters`, `connections`, credentials,
`notes`, ...) is left untouched. This is done by locating each `"position": [...]` occurrence in
raw-text order (which matches `nodes[]` array order 1:1 — asserted per-file before writing) and
replacing only the two numeric literals inside it, not by re-serializing the JSON.

WHAT THIS TOOL DELIBERATELY DOES NOT DO. It does not change `active`, does not touch `connections`,
`parameters`, `settings`, `credentials`, `notes`, sticky note *content*, or node identity in any way.
A file whose node names are not unique cannot be laid out safely (connections address nodes by name,
so an ambiguous name means an ambiguous graph) — such a file is skipped with a clear reason, never
silently mis-laid-out.
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import re
import sys
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.setrecursionlimit(10000)

REPO = pathlib.Path(__file__).resolve().parents[2]
BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.json",)

STICKY_TYPE = "n8n-nodes-base.stickyNote"

GRID = 20
FOOTPRINT_W, FOOTPRINT_H = 200, 100     # assumed default-node render box (generous)
H_SPACING, V_SPACING = 280, 160          # both > footprint, both multiples of GRID — see module docstring
STICKY_DEFAULT_W, STICKY_DEFAULT_H = 240, 160
STICKY_GAP = 80
ORPHAN_GAP = V_SPACING


def snap(v: float) -> int:
    return int(round(v / GRID) * GRID)


class LayoutError(Exception):
    """Raised for a graph shape this tool refuses to lay out (see module docstring)."""


def _iter_connection_edges(connections: dict, node_by_name: dict):
    """Yield (source, conn_type, out_idx, target) for every edge in `connections` whose endpoints
    both exist in `node_by_name`. Silently skips dangling connection endpoints — a separate gate
    (G38, dangling-workflow-ref-lint) polices workflow-id references; this tool only lays out nodes
    that actually exist."""
    for src, conns_by_type in (connections or {}).items():
        if src not in node_by_name:
            continue
        for ctype, outputs in (conns_by_type or {}).items():
            for out_idx, out_list in enumerate(outputs or []):
                for edge in (out_list or []):
                    tgt = edge.get("node")
                    if tgt in node_by_name:
                        yield src, ctype, out_idx, tgt


def compute_layout(doc: dict) -> tuple[dict[str, tuple[int, int]], list[str]]:
    """Compute {node_name: (x, y)} for every node in `doc`, plus a list of human-readable notes
    (loop-backs found, attachments resolved, anything unusual). Raises LayoutError if the graph
    shape makes a safe layout impossible (duplicate node names)."""
    nodes = doc.get("nodes", []) or []
    names = [n.get("name") for n in nodes]
    if len(names) != len(set(names)):
        dups = sorted({n for n in names if names.count(n) > 1})
        raise LayoutError(f"duplicate node name(s) {dups!r} — connections address nodes by name, "
                           f"a duplicate makes the graph ambiguous; refusing to lay out")

    node_by_name = {n["name"]: n for n in nodes}
    connections = doc.get("connections") or {}
    notes: list[str] = []

    sticky_names = {n["name"] for n in nodes if n.get("type") == STICKY_TYPE}
    flow_names = [nm for nm in names if nm not in sticky_names]

    # ── classify attachment nodes (AI sub-nodes: tool/model/memory/... feeding an Agent node) ──
    has_main_edge: set[str] = set()
    attach_edges: list[tuple[str, str, str, int]] = []  # (src, ctype, tgt, out_idx)
    all_main_edges: list[tuple[str, int, str]] = []      # (src, out_idx, tgt)
    for src, ctype, out_idx, tgt in _iter_connection_edges(connections, node_by_name):
        if ctype == "main":
            has_main_edge.add(src)
            has_main_edge.add(tgt)
            all_main_edges.append((src, out_idx, tgt))
        else:
            attach_edges.append((src, ctype, tgt, out_idx))

    attachment_names = {src for (src, _ctype, _tgt, _idx) in attach_edges
                         if src not in has_main_edge and src not in sticky_names}

    main_node_names = [nm for nm in flow_names if nm not in attachment_names]
    main_set = set(main_node_names)

    # ── main graph: children (sorted for deterministic DFS), in-degree over ALL edges ──
    children_raw: dict[str, list[tuple[int, str]]] = defaultdict(list)
    indeg_all: dict[str, int] = {nm: 0 for nm in main_node_names}
    for src, out_idx, tgt in all_main_edges:
        if src in main_set and tgt in main_set:
            children_raw[src].append((out_idx, tgt))
            indeg_all[tgt] += 1
    children_sorted = {src: sorted(lst, key=lambda p: (p[0], p[1])) for src, lst in children_raw.items()}

    # ── DFS from sorted roots (in-degree 0), classify back-edges, record preorder ──
    visited: set[str] = set()
    on_stack: set[str] = set()
    preorder: list[str] = []
    forward_edges: list[tuple[str, str]] = []
    back_edges: list[tuple[str, str]] = []

    def dfs(u: str) -> None:
        visited.add(u)
        on_stack.add(u)
        preorder.append(u)
        for _out_idx, v in children_sorted.get(u, []):
            if v in on_stack:
                back_edges.append((u, v))
                continue
            forward_edges.append((u, v))
            if v not in visited:
                dfs(v)
        on_stack.discard(u)

    roots = sorted(nm for nm in main_node_names if indeg_all.get(nm, 0) == 0)
    for r in roots:
        if r not in visited:
            dfs(r)
    # fallback: pure-cycle islands with no external entry point (pathological, but handled)
    stray_roots = sorted(nm for nm in main_node_names if nm not in visited)
    for r in stray_roots:
        dfs(r)
    if stray_roots:
        notes.append(f"{len(stray_roots)} node(s) reachable only via a cycle with no external "
                      f"trigger feeding it — synthetic root(s) used: {stray_roots}")
    if back_edges:
        notes.append(f"{len(back_edges)} loop-back edge(s) found (e.g. splitInBatches returning): "
                      + ", ".join(f"{u} -> {v}" for u, v in back_edges))

    # ── depth = longest forward path from any root (memoized; forward graph is acyclic) ──
    fwd_parents: dict[str, list[str]] = defaultdict(list)
    for u, v in forward_edges:
        fwd_parents[v].append(u)

    depth_memo: dict[str, int] = {}

    def depth_of(u: str) -> int:
        if u in depth_memo:
            return depth_memo[u]
        depth_memo[u] = 0  # guard (forward graph is acyclic, so this never actually recurses back to u)
        d = 0
        for p in fwd_parents.get(u, []):
            d = max(d, depth_of(p) + 1)
        depth_memo[u] = d
        return d

    for nm in main_node_names:
        depth_of(nm)

    # ── lane = rank by DFS-preorder index within each depth column ──
    preorder_rank = {nm: i for i, nm in enumerate(preorder)}
    by_depth: dict[int, list[str]] = defaultdict(list)
    for nm in main_node_names:
        by_depth[depth_memo[nm]].append(nm)

    placed: dict[str, tuple[int, int]] = {}
    column_max_y: dict[int, int] = {}
    for d, members in by_depth.items():
        members.sort(key=lambda nm: preorder_rank.get(nm, 1 << 30))
        x = d * H_SPACING
        for lane, nm in enumerate(members):
            y = lane * V_SPACING
            placed[nm] = (x, y)
        column_max_y[x] = (len(members) - 1) * V_SPACING if members else 0

    # ── attachments: stack below the bottom of their parent's column ──
    attach_children: dict[str, list[tuple[str, str]]] = defaultdict(list)  # target -> [(ctype, src)]
    for src, ctype, tgt, _idx in attach_edges:
        if src in attachment_names:
            attach_children[tgt].append((ctype, src))

    remaining = dict(attach_children)
    unresolved = set(attachment_names)
    progress = True
    while remaining and progress:
        progress = False
        for tgt in sorted(remaining.keys()):
            if tgt not in placed:
                continue
            siblings = sorted(remaining.pop(tgt), key=lambda cs: (cs[0], cs[1]))
            tx, _ty = placed[tgt]
            top = column_max_y.get(tx, 0)
            for i, (_ctype, src) in enumerate(siblings):
                ny = top + V_SPACING * (i + 1)
                placed[src] = (tx, ny)
                unresolved.discard(src)
            column_max_y[tx] = top + V_SPACING * len(siblings)
            progress = True

    if unresolved:
        notes.append(f"{len(unresolved)} AI sub-node(s) whose target is never reached — "
                      f"placed as orphans: {sorted(unresolved)}")

    # bottom edge, not bare y — a row placed `GAP` below the max raw y can still overlap a taller
    # node's footprint if GAP < that node's height. Flow/attachment nodes all use FOOTPRINT_H.
    overall_max_bottom = max((y + FOOTPRINT_H for _x, y in placed.values()), default=0)

    # ── orphan attachments (dangling target / unresolved chain) — a row of their own ──
    if unresolved:
        ox = 0
        oy = overall_max_bottom + ORPHAN_GAP
        for nm in sorted(unresolved):
            placed[nm] = (ox, oy)
            ox += FOOTPRINT_W + 40
        overall_max_bottom = max(overall_max_bottom, oy + FOOTPRINT_H)

    # ── sticky notes: one row below everything, left-to-right, own footprint, name/id order ──
    if sticky_names:
        def sticky_size(nm: str) -> tuple[int, int]:
            params = node_by_name[nm].get("parameters") or {}
            w = params.get("width") or STICKY_DEFAULT_W
            h = params.get("height") or STICKY_DEFAULT_H
            try:
                return int(w), int(h)
            except (TypeError, ValueError):
                return STICKY_DEFAULT_W, STICKY_DEFAULT_H

        ordered_stickies = sorted(sticky_names, key=lambda nm: (nm, node_by_name[nm].get("id", "")))
        sx = 0
        sy = overall_max_bottom + STICKY_GAP if placed else 0
        for nm in ordered_stickies:
            w, _h = sticky_size(nm)
            placed[nm] = (sx, sy)
            sx += w + 40

    # ── grid snap everything ──
    placed = {nm: (snap(x), snap(y)) for nm, (x, y) in placed.items()}

    missing = [nm for nm in names if nm not in placed]
    if missing:
        # should be unreachable given the construction above, but fail loudly rather than silently
        # dropping a node's position if it ever happens
        raise LayoutError(f"internal: {len(missing)} node(s) got no computed position: {missing}")

    return placed, notes


# ─────────────────────────────────────────────────────────────────────────────
_POSITION_RE = re.compile(
    r'"position"\s*:\s*\[\s*(-?[0-9]+(?:\.[0-9]+)?)\s*,\s*(-?[0-9]+(?:\.[0-9]+)?)\s*\]'
)


def apply_layout_text(raw_text: str, doc: dict, placed: dict[str, tuple[int, int]]) -> str:
    """Rewrite ONLY the numeric literals inside each node's `"position": [x, y]` in `raw_text`,
    in node-array order. Every other byte is untouched. Raises LayoutError if the number of
    `"position":` occurrences in the text doesn't match the number of nodes (would make the
    order-based mapping unsafe) — callers should fall back to reporting the file as un-layoutable
    rather than guessing."""
    nodes = doc.get("nodes", []) or []
    matches = list(_POSITION_RE.finditer(raw_text))
    if len(matches) != len(nodes):
        raise LayoutError(f"{len(matches)} \"position\" occurrence(s) in the raw text but "
                           f"{len(nodes)} node(s) in the parsed JSON — refusing a surgical rewrite")

    out = []
    cursor = 0
    for node, m in zip(nodes, matches):
        name = node["name"]
        x, y = placed[name]
        out.append(raw_text[cursor:m.start(1)])
        out.append(str(x))
        out.append(raw_text[m.end(1):m.start(2)])
        out.append(str(y))
        cursor = m.end(2)
    out.append(raw_text[cursor:])
    return "".join(out)


def current_positions(doc: dict) -> dict[str, tuple[int, int]]:
    return {n["name"]: (n["position"][0], n["position"][1]) for n in (doc.get("nodes") or [])
            if "position" in n and "name" in n}


def node_footprint(node: dict) -> tuple[int, int]:
    if node.get("type") == STICKY_TYPE:
        params = node.get("parameters") or {}
        try:
            return int(params.get("width") or STICKY_DEFAULT_W), int(params.get("height") or STICKY_DEFAULT_H)
        except (TypeError, ValueError):
            return STICKY_DEFAULT_W, STICKY_DEFAULT_H
    return FOOTPRINT_W, FOOTPRINT_H


def find_overlaps(doc: dict) -> list[tuple[str, str]]:
    """Return [(nameA, nameB), ...] for every pair of nodes whose footprint rectangles (using
    CURRENT `position`) overlap in both axes."""
    nodes = [n for n in (doc.get("nodes") or []) if "position" in n and "name" in n]
    boxes = []
    for n in nodes:
        x, y = n["position"][0], n["position"][1]
        w, h = node_footprint(n)
        boxes.append((n["name"], x, x + w, y, y + h))
    out = []
    for i in range(len(boxes)):
        na, xa0, xa1, ya0, ya1 = boxes[i]
        for j in range(i + 1, len(boxes)):
            nb, xb0, xb1, yb0, yb1 = boxes[j]
            if xa0 < xb1 and xb0 < xa1 and ya0 < yb1 and yb0 < ya1:
                out.append((na, nb))
    return out


# ─────────────────────────────────────────────────────────────────────────────
def structural_fingerprint(doc: dict) -> dict:
    """Everything about a workflow EXCEPT node position — used to prove a layout pass changed
    nothing else. Node dicts are copied with `position` stripped; order-independent for `nodes`
    (compared as a dict keyed by node id) so nothing depends on array order, only content."""
    nodes = {}
    for n in doc.get("nodes", []) or []:
        n2 = dict(n)
        n2.pop("position", None)
        nodes[n2.get("id", n2.get("name"))] = n2
    rest = {k: v for k, v in doc.items() if k != "nodes"}
    return {"nodes": nodes, "rest": rest}


def collect_files(args: list[str]) -> list[pathlib.Path]:
    """Named files only. There is deliberately NO glob/sweep mode — see the module docstring; a
    repo-wide run of this tool is what rewrote 80 committed workflows and inverted execution order
    in 6 of them."""
    return [pathlib.Path(a) for a in args]


def _g45():
    """G45's own module, so this tool and the gate can never disagree about the rule."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "n8n_loop_order_lint", str(pathlib.Path(__file__).parent / "n8n-loop-order-lint.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def fanout_execution_orders(doc: dict) -> dict[str, list[str]]:
    """{source node: targets in the order n8n v1 would execute them} for every fan-out.

    This is the property that must survive a re-layout. Comparing violation COUNTS is not enough:
    a layout can keep the count identical while reordering a different fan-out, which is exactly how
    a "safe-looking" run still changes behaviour."""
    g45 = _g45()
    nodes = {n["name"]: n for n in (doc.get("nodes") or []) if "name" in n}
    out: dict[str, list[str]] = {}
    for src, edges in g45._main_adjacency(doc).items():
        seen, uniq = set(), []
        for _oi, t in edges:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        if len(uniq) >= 2:
            out[src] = sorted(uniq, key=lambda t: g45.execution_rank(
                (nodes.get(t) or {}).get("position") or [0, 0]))
    return out


def process_file(path: pathlib.Path, check_only: bool) -> tuple[str, str]:
    """Returns (status, detail). status in {"unchanged", "changed", "would-change", "error"}."""
    try:
        raw = path.read_text(encoding="utf-8")
        doc = json.loads(raw)
    except (OSError, ValueError) as e:
        return "error", f"cannot read/parse: {e}"

    try:
        placed, notes = compute_layout(doc)
    except LayoutError as e:
        return "error", str(e)

    cur = current_positions(doc)
    if all(cur.get(nm) == placed[nm] for nm in placed) and set(cur) == set(placed):
        return "unchanged", "; ".join(notes)

    # NOTE: the safety checks below run in --check mode too. They used to sit after an early
    # `if check_only: return "would-change"`, so `--check` happily reported a file as merely STALE
    # when `--force` would in fact REFUSE it — the dry run disagreed with the real run about the
    # one thing the dry run exists to tell you.
    fp_before = structural_fingerprint(doc)
    try:
        new_raw = apply_layout_text(raw, doc, placed)
    except LayoutError as e:
        return "error", str(e)
    new_doc = json.loads(new_raw)
    fp_after = structural_fingerprint(new_doc)
    if fp_before != fp_after:
        return "error", "internal: structural fingerprint changed by the rewrite — NOT writing " \
                         "(this should be impossible; the rewrite only touches position numerals)"
    overlaps = find_overlaps(new_doc)
    if overlaps:
        return "error", f"internal: computed layout still has {len(overlaps)} overlapping pair(s): " \
                         f"{overlaps[:5]} — NOT writing"

    # ── the hard constraint: a tidy canvas may never change execution order ──
    # Not "no NEW violations" (a count can stay level while a different fan-out flips) — the
    # invariant is that EVERY fan-out executes its targets in exactly the order it does today.
    before_orders = fanout_execution_orders(doc)
    after_orders = fanout_execution_orders(new_doc)
    flipped = [src for src, order in before_orders.items()
               if after_orders.get(src) != order]
    if flipped:
        src = flipped[0]
        return "error", (
            f"REFUSED — this layout would change the EXECUTION ORDER of {len(flipped)} fan-out(s). "
            f"Under executionOrder v1 the top-most target runs first, so moving nodes reorders the "
            f"branches (see G45, n8n-loop-order-lint.py). First: node {src!r} runs "
            f"{before_orders[src]} today, would run {after_orders.get(src)}. "
            f"NOT writing — committed positions are preserved, not re-derived.")

    if check_only:
        return "would-change", "; ".join(notes)

    path.write_text(new_raw, encoding="utf-8")
    return "changed", "; ".join(notes)


# ─────────────────────────────────────────────────────────────────────────────
def _mk(name, ntype, position, **extra):
    n = {"name": name, "type": ntype, "position": list(position), "id": name, "parameters": {}}
    n.update(extra)
    return n


def _wire(*pairs):
    """pairs: (src, tgt) or (src, out_idx, tgt) -> connections dict, all 'main'."""
    conns: dict = defaultdict(lambda: {"main": []})
    for p in pairs:
        src, out_idx, tgt = (p[0], 0, p[1]) if len(p) == 2 else p
        c = conns[src]["main"]
        while len(c) <= out_idx:
            c.append([])
        c[out_idx].append({"node": tgt, "type": "main", "index": 0})
    return {k: dict(v) for k, v in conns.items()}


def self_test() -> int:
    bad = 0

    def check(label: str, cond: bool) -> None:
        nonlocal bad
        bad += 0 if cond else 1
        print(f"  [{'ok ' if cond else 'FAIL'}] {label}")

    # 1) simple linear chain -> strictly increasing x, same y
    doc = {"nodes": [_mk("A", "n8n-nodes-base.manualTrigger", (999, 999)),
                      _mk("B", "n8n-nodes-base.noOp", (5, 5)),
                      _mk("C", "n8n-nodes-base.noOp", (5, 5))],
           "connections": _wire(("A", "B"), ("B", "C"))}
    placed, _ = compute_layout(doc)
    check("linear chain: x strictly increases A<B<C",
          placed["A"][0] < placed["B"][0] < placed["C"][0])
    check("linear chain: same lane (y) throughout",
          placed["A"][1] == placed["B"][1] == placed["C"][1])

    # 2) branch fan-out gets distinct lanes, no overlap
    doc = {"nodes": [_mk("Trig", "n8n-nodes-base.manualTrigger", (0, 0)),
                      _mk("Left", "n8n-nodes-base.noOp", (0, 0)),
                      _mk("Mid", "n8n-nodes-base.noOp", (0, 0)),
                      _mk("Right", "n8n-nodes-base.noOp", (0, 0))],
           "connections": _wire(("Trig", "Left"), ("Trig", "Mid"), ("Trig", "Right"))}
    placed, _ = compute_layout(doc)
    ys = {placed["Left"][1], placed["Mid"][1], placed["Right"][1]}
    check("3-way fan-out (errorHandler01 shape): 3 distinct lanes", len(ys) == 3)
    doc["nodes"] = [dict(n, position=list(placed[n["name"]])) for n in doc["nodes"]]
    check("3-way fan-out: laid-out result has zero overlaps", find_overlaps(doc) == [])

    # 3) loop-back (splitInBatches pattern) does not blow up / does not create a cycle in depth
    doc = {"nodes": [_mk("Trig", "n8n-nodes-base.manualTrigger", (0, 0)),
                      _mk("Split", "n8n-nodes-base.splitInBatches", (0, 0)),
                      _mk("Done", "n8n-nodes-base.noOp", (0, 0)),
                      _mk("Process", "n8n-nodes-base.noOp", (0, 0)),
                      _mk("CheckMore", "n8n-nodes-base.if", (0, 0))],
           "connections": _wire(("Trig", "Split"), ("Split", 0, "Done"), ("Split", 1, "Process"),
                                 ("Process", "CheckMore"), ("CheckMore", 0, "Split"))}
    placed, notes = compute_layout(doc)
    check("loop-back found and reported", any("loop-back" in n for n in notes))
    check("loop-back: Split keeps a finite, sane depth (not dragged forward by its own loop body)",
          placed["Split"][0] < placed["Process"][0] < placed["CheckMore"][0])
    doc["nodes"] = [dict(n, position=list(placed[n["name"]])) for n in doc["nodes"]]
    check("loop-back layout has zero overlaps", find_overlaps(doc) == [])

    # 4) multi-trigger workflow (mailLabelEngine01 shape): each root gets its own lane at depth 0
    doc = {"nodes": [_mk("T1", "n8n-nodes-base.webhook", (0, 0)),
                      _mk("T2", "n8n-nodes-base.scheduleTrigger", (0, 0)),
                      _mk("T3", "n8n-nodes-base.manualTrigger", (0, 0)),
                      _mk("Shared", "n8n-nodes-base.noOp", (0, 0))],
           "connections": _wire(("T1", "Shared"), ("T2", "Shared"), ("T3", "Shared"))}
    placed, _ = compute_layout(doc)
    check("multi-trigger: all 3 triggers at depth 0 (x=0)",
          placed["T1"][0] == placed["T2"][0] == placed["T3"][0] == 0)
    check("multi-trigger: 3 distinct lanes for the 3 triggers",
          len({placed["T1"][1], placed["T2"][1], placed["T3"][1]}) == 3)

    # 5) sticky notes never disturb the flow / never overlap it or each other
    doc = {"nodes": [_mk("A", "n8n-nodes-base.manualTrigger", (500, 500)),
                      _mk("B", "n8n-nodes-base.noOp", (500, 500)),
                      _mk("N1", STICKY_TYPE, (10, 10), parameters={"width": 300, "height": 200}),
                      _mk("N2", STICKY_TYPE, (10, 10), parameters={"width": 300, "height": 200})],
           "connections": _wire(("A", "B"))}
    placed, _ = compute_layout(doc)
    check("sticky notes placed below the flow's max y",
          placed["N1"][1] > max(placed["A"][1], placed["B"][1]) and
          placed["N2"][1] > max(placed["A"][1], placed["B"][1]))
    doc["nodes"] = [dict(n, position=list(placed[n["name"]])) for n in doc["nodes"]]
    check("sticky notes: zero overlaps with flow or each other", find_overlaps(doc) == [])

    # 6) AI attachment (ai_tool/ai_languageModel): tool node placed under its Agent, own column
    doc = {"nodes": [_mk("Trig", "n8n-nodes-base.manualTrigger", (0, 0)),
                      _mk("Agent", "n8n-nodes-base.agent", (0, 0)),
                      _mk("Tool1", "n8n-nodes-base.toolWorkflow", (0, 0)),
                      _mk("Model1", "n8n-nodes-base.lmChatOpenAi", (0, 0))],
           "connections": dict(_wire(("Trig", "Agent")),
                                **{"Tool1": {"ai_tool": [[{"node": "Agent", "type": "ai_tool", "index": 0}]]},
                                   "Model1": {"ai_languageModel": [[{"node": "Agent", "type": "ai_languageModel", "index": 0}]]}})}
    placed, _ = compute_layout(doc)
    check("AI attachment: tool node shares Agent's x column",
          placed["Tool1"][0] == placed["Agent"][0])
    check("AI attachment: tool node sits below Agent",
          placed["Tool1"][1] > placed["Agent"][1])
    check("AI attachment: two attachments get distinct lanes",
          placed["Tool1"][1] != placed["Model1"][1])
    doc["nodes"] = [dict(n, position=list(placed[n["name"]])) for n in doc["nodes"]]
    check("AI attachment layout has zero overlaps", find_overlaps(doc) == [])

    # 7) idempotence: re-running compute_layout on its own output changes nothing
    doc = {"nodes": [_mk("Trig", "n8n-nodes-base.manualTrigger", (0, 0)),
                      _mk("A", "n8n-nodes-base.if", (0, 0)),
                      _mk("B", "n8n-nodes-base.noOp", (0, 0)),
                      _mk("C", "n8n-nodes-base.noOp", (0, 0)),
                      _mk("D", "n8n-nodes-base.noOp", (0, 0))],
           "connections": _wire(("Trig", "A"), ("A", 0, "B"), ("A", 1, "C"), ("B", "D"), ("C", "D"))}
    placed1, _ = compute_layout(doc)
    doc2 = {**doc, "nodes": [dict(n, position=list(placed1[n["name"]])) for n in doc["nodes"]]}
    placed2, _ = compute_layout(doc2)
    check("idempotent: second pass over first pass's output is a no-op", placed1 == placed2)

    # 8) duplicate node names refused, not silently mis-laid-out
    doc = {"nodes": [_mk("A", "n8n-nodes-base.manualTrigger", (0, 0)),
                      _mk("A", "n8n-nodes-base.noOp", (0, 0))],
           "connections": {}}
    try:
        compute_layout(doc)
        check("duplicate node names raise LayoutError", False)
    except LayoutError:
        check("duplicate node names raise LayoutError", True)

    # 9) surgical text rewrite touches ONLY the position numerals
    raw = ('{\n  "nodes": [\n    {\n      "name": "A",\n      "position": [\n        5,\n'
           '        7\n      ],\n      "notes": "keep <this> & that"\n    }\n  ]\n}\n')
    doc = json.loads(raw)
    new_raw = apply_layout_text(raw, doc, {"A": (100, 200)})
    check("surgical rewrite: position numerals updated",
          '"position": [\n        100,\n        200\n      ]' in new_raw)
    check("surgical rewrite: unrelated text untouched byte-for-byte",
          'keep <this> & that' in new_raw and new_raw.count("\n") == raw.count("\n"))

    print(f"\nn8n-layout self-test: {'ALL PASS' if bad == 0 else f'{bad} FAILING'}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Opt-in, single-file n8n canvas layout. Requires explicit file paths and "
                    "--force to write. Read the module docstring before using it.")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--check", action="store_true", help="report only; do not write; exit 1 if any file would change")
    ap.add_argument("--force", action="store_true",
                    help="actually write. Without it this is a dry run, because these coordinates "
                         "are execution semantics, not decoration.")
    ap.add_argument("files", nargs="*", help="workflow file(s) to lay out — REQUIRED, no sweep mode")
    a = ap.parse_args()

    if a.self_test:
        return self_test()

    if not a.files:
        print("n8n-layout: refusing to run without explicit file path(s).\n"
              "  This tool rewrites nodes[].position, which under executionOrder v1 IS the execution\n"
              "  order of every fan-out. A repo-wide run of it rewrote 80 committed workflows and\n"
              "  inverted the loop-order invariant in 6 of them (3 pre-existing violations -> 55).\n"
              "  Committed positions are preserved, not re-derived — see the module docstring.\n"
              "  For n8n's own look, use n8n's own 'Tidy up' button in the editor.\n"
              "  Audit the invariant: python3 scripts/refactor/n8n-loop-order-lint.py\n"
              "  Undo a bad sweep:    python3 scripts/refactor/n8n-position-restore.py", file=sys.stderr)
        return 2

    if not (a.force or a.check):
        print("n8n-layout: dry run (no --force) — nothing will be written.\n", file=sys.stderr)
        a.check = True

    files = collect_files(a.files)
    changed = would_change = unchanged = errors = 0
    for path in files:
        # `Path.relative_to` RAISES for a path outside the repo, so doing it unguarded first
        # crashed the tool on any file given by an absolute path elsewhere (e.g. a copy in a
        # scratch dir, which is exactly how you would safely trial a layout).
        try:
            rel = path.resolve().relative_to(REPO)
        except ValueError:
            rel = path
        status, detail = process_file(path, a.check)
        if status == "changed":
            changed += 1
            print(f"  LAID OUT   {rel}" + (f"  ({detail})" if detail else ""))
        elif status == "would-change":
            would_change += 1
            print(f"  STALE      {rel}" + (f"  ({detail})" if detail else ""))
        elif status == "unchanged":
            unchanged += 1
        else:
            errors += 1
            print(f"  SKIPPED    {rel}: {detail}")

    print()
    if a.check:
        print(f"n8n-layout --check: {would_change} stale, {unchanged} clean, {errors} skipped "
              f"(of {len(files)} file(s))")
        return 1 if (would_change or errors) else 0

    print(f"n8n-layout: {changed} laid out, {unchanged} already clean, {errors} skipped "
          f"(of {len(files)} file(s))")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
