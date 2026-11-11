"""The Drive agent sends an image or a recording to OpenAI only when the office says ITS key is set (DGO-1814).

    python3 apps/google-workspace-agent/tests/test_agent_ai_gate.py

gDriveMcpAgent01's two OpenAI nodes (Analyse Image, Transcribe Audio) took the office's general OPENAI_API_KEY with no
switch of their own, and an OpenAI node with an empty key still sends the file — OpenAI refuses it after it left.
What holds, read from the blueprint's authoritative connections JSON (the graph n8n receives; the links() view must
equal it) and the files around it:
  · every model node is behind a check: with the IF nodes' TRUE outputs cut, no model is reachable from any trigger,
    and with them it is (the test can see a model at all);
  · each check asks the connections service `GET /api/is-set/google-workspace-agent-openai` — a boolean, no value —
    and is its IF's only input, with no onError / continueOnFail / alwaysOutputData (unreachable = nothing sent);
  · each IF tests `$json.set` is boolean true; its FALSE output reaches the off reply, never a model;
  · the resume step hands the model the downloaded file (json and binary), so the tools work as before when on;
  · both OpenAI nodes take the agent's OWN credential gwaAgentOpenAi01, whose key is
    GOOGLE_WORKSPACE_AGENT_OPENAI_API_KEY (apps/n8n/blueprint.yml), empty in .env.ex, an EXTERNAL key of
    scripts/env-secrets.py, and the provider the app declares (contributes.connection_providers) under the id the
    check asks for.

GATE_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old one).
"""
import json
import os
import pathlib
import re
import unittest

ROOT = pathlib.Path(os.environ.get("GATE_ROOT") or pathlib.Path(__file__).resolve().parents[3])
WF = ROOT / "apps/google-workspace-agent/blueprint/n8n/gDriveMcpAgent01.workflow.ts"
CONN_ID = "google-workspace-agent-openai"
ENV_KEY = "GOOGLE_WORKSPACE_AGENT_OPENAI_API_KEY"
CRED = "gwaAgentOpenAi01"

MODEL = re.compile(r"(?i)openai|lmchat|gemini|anthropic|mistral|deepseek|\.agent$|chainllm")
TRIGGER = re.compile(r"(?i)trigger$|\.webhook$")
NODE = re.compile(r"(?ms)^    @node\(\{\n(.*?)^    \}\)\n    (\w+) = ")
LINK = re.compile(r"this\.(\w+)\.out\((\d+)\)\.to\(this\.(\w+)\.in\((\d+)\)\)")


class Graph:
    def __init__(self, path):
        self.text = text = path.read_text(encoding="utf-8")
        self.nodes, self.props = {}, {}
        for block, prop in NODE.findall(text):
            name = re.search(r"^        name: '([^']*)',?$", block, re.M).group(1)
            typ = re.search(r"^        type: '([^']+)'", block, re.M).group(1)
            self.nodes[name] = {"type": typ, "prop": prop, "decorator": block}
            self.props[prop] = name
        assert len(self.nodes) == text.count("    @node({"), "a node's block escaped the scan"
        conn = json.loads(re.search(r"^    /\*__n8n__\*/ connections: (\{.*\}),$", text, re.M).group(1))
        self.edges = set()
        for src, outs in conn.items():
            for i, targets in enumerate(outs.get("main") or []):
                for t in targets or []:
                    self.edges.add((src, i, t["node"], t.get("index", 0)))
        self.links = {(self.props.get(a, "?" + a), int(i), self.props.get(b, "?" + b), int(j))
                      for a, i, b, j in LINK.findall(text)}
        self.models = {n for n, v in self.nodes.items() if MODEL.search(v["type"])}
        self.triggers = {n for n, v in self.nodes.items() if TRIGGER.search(v["type"])}

    def body(self, name):
        m = re.search(r"(?ms)^    %s = \{\n(.*?)^    \};" % re.escape(self.nodes[name]["prop"]), self.text)
        return m.group(1) if m else ""

    def of_type(self, suffix):
        return sorted(n for n, v in self.nodes.items() if v["type"].endswith(suffix))

    def reachable(self, starts, cut=frozenset()):
        seen, todo = set(starts), list(starts)
        while todo:
            n = todo.pop()
            for s, i, d, _ in self.edges:
                if s == n and (s, i) not in cut and d not in seen:
                    seen.add(d)
                    todo.append(d)
        return seen


class AgentAiGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = Graph(WF)
        cls.checks = [n for n in cls.g.of_type(".httpRequest") if f"/api/is-set/{CONN_ID}'" in cls.g.body(n)]
        cls.ifs = cls.g.of_type(".if")

    def test_no_model_is_reachable_with_the_gates_true_outputs_cut(self):
        g = self.g
        self.assertTrue(g.models, "the scan sees the agent's model nodes")
        self.assertTrue(g.models & g.reachable(g.triggers), "with the gates open a model is reachable")
        cut = {(n, 0) for n in self.ifs}
        self.assertEqual(g.models & g.reachable(g.triggers, cut), set(), "a model reachable around the gate")

    def test_each_check_asks_the_office_and_is_its_ifs_only_input_and_fails_closed(self):
        g = self.g
        self.assertEqual(len(self.checks), 2, self.checks)
        for c in self.checks:
            self.assertIn("url: 'http://connections:8990/api/is-set/google-workspace-agent-openai'", g.body(c))
            for flag in ("onError", "continueOnFail", "alwaysOutputData", "neverError"):
                self.assertNotIn(flag, g.nodes[c]["decorator"] + g.body(c), f"{c}: {flag}")
            nxt = {d for s, _, d, _ in g.edges if s == c}
            self.assertEqual(len(nxt), 1, (c, nxt))
            (iff,) = nxt
            self.assertIn(iff, self.ifs)
            self.assertEqual({s for s, _, d, _ in g.edges if d == iff}, {c}, f"{iff}: the check is its only input")
            for flag in ("onError", "continueOnFail", "alwaysOutputData"):   # an IF that fails must not pass its input on
                self.assertNotIn(flag, g.nodes[iff]["decorator"] + g.body(iff), f"{iff}: {flag}")
            body = g.body(iff)
            self.assertIn("leftValue: '={{ $json.set }}'", body)
            self.assertIn("operator: { type: 'boolean', operation: 'true', singleValue: true }", body)
            self.assertIn("typeValidation: 'strict'", body)

    def test_the_false_side_answers_off_and_reaches_no_model(self):
        g = self.g
        for iff in self.ifs:
            off = {d for s, i, d, _ in g.edges if s == iff and i == 1}
            self.assertEqual(off, {"Agent AI Off Response"}, iff)
            self.assertEqual(g.models & g.reachable(off), set())
        self.assertIn("no OpenAI key of its own", g.body("Agent AI Off Response"))

    def test_the_resume_step_hands_the_model_the_downloaded_file(self):
        g = self.g
        for iff in self.ifs:
            (resume,) = {d for s, i, d, _ in g.edges if s == iff and i == 0}
            body = g.body(resume)
            self.assertIn("mode: 'runOnceForEachItem'", body)
            self.assertIn("return { json: $('Download File1').item.json, binary: $('Download File1').item.binary };",
                          body)
            self.assertTrue({d for s, _, d, _ in g.edges if s == resume} <= g.models, resume)

    def test_the_links_view_is_the_graph(self):
        self.assertEqual(self.g.links, self.g.edges)

    def test_the_models_take_the_agents_own_credential_and_key(self):
        g = self.g
        for m in g.models:
            self.assertIn(f"openAiApi: {{ id: '{CRED}'", g.nodes[m]["decorator"], m)
            self.assertNotIn("xu8Y1cko7L6LmqMd", g.nodes[m]["decorator"], m)
        bp = (ROOT / "apps/n8n/blueprint.yml").read_text(encoding="utf-8")
        line = next(ln for ln in bp.splitlines() if ln.strip().startswith(f"{CRED}:"))
        self.assertIn('"apiKey":"${%s}"' % ENV_KEY, line)
        self.assertEqual(json.loads((ROOT / f"apps/n8n/credentials/{CRED}.json").read_text())["id"], CRED)
        self.assertIn(f"\n{ENV_KEY}=\n", (ROOT / ".env.ex").read_text(encoding="utf-8"), "empty in the template")
        es = (ROOT / "scripts/env-secrets.py").read_text(encoding="utf-8")
        external = es[es.index("EXTERNAL = ("):]
        self.assertIn(f'"{ENV_KEY}"', external[:external.index(")")])
        app = json.loads((ROOT / "apps/google-workspace-agent/app.json").read_text(encoding="utf-8"))
        prov = {p["id"]: p for p in app.get("contributes", {}).get("connection_providers", [])}
        self.assertEqual(prov.get(CONN_ID, {}).get("env"), ENV_KEY)
        self.assertIn(CONN_ID, {c["id"] for c in app.get("connections", [])})


if __name__ == "__main__":
    unittest.main(verbosity=2)
