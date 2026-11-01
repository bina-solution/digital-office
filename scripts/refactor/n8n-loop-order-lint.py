#!/usr/bin/env python3
"""n8n-loop-order-lint — gate G45: canvas height never drains a loop before its work runs.

    python3 scripts/refactor/n8n-loop-order-lint.py [--self-test] [--verbose]
    python3 scripts/refactor/n8n-loop-order-lint.py --rev HEAD     # audit the committed state instead

WHY THIS GATE EXISTS. In n8n, `nodes[].position` is not decoration — under
`settings.executionOrder: "v1"` (which every workflow in this repo sets) it IS the execution order
for a fan-out. This was verified against the running engine's own source, n8n **2.17.0**, in
`n8n-core/dist/execution-engine/workflow-execute.js`:

    for (outputIndex in ...main) {                  // EVERY output index, flattened into ONE list
        for (connectionData of ...main[outputIndex]) {
            nodesToAdd.push({ position: nodeToAdd?.position || [0,0], connection, outputIndex });
        }
    }
    nodesToAdd.sort((a, b) => {
        if (a.position[1] < b.position[1]) return  1;    // DESCENDING by y
        if (a.position[1] > b.position[1]) return -1;
        if (a.position[0] > b.position[0]) return -1;    // then DESCENDING by x
        return 0;
    });
    for (const nodeData of nodesToAdd) this.addNodeToBeExecuted(...);

and in `addNodeToBeExecuted`:

    const enqueueFn = workflow.settings.executionOrder === 'v1' ? 'unshift' : 'push';
    this.runExecutionData.executionData.nodeExecutionStack[enqueueFn]({...});

with the main loop doing `nodeExecutionStack.shift()`. The sort is DESCENDING and each element is
then `unshift`ed onto the FRONT of the stack, so the array is consumed back-to-front:

    ==> the TOP-MOST node (smallest y) runs FIRST; on an exact y tie, the LEFT-MOST (smallest x).

Two consequences that make this a correctness invariant rather than a style preference:

  1. **Position overrides output index.** `nodesToAdd` is accumulated across all output indices
     before the single sort, so a low-placed target on output 0 runs AFTER a high-placed target on
     output 1. You cannot reason about branch order from the wiring alone.
  2. **Execution is depth-first.** Each executed node `unshift`s its own children to the front too,
     so the first branch runs to completion before the second branch starts.

THE FAILURE THIS CATCHES. The `splitInBatches` ("Loop Over Items") batching idiom fans out to both
the work to do for this batch AND an edge that re-enters the loop node. If the re-entry edge is at or
above the work lane, n8n re-enters the loop node first, drains every batch, and only then runs the
work — a completely different execution profile from the intended one. **The workflow still reports
success**, which is why nothing else in this repo would ever notice; it is the same silent-failure
family as G7, G19, G38, G41 and G48.

WHAT COUNTS AS A FAILURE. Only targets that actually RACE are compared — that means two or more
distinct targets on the **same** `main` output index. Different output indices of an `if`/`switch`
are mutually exclusive, and the last output of a node with `onError: continueErrorOutput` is an
error sink, so comparing across output indices invents races that cannot happen. (That mistake is
what made this gate report `syncV3Deliver0001` for weeks: `Call DELIVER G` out0=success feeds the
normal loop return and out1=error feeds a failure sink, and the gate called the error sink a
starved "work lane".) A `splitInBatches` node's own out0 "done" / out1 "loop" pair likewise never
carries data at the same time, so it is never a race either.

Within one racing group, each target is ranked by how many hops it needs to get back to the
enclosing loop driver `L` (a `splitInBatches` node with `src == L`, or with a cycle through `src`).
Fewer hops = closer to re-entering the loop. The gate fails when a target that returns to `L` in
FEWER hops is scheduled BEFORE one that takes more hops or never returns at all — because then the
loop goes around again before the longer lane has run. This subsumes the obvious self-edge case
(`h == 0`) and also catches re-entry through an intermediate node, which a target-identity test
misses: `indoxGmailDocDownloader01`'s `Code` fan-out returns to its loop via `End Process Gmail
Document` (h=1) racing a terminal `Upsert Incoming Document` (h=None), and is correct today only
because of its y coordinates.

NOT CHECKED: workflows whose `settings.executionOrder` is not `v1` (position is not consulted there),
and fan-outs with no cycle at all (branch order may matter to a human but is not a loop-draining bug).

THE SECOND RULE — THE LANE DOES NOT LEAD BACK INTO THE LOOP. The owner, 2026-08-25, on a loop that
went around through its own upsert: «זה bad practice כי upsert לא בהכרח מחזיר אותה כמות אובייקטים
וזה יכול לשבור את הלולאה, לכן … הלולאה קוראת לנתיב ואז לעצמה, והנתיב לא מוביל חזרה ללולאה … ותוודא
שזה לא קורה שוב». A loop that is re-entered from the end of its lane goes around on whatever that
last node handed back: an upsert, a sub-workflow or an HTTP call may return fewer items than it was
given, or none — and then the loop stops early, silently, with batches unprocessed. So the only
edge from inside a loop's body back into the loop node is the loop's own self-edge (`check_returns`).
Four branches were rewired by hand that day and nothing checked the rest; this gate could not have
— it was reading no shipped blueprint (see BLUEPRINT_GLOBS). Independent of executionOrder.

FIXING A FAILURE IS A HAND EDIT. There is deliberately no auto-fixer. A previous version of this
gate enforced a *computed* layout (`n8n-layout.py`), which rewrote positions across 80 committed
workflows and inverted this very invariant — a tidy canvas that changes execution semantics is worse
than an untidy one. Committed positions are presumed correct; see
`scripts/refactor/n8n-position-restore.py`.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from collections import defaultdict, deque

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
# Blueprints are code (.workflow.ts) since 52b32aa4. n8n_blueprint is the ONE reader —
# see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402

# IT READ NO SHIPPED BLUEPRINT FOR SEVEN WEEKS. The first two globs named `*.json`; those
# directories have held only `.workflow.ts` since 2026-08-16. What was left was the third glob —
# 22 exported snapshots — so the gate said "all 22 blueprint workflow(s)" and passed, while the 97
# workflows that run held 64 loops nobody was looking at. Read through the one reader on
# 2026-10-07 they hold 29 findings of exactly the kind this gate was written for.
BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.workflow.ts",)
# Not a shipped blueprint tree, but it holds 36 splitInBatches nodes of its own; leaving it out
# meant "0 findings" there was never evidence of anything. These ARE json: exported snapshots.
SNAPSHOT_GLOBS = ("apps/indox/app/incoming_documents/context-collection/n8n-workflows/*.json",)

SPLIT_IN_BATCHES = "n8n-nodes-base.splitInBatches"


# ── the engine's own ordering, restated ─────────────────────────────────────
def execution_rank(position) -> tuple[float, float]:
    """Sort key such that ascending order == n8n v1 execution order (top-most first, then left-most).

    n8n sorts DESCENDING by (y, x) and then unshifts each onto the front of the execution stack,
    which consumes the array back-to-front — so the effective order is ascending (y, x)."""
    try:
        x, y = float(position[0]), float(position[1])
    except (TypeError, ValueError, IndexError):
        x = y = 0.0
    return (y, x)


def _main_adjacency(doc: dict):
    names = {n.get("name") for n in (doc.get("nodes") or [])}
    adj: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for src, by_type in (doc.get("connections") or {}).items():
        if src not in names:
            continue
        for out_idx, lst in enumerate(((by_type or {}).get("main")) or []):
            for c in (lst or []):
                tgt = (c or {}).get("node")
                if tgt in names:
                    adj[src].append((out_idx, tgt))
    return adj


def _reaches(adj, start: str, goal: str, limit: int = 5000) -> bool:
    seen, stack = set(), [start]
    while stack:
        cur = stack.pop()
        if cur == goal:
            return True
        if cur in seen or len(seen) > limit:
            continue
        seen.add(cur)
        stack.extend(t for _i, t in adj.get(cur, ()))
    return False


def _hops(adj, start: str, goal: str):
    """Fewest `main` hops from `start` to `goal`, or None if `goal` is unreachable.

    This is the "how soon does this lane put us back in the loop" measure. 0 means the target IS
    the loop driver (a self-edge or a direct edge back to it)."""
    if start == goal:
        return 0
    seen, queue = {start}, deque([(start, 0)])
    while queue:
        cur, d = queue.popleft()
        for _i, t in adj.get(cur, ()):
            if t == goal:
                return d + 1
            if t not in seen:
                seen.add(t)
                queue.append((t, d + 1))
    return None


def check_doc(doc: dict) -> list[str]:
    """Return a list of failure reasons for `doc` (empty = clean)."""
    if ((doc.get("settings") or {}).get("executionOrder")) != "v1":
        return []  # position is not consulted outside v1

    nodes = {n["name"]: n for n in (doc.get("nodes") or []) if "name" in n}
    adj = _main_adjacency(doc)
    drivers_all = [n for n, nd in nodes.items() if nd.get("type") == SPLIT_IN_BATCHES]
    problems: list[str] = []

    # Only targets on the SAME output index can be scheduled together — see module docstring.
    by_output: dict[tuple[str, int], list[str]] = defaultdict(list)
    for src, edges in adj.items():
        for out_idx, tgt in edges:
            if tgt not in by_output[(src, out_idx)]:
                by_output[(src, out_idx)].append(tgt)

    for (src, out_idx), targets in sorted(by_output.items()):
        if len(targets) < 2:
            continue
        # loop drivers this fan-out actually sits inside
        drivers = [L for L in drivers_all
                   if src == L or (_reaches(adj, L, src) and _reaches(adj, src, L))]
        if not drivers:
            continue

        def rank(t: str) -> tuple[float, float]:
            return execution_rank((nodes.get(t) or {}).get("position") or [0, 0])

        for L in drivers:
            # ascending rank == the order n8n v1 actually runs them
            ordered = sorted(targets, key=rank)
            dist = {t: _hops(adj, t, L) for t in targets}
            for i, early in enumerate(ordered):
                h_early = dist[early]
                if h_early is None:
                    continue  # this lane never returns to the loop; it cannot drain it
                starved = [t for t in ordered[i + 1:]
                           if dist[t] is None or dist[t] > h_early]
                if not starved:
                    continue
                epos = (nodes.get(early) or {}).get("position")
                detail = ", ".join(
                    f"{t!r} (position {(nodes.get(t) or {}).get('position')}, "
                    f"{'never returns to the loop' if dist[t] is None else f'{dist[t]} hop(s) back'})"
                    for t in starved)
                problems.append(
                    f"LOOP DRAINED BEFORE WORK — node {src!r} output {out_idx} fans out to "
                    f"{early!r} (position {epos}, {h_early} hop(s) back to loop driver {L!r}), which "
                    f"n8n schedules BEFORE the work lane(s): {detail}. Under executionOrder v1 the "
                    f"top-most target runs first (leftmost on a y tie), so the loop goes around "
                    f"again before that work runs — every batch is consumed first. "
                    f"Fix: give the work lane(s) a strictly smaller y than "
                    f"y={epos[1] if epos else '?'} (equal y is NOT safe — it falls to the x tiebreak).")
                break  # one report per (fan-out, driver) is enough

    return problems


def check_returns(doc: dict) -> list[str]:
    """The second rule: one reason per loop that is re-entered from inside its own body."""
    nodes = {n["name"]: n for n in (doc.get("nodes") or []) if "name" in n}
    adj = _main_adjacency(doc)
    problems: list[str] = []
    for L, nd in sorted(nodes.items()):
        if nd.get("type") != SPLIT_IN_BATCHES:
            continue
        try:                                          # v3: out0 done, out1 loop; before it, one output
            loop_out = 1 if float(nd.get("typeVersion")) >= 3 else 0
        except (TypeError, ValueError):               # no version written: go by the wiring
            loop_out = 1 if any(i >= 1 for i, _t in adj.get(L, ())) else 0
        seen, stack = set(), [t for i, t in adj.get(L, ()) if i == loop_out and t != L]
        while stack:                                  # the body: what the loop output reaches
            cur = stack.pop()                         # without going through the loop node
            if cur in seen or cur == L:
                continue
            seen.add(cur)
            stack.extend(t for _i, t in adj.get(cur, ()))
        back = sorted(x for x in seen if any(t == L for _i, t in adj.get(x, ())))
        if back:
            who = ", ".join(f"{x!r} ({str((nodes.get(x) or {}).get('type') or '?').split('.')[-1]})"
                            for x in back)
            problems.append(
                f"LANE LEADS BACK INTO THE LOOP — loop {L!r} is re-entered from {who} instead of "
                f"from itself. A node on the way back need not hand back what it was given (an "
                f"upsert, a sub-workflow, an HTTP call can return fewer items, or none), and then "
                f"the loop stops early or goes around on the wrong count. "
                f"Fix: wire the loop output to the lane AND to {L!r} itself, and let the lane end.")
    return problems


# ── file/rev plumbing ───────────────────────────────────────────────────────
def iter_docs(rev: str | None):
    """(rel, doc, error) for every shipped blueprint, then every snapshot. `--rev` audits the
    snapshots only: a blueprint is compiled from a directory on disk, not from `git show`."""
    for pattern in (() if rev else BLUEPRINT_GLOBS):
        for path in sorted(REPO.glob(pattern)):
            rel = path.relative_to(REPO).as_posix()
            try:
                yield rel, load_blueprint(str(path)), None
            except (OSError, ValueError, CompileError) as e:
                yield rel, None, f"cannot read: {e}"
    for pattern in SNAPSHOT_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            rel = path.relative_to(REPO).as_posix()
            if rev:
                p = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=REPO,
                                   capture_output=True, text=True)
                if p.returncode != 0:
                    continue
                raw = p.stdout
            else:
                try:
                    raw = path.read_text(encoding="utf-8")
                except OSError as e:
                    yield rel, None, f"cannot read: {e}"
                    continue
            try:
                yield rel, json.loads(raw), None
            except ValueError as e:
                yield rel, None, f"cannot parse: {e}"


# ── self-test ───────────────────────────────────────────────────────────────
def _wf(nodes, conns, execution_order="v1"):
    return {"nodes": nodes, "connections": conns, "settings": {"executionOrder": execution_order}}


def _n(name, pos, ntype="n8n-nodes-base.noOp"):
    return {"name": name, "type": ntype, "position": list(pos), "id": name, "parameters": {}}


def self_test() -> int:
    bad = 0

    def check(label, cond):
        nonlocal bad
        bad += 0 if cond else 1
        print(f"  [{'ok ' if cond else 'FAIL'}] {label}")

    # the engine's ordering, restated and pinned
    check("v1 order: top-most (smaller y) runs first",
          execution_rank([500, 10]) < execution_rank([0, 20]))
    check("v1 order: on an exact y tie, left-most runs first",
          execution_rank([100, 50]) < execution_rank([900, 50]))

    # HEALTHY: loop output fans out to work (above) and back to the loop node (below)
    healthy = _wf(
        [_n("Loop", (1000, 500), SPLIT_IN_BATCHES), _n("Work", (1200, 300)), _n("Done", (1200, 100))],
        {"Loop": {"main": [[{"node": "Done", "type": "main", "index": 0}],
                           [{"node": "Work", "type": "main", "index": 0},
                            {"node": "Loop", "type": "main", "index": 0}]]}})
    check("healthy: work lane above the self re-entry passes", check_doc(healthy) == [])

    # BROKEN: the very shape n8n-layout.py produced — work at the SAME y, further right
    broken = json.loads(json.dumps(healthy))
    for n in broken["nodes"]:
        if n["name"] == "Work":
            n["position"] = [1200, 500]          # same y as Loop, larger x -> Loop wins the tiebreak
    problems = check_doc(broken)
    check("PROVE IT CAN FAIL — work at equal y but further right is caught (the x tiebreak)",
          any("LOOP DRAINED BEFORE WORK" in p for p in problems))

    # BROKEN: work strictly below the loop node
    below = json.loads(json.dumps(healthy))
    for n in below["nodes"]:
        if n["name"] == "Work":
            n["position"] = [1200, 900]
    check("PROVE IT CAN FAIL — work strictly below the re-entry is caught",
          any("LOOP DRAINED BEFORE WORK" in p for p in check_doc(below)))

    # BROKEN: re-entry via a separate node that leads back to a splitInBatches driver.
    # An earlier version of this gate asserted the OPPOSITE here — that an intermediate hop is not
    # a re-entry "unless it IS the driver" — and called that a false-positive guard. Tracing the
    # engine shows it is a real drain: Body's fan-out sorts to [Back(y=0), Work(y=400)], Back runs,
    # unshifts Loop, Loop emits the next batch and unshifts Body — all before Work ever runs.
    # This shape is live in indoxGmailDocDownloader01 ('Code' -> 'End Process Gmail Document'),
    # where only the y coordinates keep it correct.
    indirect = _wf(
        [_n("Loop", (0, 0), SPLIT_IN_BATCHES), _n("Body", (200, 0)),
         _n("Work", (400, 400)), _n("Back", (400, 0))],
        {"Loop": {"main": [[], [{"node": "Body", "type": "main", "index": 0}]]},
         "Body": {"main": [[{"node": "Back", "type": "main", "index": 0},
                            {"node": "Work", "type": "main", "index": 0}]]},
         "Back": {"main": [[{"node": "Loop", "type": "main", "index": 0}]]}})
    check("PROVE IT CAN FAIL — re-entry through an INTERMEDIATE hop above the work lane is caught",
          any("LOOP DRAINED BEFORE WORK" in p for p in check_doc(indirect)))

    # ...and the same graph is clean once the work lane is raised above the returning hop
    indirect_ok = json.loads(json.dumps(indirect))
    for n in indirect_ok["nodes"]:
        if n["name"] == "Work":
            n["position"] = [400, -200]
    check("indirect re-entry: clean once the work lane sits above the returning hop",
          check_doc(indirect_ok) == [])

    # NOT A RACE: different output indices are mutually exclusive. This is the syncV3Deliver0001
    # shape — out0 = success -> the normal loop return, out1 = error sink (onError
    # continueErrorOutput). The gate reported this for weeks; it must not.
    err_out = _wf(
        [_n("Loop", (500, 380), SPLIT_IN_BATCHES), _n("Work", (760, 460)),
         _n("Call", (1200, 460)), _n("ErrSink", (60, 700))],
        {"Loop": {"main": [[], [{"node": "Work", "type": "main", "index": 0}]]},
         "Work": {"main": [[{"node": "Call", "type": "main", "index": 0}]]},
         "Call": {"main": [[{"node": "Loop", "type": "main", "index": 0}],
                           [{"node": "ErrSink", "type": "main", "index": 0}]]}})
    check("NO FALSE POSITIVE — a loop return on out0 and an error sink on out1 never race",
          check_doc(err_out) == [])

    # BROKEN via the y tie alone — the indoxV2Driver01 'Loop Over Items39' shape
    tie = _wf(
        [_n("Loop", (-4512, 14840), SPLIT_IN_BATCHES), _n("Work", (-4288, 14840))],
        {"Loop": {"main": [[], [{"node": "Loop", "type": "main", "index": 0},
                                {"node": "Work", "type": "main", "index": 0}]]}})
    check("PROVE IT CAN FAIL — identical y, self-edge left of the work lane, caught by the x tiebreak",
          any("LOOP DRAINED BEFORE WORK" in p for p in check_doc(tie)))
    tie_ok = json.loads(json.dumps(tie))
    for n in tie_ok["nodes"]:
        if n["name"] == "Work":
            n["position"] = [-4288, 14744]
    check("the same graph is clean once the tie is broken (work strictly above)",
          check_doc(tie_ok) == [])

    direct = _wf(
        [_n("Loop", (0, 0), SPLIT_IN_BATCHES), _n("Body", (200, 0)), _n("Work", (400, 400))],
        {"Loop": {"main": [[], [{"node": "Body", "type": "main", "index": 0}]]},
         "Body": {"main": [[{"node": "Loop", "type": "main", "index": 0},
                            {"node": "Work", "type": "main", "index": 0}]]}})
    check("PROVE IT CAN FAIL — body fanning back to the loop driver above its own work lane",
          any("LOOP DRAINED BEFORE WORK" in p for p in check_doc(direct)))

    # a non-v1 workflow is out of scope
    v0 = json.loads(json.dumps(broken))
    v0["settings"]["executionOrder"] = "v0"
    check("executionOrder v0 is not position-ordered, so it is not flagged", check_doc(v0) == [])

    # a fan-out with no cycle is not this gate's business
    plain = _wf([_n("A", (0, 0)), _n("B", (200, 0)), _n("C", (200, 200))],
                {"A": {"main": [[{"node": "B", "type": "main", "index": 0},
                                 {"node": "C", "type": "main", "index": 0}]]}})
    check("a plain fan-out with no loop re-entry is not flagged", check_doc(plain) == [])

    # ── the second rule: the lane does not lead back into the loop ──
    check("returns: a loop wired to its lane AND to itself is by the rule",
          check_returns(healthy) == [] and check_returns(tie) == [])
    back_problems = check_returns(err_out)
    check("PROVE IT CAN FAIL — a loop re-entered from its lane's last node is named with that node",
          len(back_problems) == 1 and "'Call'" in back_problems[0] and "LANE LEADS BACK" in back_problems[0])
    check("returns: every node that leads back is named once, per loop",
          len(check_returns(indirect)) == 1 and "'Back'" in check_returns(indirect)[0])
    old_loop = _wf(
        [dict(_n("Loop", (0, 0), SPLIT_IN_BATCHES), typeVersion=2), _n("Upsert", (200, 0))],
        {"Loop": {"main": [[{"node": "Upsert", "type": "main", "index": 0}]]},
         "Upsert": {"main": [[{"node": "Loop", "type": "main", "index": 0}]]}})
    check("returns: a one-output (typeVersion < 3) loop fed back by its lane is caught too",
          len(check_returns(old_loop)) == 1)
    dead = _wf(
        [_n("Start", (0, 0)), _n("Loop", (0, 300), SPLIT_IN_BATCHES), _n("Work", (200, 0))],
        {"Start": {"main": [[{"node": "Work", "type": "main", "index": 0}]]},
         "Loop": {"main": [[], [{"node": "Work", "type": "main", "index": 0}]]}})
    check("returns: a loop nothing comes back to is not this rule's finding", check_returns(dead) == [])
    v0_back = json.loads(json.dumps(err_out))
    v0_back["settings"]["executionOrder"] = "v0"
    check("returns: the rule does not depend on executionOrder", len(check_returns(v0_back)) == 1)

    print(f"\nG45 self-test: {'ALL PASS' if bad == 0 else f'{bad} FAILING'}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--rev", help="audit this git revision's blueprints instead of the working tree")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    findings: list[tuple[str, str]] = []
    n_files = n_shipped = 0
    for rel, doc, err in iter_docs(a.rev):
        n_files += 1
        n_shipped += rel.endswith(".workflow.ts") and not err
        if err:
            findings.append((rel, err))
            continue
        if not isinstance(doc, dict) or "nodes" not in doc:
            continue
        # the second rule is asked of what RUNS — a snapshot of a retired workflow is a record
        for problem in check_doc(doc) + (check_returns(doc) if rel.endswith(".workflow.ts") else []):
            findings.append((rel, problem))

    where = f" at {a.rev}" if a.rev else ""
    if not a.rev and not n_shipped:
        print("G45 FAIL — read ZERO shipped blueprint workflows, so no loop that runs was checked.\n"
              "  globs: " + ", ".join(BLUEPRINT_GLOBS))
        return 1
    if not findings:
        print(f"G45 PASS — all {n_files} workflow(s){where} ({n_shipped} shipped blueprint(s)): every "
              f"loop fan-out runs its work lane before re-entering the loop, and no lane leads back "
              f"into its loop.")
        return 0

    drained = sum(1 for _f, p in findings if p.startswith("LOOP DRAINED"))
    led_back = sum(1 for _f, p in findings if p.startswith("LANE LEADS BACK"))
    print(f"G45 FAIL{where} — {len(findings)} problem(s) across "
          f"{len({f for f, _ in findings})} workflow(s): {drained} loop(s) drained before their work, "
          f"{led_back} re-entered from their own lane:\n")
    for path, problem in findings:
        print(f"  {path}")
        print(f"      {problem}\n")
    print("  Fix by hand: raise the work lane above the loop re-entry node on the canvas; wire a\n"
          "  loop to itself rather than back from its lane.\n"
          "  There is no auto-fixer on purpose — see this gate's module docstring.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
