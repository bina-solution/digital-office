"""openhands reaches Gemini only on its own key line, never on INDOX's (DGO-1792).

    python3 apps/openhands/tests/test_gemini_needs_its_own_key.py

Every openhands service took `GEMINI_API_KEY=${GEMINI_API_KEY:-${GOOGLE_API_KEY:-}}` — INDOX's key — and the
code turns Gemini on whenever a key is there (dispatcher/server.js picks gemini-2.5-flash for vision,
generate-litellm-config.py lists every gemini/* model, and the agent's sandbox got it in OH_AGENT_SERVER_ENV).
So an office's yes for INDOX's extraction was a yes for openhands too. The owner's rule: no outside AI runs
without his word, and a word for one app is not a word for another.

What holds, by docker compose's own interpolation (${VAR}, ${VAR:-default}, ${VAR-default}, nested) run on
every value in apps/openhands/docker-compose.yml that carries a Gemini key — the services' GEMINI_API_KEY and
the sandbox's JSON:
  a. with INDOX's key set (GEMINI_API_KEY and GOOGLE_API_KEY) and nothing for openhands, each gets '';
  b. with OPENHANDS_GEMINI_API_KEY set, each gets that key (the yes still works when it is said);
  c. nothing in the file reads ${GEMINI_API_KEY…} or ${GOOGLE_API_KEY…} any more;
  d. .env.ex declares OPENHANDS_GEMINI_API_KEY empty.

OPENHANDS_GEMINI_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old file).
"""
import json
import os
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(os.environ.get("OPENHANDS_GEMINI_ROOT") or pathlib.Path(__file__).resolve().parents[3])
COMPOSE = ROOT / "apps/openhands/docker-compose.yml"
TEMPLATE = ROOT / ".env.ex"
INDOX_SAID_YES = {"GEMINI_API_KEY": "indox-key", "GOOGLE_API_KEY": "indox-key", "DEEPSEEK_API_KEY": "ds-key"}


def interpolate(s, env):
    """docker compose's interpolation: $$, ${VAR}, ${VAR:-d}, ${VAR-d}, ${VAR:?e}, ${VAR?e}; d may nest."""
    out, i = [], 0
    while i < len(s):
        if s.startswith("$$", i):
            out.append("$")
            i += 2
        elif s.startswith("${", i):
            j, depth = i + 2, 1
            while depth:
                if s.startswith("${", j):
                    depth, j = depth + 1, j + 2
                    continue
                if s[j] == "}":
                    depth -= 1
                j += 1
            name, colon, op, rest = re.match(r"([A-Za-z_]\w*)(?:(:?)([-?])(.*))?$", s[i + 2:j - 1], re.S).groups()
            val = env.get(name)
            unset = val is None or (colon == ":" and val == "")
            if op == "-" and unset:
                val = interpolate(rest, env)
            out.append(val or "")
            i = j
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def gemini_values():
    """(where, raw value) for every Gemini key the compose hands a container, the sandbox's JSON included."""
    found = []
    for svc, spec in (yaml.safe_load(COMPOSE.read_text(encoding="utf-8")).get("services") or {}).items():
        env = spec.get("environment") or []
        items = env.items() if isinstance(env, dict) else (e.split("=", 1) for e in env if "=" in e)
        for name, raw in items:
            if name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
                found.append(("%s %s" % (svc, name), raw, None))
            elif "GEMINI_API_KEY" in str(raw):
                found.append(("%s %s" % (svc, name), raw, "GEMINI_API_KEY"))
    return found


def resolved(raw, inner, env):
    value = interpolate(str(raw), env)
    return json.loads(value).get(inner, "") if inner else value


class OpenhandsGeminiNeedsItsOwnKey(unittest.TestCase):
    def test_the_scan_sees_every_service_that_takes_a_gemini_key(self):
        where = {w.split()[0] for w, _, _ in gemini_values()}
        self.assertGreaterEqual(where, {"openhands", "openhands-init", "llm-gateway-init", "dispatcher"}, where)
        self.assertTrue(any(inner for _, _, inner in gemini_values()), "the sandbox's OH_AGENT_SERVER_ENV")

    def test_indoxs_yes_is_not_openhands_yes(self):
        got = {w: resolved(raw, inner, INDOX_SAID_YES) for w, raw, inner in gemini_values()}
        self.assertEqual({w: v for w, v in got.items() if v}, {}, "INDOX's key reached an openhands container")

    def test_openhands_own_key_still_turns_it_on(self):
        env = dict(INDOX_SAID_YES, OPENHANDS_GEMINI_API_KEY="oh-key")
        got = {w: resolved(raw, inner, env) for w, raw, inner in gemini_values()}
        self.assertEqual(set(got.values()), {"oh-key"}, got)

    def test_nothing_reads_indoxs_key_line(self):
        # `$${GEMINI_API_KEY}` is compose's escape — the container's own variable, fed by the lines above
        text = COMPOSE.read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"(?<!\$)\$\{?(?:GEMINI|GOOGLE)_API_KEY\b", text), [])   # ${X…} and bare $X
        # a valueless entry (`- GOOGLE_API_KEY`) is filled from .env by compose itself
        for svc, spec in (yaml.safe_load(text).get("services") or {}).items():
            env = spec.get("environment") or []
            bare = [k for k, v in env.items() if v is None] if isinstance(env, dict) else [e for e in env if "=" not in e]
            self.assertFalse({"GEMINI_API_KEY", "GOOGLE_API_KEY"} & set(bare), svc)
            self.assertNotIn("env_file", spec, "%s: an env_file hands a container .env's lines" % svc)

    def test_the_template_declares_the_line_empty(self):
        lines = TEMPLATE.read_text(encoding="utf-8").splitlines()
        self.assertIn("OPENHANDS_GEMINI_API_KEY=", lines)

    def test_the_interpolation_is_composes(self):
        env = {"A": "a", "E": ""}
        self.assertEqual(interpolate("${A:-x}|${E:-x}|${E-x}|${U-x}|${U:-${A}}|$${A}|${U}", env), "a|x||x|a|${A}|")


if __name__ == "__main__":
    unittest.main(verbosity=2)
