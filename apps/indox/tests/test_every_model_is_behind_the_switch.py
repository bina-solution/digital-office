"""test_every_model_is_behind_the_switch.py — no INDOX path reaches a model past the office's word.

    python3 apps/indox/tests/test_every_model_is_behind_the_switch.py

The owner's rule: no outside AI without his word, and INDOX's word is the instance's `extraction_ai_enabled`.
Two extractors held it on one path only — the balance-sheet extractor on none of its own (fixed first), and the
invoice extractor's check sat on the cache-miss path, so its «use_cache is false» output reached Gemini past it
(DGO-1792). What holds now, for EVERY blueprint in apps/indox/blueprint/n8n that has a model node (a Gemini/
OpenAI/… node, an agent or chain root, or an HTTP node calling an outside model's host), read from its
authoritative graph:

  a. every check of the switch reads it true-word only, falling back to 'false', has no onError and no
     alwaysOutputData, and feeds exactly one gate — an If that skips on ai_enabled == 'false' — as its only input;
  b. with every gate's «on» output cut, no model is reachable from any trigger — and with them, one is;
  c. every gate's «off» output answers the webhook and reaches no model;
  d. the links() view says what the graph says.

INDOX_GATE_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old files).
"""
import os
import pathlib
import re
import unittest

from blueprint_graph import Graph

ROOT = pathlib.Path(os.environ.get("INDOX_GATE_ROOT") or pathlib.Path(__file__).resolve().parents[3])
BLUEPRINTS = sorted((ROOT / "apps/indox/blueprint/n8n").glob("*.workflow.ts"))
GATE_RULE = re.compile(r"leftValue: '=\{\{ \$json\.ai_enabled \}\}',\s*rightValue: 'false',\s*operator: \{\s*"
                       r"type: 'string',\s*operation: 'equals'")
SWITCH_SQL = re.compile(r"key='extraction_ai_enabled' AND lower\(trim\(value\)\) = 'true'\), 'false'\) AS ai_enabled")


def with_models():
    graphs = {p.name[: -len(".workflow.ts")]: Graph(p) for p in BLUEPRINTS}
    return {n: g for n, g in graphs.items() if g.models}


class EveryModelIsBehindTheSwitch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graphs = with_models()

    def test_the_scan_sees_the_extractors(self):
        self.assertGreaterEqual(len(BLUEPRINTS), 50, "blueprints read: %d" % len(BLUEPRINTS))
        self.assertGreaterEqual(set(self.graphs), {"indoxV2ExtractBalanceSheet01", "indoxV2ExtractInvoiceGemini01"})

    def test_every_check_reads_true_word_only_and_feeds_one_gate(self):
        for name, g in self.graphs.items():
            self.assertTrue(g.checks, "%s has a model and no check of extraction_ai_enabled" % name)
            for c in g.checks:
                self.assertRegex(g.body(c), SWITCH_SQL, "%s / %s" % (name, c))
                self.assertNotIn("onError", g.nodes[c]["decorator"], "%s / %s" % (name, c))
                self.assertNotIn("alwaysOutputData", g.nodes[c]["decorator"], "%s / %s" % (name, c))
                gates = g.after(c)
                self.assertEqual(len(gates), 1, "%s / %s feeds %s" % (name, c, sorted(gates)))
                gate = next(iter(gates))
                self.assertRegex(g.body(gate), GATE_RULE, "%s / %s" % (name, gate))
                # exactly one condition: a second one under 'and' would send items «on» with the switch off
                self.assertEqual(g.body(gate).count("operator: {"), 1, "%s / %s" % (name, gate))
                # the instance's own settings, never a fixed schema
                self.assertIn("'indox_' + i", g.body(c), "%s / %s" % (name, c))
                self.assertEqual(g.before(gate), {c}, "%s / %s: the gate's only input is its check" % (name, gate))

    def test_no_model_is_reachable_past_the_gates(self):
        for name, g in self.graphs.items():
            gates = {next(iter(g.after(c))) for c in g.checks if len(g.after(c)) == 1}
            self.assertTrue(g.reachable(g.triggers) & g.models, "%s: no model reachable at all — vacuous" % name)
            past = g.reachable(g.triggers, cut={(x, 1) for x in gates}) & g.models
            self.assertEqual(past, set(), "%s: reachable with every gate's «on» output cut" % name)

    def test_off_answers_and_reaches_no_model(self):
        for name, g in self.graphs.items():
            for c in g.checks:
                for gate in g.after(c):
                    after = g.reachable(g.after(gate, 0))
                    self.assertEqual(after & g.models, set(), "%s / %s" % (name, gate))
                    self.assertTrue([n for n in after if g.nodes[n]["type"].endswith(".respondToWebhook")],
                                    "%s / %s: AI off must answer the webhook" % (name, gate))

    def test_the_links_view_says_what_the_graph_says(self):
        for name, g in self.graphs.items():
            self.assertEqual(g.links, g.edges, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
