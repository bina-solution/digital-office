#!/usr/bin/env python3
"""The proof's two lanes (scripts/ci/gates.sh --fast / --slow, DGO-2123): fail fast, and never a gate left out.

    python3 scripts/test_gates_lanes.py

A version's proof runs every self-test and every gate under ~10 s first, and the slow gates (gates.sh's SLOW) only
once those passed — so a red a seconds-long gate finds ends the job in minutes. Two lanes are one list cut in two:
a gate in neither is a gate the proof stopped running, a gate in both runs twice. This holds the cut, and that
gates-hosted runs the fast lane before the slow one, with one blueprint compile for both.
"""
import pathlib
import subprocess
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
GATES = REPO / "scripts" / "ci" / "gates.sh"


def listed(*flags):
    p = subprocess.run(["bash", str(GATES), *flags, "--list"], capture_output=True, text=True, timeout=60, cwd=REPO)
    assert p.returncode == 0, p.stderr
    return [ln for ln in p.stdout.splitlines() if ln.strip()]


class Lanes(unittest.TestCase):
    def test_the_lanes_cut_the_one_list_in_two(self):
        every, fast, slow = listed(), listed("--fast"), listed("--slow")
        self.assertGreater(len(every), 50, "the list itself")
        self.assertEqual(set(fast) & set(slow), set(), "a gate in both lanes runs twice")
        self.assertEqual(sorted(fast + slow), sorted(every), "a gate in neither lane is a gate the proof stopped running")
        self.assertTrue(fast and slow)
        self.assertEqual(fast, [g for g in every if g in fast], "a lane keeps the list's order")
        self.assertIn("plane-tests-lint", slow)          # G72: 996 s of the half hour
        self.assertIn("issue-file-lint", fast)           # G75: batch 87's night of red

    def test_the_flag_may_come_before_or_after_list(self):
        p = subprocess.run(["bash", str(GATES), "--list", "--slow"], capture_output=True, text=True, timeout=60,
                           cwd=REPO)
        self.assertEqual([ln for ln in p.stdout.splitlines() if ln.strip()], listed("--slow"))

    def wf(self):
        return (REPO / ".github" / "workflows" / "gates-hosted.yml").read_text(encoding="utf-8")

    def test_the_proof_runs_the_fast_lane_first_with_one_blueprint_compile(self):
        wf = self.wf()
        steps = wf[wf.index("\n  gates:"):wf.index("\n  slow:")].split("\n      - ")
        lanes = [s for s in steps if "bash scripts/ci/gates.sh" in s]
        self.assertEqual(len(lanes), 2, "two lanes, no third run of everything")
        self.assertIn("gates.sh --fast", lanes[0], "the fast lane runs first")
        self.assertIn("gates.sh --slow", lanes[1])
        self.assertTrue(all("N8N_BP_CACHE: ${{ runner.temp }}/n8nbp-cache" in s for s in lanes), "one cache for both")
        # a `continue-on-error` on a lane (above its `run:`) would let a red lane through to a green job — and on
        # dgo-stable to refs/green (the second reader). The one step that may carry it is the proof's clearing of the
        # way after both, which decides nothing (step-aside --clear, DGO-2123)
        for s in lanes:
            self.assertNotIn("continue-on-error", s, "a red lane ends the job")
        self.assertTrue(all("step-aside --clear" in s for s in steps if "continue-on-error" in s))
        self.assertIn('G72_JOBS: "2"', lanes[1])
        # here, the slow lane runs for the line and a hand-run; an office branch's push runs it in `slow` (below)
        self.assertIn("if: github.ref == 'refs/heads/dgo-stable' || github.event_name == 'workflow_dispatch'", lanes[1])

    def test_an_office_branchs_slow_lane_is_queued_once_its_fast_lane_passed(self):
        # the king, 2026-11-20 (DGO-2123): a branch's fast gates answer before the twenty-minute lane takes the runner
        wf = self.wf()
        job = wf[wf.index("\n  slow:"):wf.index("\n  carrier:")]
        self.assertIn("needs: [decide, gates]", job)
        self.assertIn("if: needs.decide.outputs.gates == 'true' && github.event_name == 'push' "
                      "&& github.ref != 'refs/heads/dgo-stable'", job, "exactly where the gates job's slow step is not")
        self.assertEqual(job.count("bash scripts/ci/gates.sh"), 1)
        self.assertIn("bash scripts/ci/gates.sh --slow", job)
        self.assertNotIn("continue-on-error", job)
        self.assertIn('G72_JOBS: "2"', job)

    def test_the_jobs_after_the_gates_keep_the_shared_workspace_and_green_on_time(self):
        # the second reader (DGO-2123): a sparse checkout with no directory of its own turns the runner's one workspace
        # into a blob-less clone for every later job; retention inside green made the offices that read the API wait for
        # it; a list left by an earlier job read as the newest would delete what the newest names
        wf = self.wf()
        go = wf[wf.index("\n  go:"):wf.index("\n  # GREEN AS GIT DATA")]
        self.assertIn("needs.gates.outputs.forward_auth == 'true'", go)
        self.assertIn("path: .go", go)
        self.assertIn("working-directory: .go/platform-base/forward-auth", go)
        green = wf[wf.index("\n  green:"):wf.index("\n  # READY-MADE IMAGES' RETENTION")]
        self.assertIn("needs: [decide, gates, carrier, images, go]", green)
        self.assertIn("(needs.go.result == 'success' || needs.go.result == 'skipped')", green,
                      "forward-auth's tests where they ran, and nothing where they did not")
        self.assertNotIn("store-retention.sh", green, "retention is a job of its own, after green")
        ret = wf[wf.index("\n  retention:"):wf.index("\n  # The proof is over")]
        self.assertIn("needs: [decide, green]", ret)
        self.assertIn("needs.green.result == 'success'", ret)
        self.assertIn("continue-on-error: true", ret)
        self.assertIn('git init -q --bare "${lists}"', ret, "the lists fetched fresh: a fetch that fails leaves none")
        for job in (go, ret):
            for block in job.split("- uses: actions/checkout@v4")[1:]:
                self.assertIn("path:", block.split("\n      - ")[0], "each checkout of theirs in a directory of its own")


if __name__ == "__main__":
    unittest.main(verbosity=1)
