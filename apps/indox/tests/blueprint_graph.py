"""blueprint_graph — an n8n-as-code blueprint's graph, read without node (the Mac has none), for the tests here.

The `/*__n8n__*/ connections:` JSON line is the graph n8n receives (ai/context/n8n-development.md); the links()
DSL below it is a view of it. Not a test itself: G72 runs only test_* files.
"""
import json
import re

MODEL = re.compile(r"(?i)gemini|lmchat|openai|anthropic|mistral|deepseek|\.agent$|chainllm|chainsummarization"
                   r"|informationextractor|textclassifier|sentimentanalysis")
TRIGGER = re.compile(r"(?i)trigger$|\.webhook$")
# an HTTP node that calls an outside model's host is a model too
AI_URL = re.compile(r"(?i)https://[\w.-]*(googleapis\.com|openai\.com|anthropic\.com|deepseek\.com|mistral\.ai"
                    r"|groq\.com|openrouter\.ai|cohere\.(ai|com))")
NODE = re.compile(r"(?ms)^    @node\(\{\n(.*?)^    \}\)\n    (\w+) = ")
LINK = re.compile(r"this\.(\w+)\.out\((\d+)\)\.to\(this\.(\w+)\.in\((\d+)\)\)")


class Graph:
    def __init__(self, path):
        self.text = text = path.read_text(encoding="utf-8")
        self.nodes, self.props = {}, {}
        for block, prop in NODE.findall(text):
            name = re.search(r"""^        name: (?:'([^']*)'|"([^"]*)"),?$""", block, re.M)
            name = name.group(1) if name.group(1) is not None else name.group(2)
            typ = re.search(r"^        type: '([^']+)'", block, re.M).group(1)
            self.nodes[name] = {"type": typ, "prop": prop, "decorator": block}
            self.props[prop] = name
        assert len(self.nodes) == text.count("    @node({"), "%s: a node's block escaped the scan" % path.name
        conn = json.loads(re.search(r"^    /\*__n8n__\*/ connections: (\{.*\}),$", text, re.M).group(1))
        self.edges, self.other = set(), set()   # main; and ai_*/other types (a sub-node feeding a root)
        for src, outs in conn.items():
            for kind, outputs in outs.items():
                for i, targets in enumerate(outputs or []):
                    for t in targets or []:
                        (self.edges if kind == "main" else self.other).add((src, i, t["node"], t.get("index", 0)))
        # a link naming no declared node keeps its property name with a '?', so a comparison shows it
        self.links = {(self.props.get(a, "?" + a), int(i), self.props.get(b, "?" + b), int(j))
                      for a, i, b, j in LINK.findall(text)}
        self.models = {n for n, v in self.nodes.items() if MODEL.search(v["type"])
                       or (v["type"].endswith(".httpRequest") and AI_URL.search(self.body(n)))}
        self.triggers = {n for n, v in self.nodes.items() if TRIGGER.search(v["type"])}
        self.checks = sorted(n for n, v in self.nodes.items() if v["type"].endswith(".postgres")
                             and "extraction_ai_enabled" in self.body(n))

    def body(self, name):
        m = re.search(r"(?ms)^    %s = \{\n(.*?)^    \};" % re.escape(self.nodes[name]["prop"]), self.text)
        return m.group(1) if m else ""

    def after(self, name, output=None):
        return {d for s, i, d, _ in self.edges if s == name and (output is None or i == output)}

    def before(self, name):
        return {s for s, _, d, _ in self.edges if d == name}

    def reachable(self, starts, cut=frozenset()):
        seen, todo = set(starts), list(starts)
        while todo:
            n = todo.pop()
            nxt = [d for s, i, d, _ in self.edges if s == n and (s, i) not in cut]
            nxt += [b if a == n else a for a, _, b, _ in self.other if n in (a, b)]   # a root runs its sub-nodes
            for d in nxt:
                if d not in seen:
                    seen.add(d)
                    todo.append(d)
        return seen
