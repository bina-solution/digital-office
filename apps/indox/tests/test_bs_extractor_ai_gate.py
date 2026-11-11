"""test_bs_extractor_ai_gate.py — INDOX's balance-sheet Gemini extractor asks the office before it calls a model.

    python3 apps/indox/tests/test_bs_extractor_ai_gate.py

indoxV2ExtractBalanceSheet01 (webhook `bs_ex_2_dev`, active) had no switch of its own: `extraction_ai_enabled`
held it only when BsDocEx01 called it, and any POST to its webhook reached Gemini directly
(issues/five-more-paths-reach-an-outside-ai-…, DGO-1792). What holds now, read from the blueprint's
authoritative graph (the `/*__n8n__*/ connections:` JSON, every connection type; the links() view below it
must say the same):

  a. a check reads `extraction_ai_enabled` in the instance's settings, true-word only, falling back to 'false',
     and refuses (throws) when the caller names no instance; it has no onError and no alwaysOutputData, so
     an error or an empty answer can never reach the gate's «on» side;
  b. every path from every trigger to every model node (a Gemini/OpenAI/… node, or an agent or chain root)
     runs through that check's gate, and the check is the gate's only input: with the gate's «AI on» output
     cut no model is reachable — and with it one is (the scan is not vacuous);
  c. the gate's «AI off» output reaches a webhook reply and no model, and the reply says ai_disabled and not
     success (BsDocEx01's Build AI Result reads ai_disabled first; any other caller reads it as no result);
  d. the «AI on» output hands the next node Before Start's own item (json and the file), so the flow after the
     gate sees what it saw before.

Not covered here: extraction.py's lab run posts to the webhook without an instance, so the check refuses it
(issues/indox-extraction-lab-ai-mode-names-no-instance-…).

BS_GATE_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old file).
"""
import json
import os
import pathlib
import re
import unittest

ROOT = pathlib.Path(os.environ.get("BS_GATE_ROOT") or pathlib.Path(__file__).resolve().parents[3])
WF = ROOT / "apps/indox/blueprint/n8n/indoxV2ExtractBalanceSheet01.workflow.ts"
MODEL = re.compile(r"(?i)gemini|lmchat|openai|anthropic|mistral|deepseek|\.agent$|chainllm|chainsummarization"
                   r"|informationextractor|textclassifier|sentimentanalysis")
TRIGGER = re.compile(r"(?i)trigger$|\.webhook$")
NODE = re.compile(r"(?ms)^    @node\(\{\n(.*?)^    \}\)\n    (\w+) = ")
LINK = re.compile(r"this\.(\w+)\.out\((\d+)\)\.to\(this\.(\w+)\.in\((\d+)\)\)")


def load():
    text = WF.read_text(encoding="utf-8")
    nodes, props = {}, {}
    for block, prop in NODE.findall(text):
        name = re.search(r"""^        name: (?:'([^']*)'|"([^"]*)"),?$""", block, re.M)
        typ = re.search(r"^        type: '([^']+)'", block, re.M)
        name = name.group(1) if name.group(1) is not None else name.group(2)
        nodes[name] = {"type": typ.group(1), "prop": prop}
        props[prop] = name
    conn = json.loads(re.search(r"^    /\*__n8n__\*/ connections: (\{.*\}),$", text, re.M).group(1))
    edges = set()
    other = set()   # ai_* and any other connection type: a sub-node feeding a root, followed both ways below
    for src, outs in conn.items():
        for kind, outputs in outs.items():
            for i, targets in enumerate(outputs or []):
                for t in targets or []:
                    (edges if kind == "main" else other).add((src, i, t["node"], t.get("index", 0)))
    links = {(props[a], int(i), props[b], int(j)) for a, i, b, j in LINK.findall(text)}
    assert len(nodes) == text.count("    @node({"), "a node's block escaped the scan"
    return text, nodes, props, edges, links, other


def body(text, prop):
    m = re.search(r"(?ms)^    %s = \{\n(.*?)^    \};" % re.escape(prop), text)
    return m.group(1) if m else ""


def reachable(edges, starts, cut=frozenset(), other=frozenset()):
    seen, todo = set(starts), list(starts)
    while todo:
        n = todo.pop()
        nxt = [dst for src, i, dst, _ in edges if src == n and (src, i) not in cut]
        nxt += [b if a == n else a for a, _, b, _ in other if n in (a, b)]   # a root runs its sub-nodes
        for dst in nxt:
            if dst not in seen:
                seen.add(dst)
                todo.append(dst)
    return seen


class BsExtractorAsksBeforeTheModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text, cls.nodes, cls.props, cls.edges, cls.links, cls.other = load()
        cls.models = {n for n, v in cls.nodes.items() if MODEL.search(v["type"])}
        cls.triggers = {n for n, v in cls.nodes.items() if TRIGGER.search(v["type"])}
        cls.checks = [n for n, v in cls.nodes.items() if v["type"].endswith(".postgres")
                      and "extraction_ai_enabled" in body(cls.text, v["prop"])]
        gates = [d for s, _, d, _ in cls.edges if cls.checks and s == cls.checks[0]]
        cls.gate = gates[0] if len(gates) == 1 else None

    def test_the_scan_sees_the_workflow(self):
        self.assertGreaterEqual(len(self.models), 3, "model nodes found: %s" % sorted(self.models))
        self.assertGreaterEqual(len(self.triggers), 3, "triggers found: %s" % sorted(self.triggers))

    def test_a_check_reads_the_switch_true_word_only_falling_back_to_false(self):
        self.assertEqual(len(self.checks), 1, "checks of extraction_ai_enabled: %s" % self.checks)
        q = body(self.text, self.nodes[self.checks[0]]["prop"])
        self.assertRegex(q, r"key='extraction_ai_enabled' AND lower\(trim\(value\)\) = 'true'\), 'false'\) AS ai_enabled")
        self.assertIn("'indox_' + i", q)
        self.assertIn("throw new Error", q, "no instance must refuse, not read another instance's switch")
        # an error or an empty answer must stop the flow, never hand the gate an item without ai_enabled
        deco = re.search(r"(?ms)^    @node\(\{\n((?:(?!^    \}\)).)*?)^    \}\)\n    %s = " % self.nodes[self.checks[0]]["prop"],
                         self.text).group(1)
        self.assertNotIn("onError", deco)
        self.assertNotIn("alwaysOutputData", deco)

    def test_every_path_to_a_model_runs_through_the_gate(self):
        self.assertIsNotNone(self.gate, "the check must feed exactly one gate")
        self.assertRegex(body(self.text, self.nodes[self.gate]["prop"]),
                         r"leftValue: '=\{\{ \$json\.ai_enabled \}\}',\s*rightValue: 'false',\s*operator: \{\s*type: 'string',\s*operation: 'equals'")
        into_gate = {s for s, _, d, _ in self.edges if d == self.gate}
        self.assertEqual(into_gate, {self.checks[0]}, "the gate's only input is the check")
        open_ = reachable(self.edges, self.triggers, other=self.other) & self.models
        self.assertTrue(open_, "with the gate open no model is reachable — the scan is vacuous")
        shut = reachable(self.edges, self.triggers, cut={(self.gate, 1)}, other=self.other) & self.models
        self.assertEqual(shut, set(), "reachable past the gate's «AI on» output being cut")

    def test_ai_off_answers_the_caller_and_reaches_no_model(self):
        self.assertIsNotNone(self.gate)
        off = {d for s, i, d, _ in self.edges if s == self.gate and i == 0}
        after = reachable(self.edges, off, other=self.other)
        self.assertEqual(after & self.models, set())
        replies = [n for n in after if self.nodes[n]["type"].endswith(".respondToWebhook")]
        self.assertEqual(len(replies), 1, "AI off must answer the webhook once: %s" % replies)
        said = "".join(body(self.text, self.nodes[n]["prop"]) for n in after)
        self.assertRegex(said, r"name: 'ai_disabled',\s*value: true,\s*type: 'boolean'")
        self.assertRegex(said, r"name: 'success',\s*value: false,\s*type: 'boolean'")

    def test_ai_on_hands_on_before_starts_own_item(self):
        self.assertIsNotNone(self.gate)
        on = [d for s, i, d, _ in self.edges if s == self.gate and i == 1]
        self.assertEqual(len(on), 1)
        code = body(self.text, self.nodes[on[0]]["prop"])
        self.assertIn("mode: 'runOnceForEachItem'", code)
        self.assertIn("json: $('Before Start').item.json", code)
        self.assertIn("binary: $('Before Start').item.binary", code)

    def test_the_links_view_says_what_the_graph_says(self):
        self.assertEqual(self.links, self.edges)


if __name__ == "__main__":
    unittest.main(verbosity=2)
