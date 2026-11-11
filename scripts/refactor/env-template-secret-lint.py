#!/usr/bin/env python3
"""G93 — the template carries no secret; every secret an office makes is made by the one generator.

    python3 scripts/refactor/env-template-secret-lint.py              # the check
    python3 scripts/refactor/env-template-secret-lint.py --self-test  # the shapes it catches and spares

WHY (DGO-1220). .env.ex held the office's real secrets on purpose (a52d8118), and every install that copies
it — debian-install.sh, scripts/onboarding, packaging/linux/header.sh, README's `cp` — ran on them, so offices
shared their database passwords, their vault key and their n8n encryption key with each other and with
whoever holds the template. Part 2 emptied the template and made scripts/env-secrets.py the one place a
value is made. This gate keeps it that way:

  (a) a secret-named key of .env.ex holds a value (a placeholder word counts too: an empty value is how the
      generator and the apps know to make one);
  (b) any value of .env.ex, under any name, is shaped like a generated secret (hex of 32+, a JWT, or 32+
      characters of a token alphabet with high entropy);
  (c) a secret-named key of .env.ex is in none of env-secrets.py's lists (TABLE: minted; APP_MADE: the app
      issues it; EXTERNAL: the owner pastes it), so nobody would ever make it;
  (d) a tracked compose file falls back to a LITERAL for a secret-named variable (`${KEY:-word}`): an office
      with no line runs on the word, which is public. The ones that exist are a BASELINE — debt, not
      permission: an office may run on one today, and changing the fallback re-keys it (the vault's above
      all), which is DGO-1015's rotation. A file's count may only go down, and a count that fell without
      being recorded fails too.

It never prints a value: `path:line KEY rule`. A scan that reads no template or no compose file FAILS.
"""
import collections
import importlib.util
import math
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SECRET_NAME = re.compile(r"(PASS|PASSWORD|SECRET|TOKEN|_KEY|_PW|PASSPHRASE)$")
TOKEN_ALPHABET = re.compile(r"[A-Za-z0-9_+/=-]{32,}")

#: (file, key) -> how many `${key:-literal}` it holds today (DGO-1220: 17 in 7 files; 16 since DGO-860 took
#: openhands' JWT fallback out). Shrink only.
BASELINE = {
    ("apps/apitools/feature-validation/docker-compose.yml", "WHATSAPP_PASS"): 2,
    ("apps/chat/docker-compose.yml", "CHAT_AUTH_PASS"): 1,
    ("apps/chat/docker-compose.yml", "CHAT_RELAY_S3_KEY"): 3,
    ("apps/mail/docker-compose.yml", "LOCALMAIL_PW"): 2,
    ("apps/openhands/docker-compose.yml", "LITELLM_MASTER_KEY"): 3,
    ("apps/openhands/docker-compose.yml", "DISPATCHER_TOKEN"): 1,
    ("apps/project-pln/docker-compose.yml", "PLANE_S3_ACCESS_KEY"): 2,
    ("apps/supabase/docker-compose.yml", "SUPABASE_DASHBOARD_PASSWORD"): 1,
    ("platform-base/connections/docker-compose.yml", "CONNECTIONS_ROOT_KEY"): 1,
}


def generator():
    spec = importlib.util.spec_from_file_location("env_secrets", os.path.join(REPO, "scripts", "env-secrets.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def entropy(s):
    counts = collections.Counter(s)
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def secret_shaped(value):
    if re.fullmatch(r"[0-9a-fA-F]{32,}", value):
        return "hex"
    if re.fullmatch(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", value):
        return "jwt"
    if TOKEN_ALPHABET.fullmatch(value) and entropy(value) >= 4.0:
        return "token"
    return ""


def check_template(text, gen, where=".env.ex"):
    known = set(gen.TABLE) | set(gen.APP_MADE) | set(gen.EXTERNAL)
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).split(" #")[0].strip().strip("'\"")
        if SECRET_NAME.search(key) and value and "${" not in value:
            out.append(f"{where}:{n} {key} (a) a secret-named key holds a value — the template carries it empty")
        shape = secret_shaped(value) if value and "${" not in value else ""
        if shape:
            out.append(f"{where}:{n} {key} (b) the value is shaped like a generated secret ({shape})")
        if SECRET_NAME.search(key) and key not in known:
            out.append(f"{where}:{n} {key} (c) a secret-named key in none of env-secrets.py's TABLE, APP_MADE, EXTERNAL")
    return out


def compose_fallbacks(files, read):
    found = collections.Counter()
    for f in files:
        text = read(f)
        for m in re.finditer(r"\$\{([A-Z0-9_]+):?-([^}]+)\}", text):
            if SECRET_NAME.search(m.group(1)) and "$" not in m.group(2):
                found[(f, m.group(1))] += 1
    return found


def check_fallbacks(found, baseline):
    out = []
    for (f, key), n in sorted(found.items()):
        allowed = baseline.get((f, key), 0)
        if n > allowed:
            out.append(f"{f} {key} (d) {n} literal fallback(s) for a secret, {allowed} in the baseline")
    for (f, key), allowed in sorted(baseline.items()):
        if found.get((f, key), 0) < allowed:
            out.append(f"{f} {key} (d) {found.get((f, key), 0)} literal fallback(s), the baseline says {allowed} "
                       f"— lower it: the number only goes down")
    return out


def main():
    gen = generator()
    template = os.path.join(REPO, ".env.ex")
    if not os.path.isfile(template):
        print("G93 FAIL — no .env.ex: the template scan read nothing")
        return 1
    with open(template, encoding="utf-8") as fh:
        problems = check_template(fh.read(), gen)
    files = [f for f in subprocess.run(["git", "-C", REPO, "ls-files"], capture_output=True, text=True).stdout.split()
             if re.search(r"(^|/)(docker-)?compose[^/]*\.ya?ml$", f)]
    if not files:
        print("G93 FAIL — no tracked compose file: the fallback scan read nothing")
        return 1

    def read(f):
        with open(os.path.join(REPO, f), encoding="utf-8", errors="replace") as fh:
            return fh.read()
    found = compose_fallbacks(files, read)
    problems += check_fallbacks(found, BASELINE)
    print(f"G93 — .env.ex read; {len(files)} tracked compose file(s) read; {sum(found.values())} literal "
          f"fallback(s) for a secret ({sum(BASELINE.values())} in the baseline); no value is ever printed")
    for p in problems:
        print(f"  FAIL  {p}")
    print("G93 " + ("FAIL" if problems else "PASS"))
    return 1 if problems else 0


def self_test():
    gen = generator()
    cases = [
        ("POSTGRES_PASSWORD=" + "ab" * 24, ["(a)", "(b)"]),
        ("POSTGRES_PASSWORD=CHANGE_ME", ["(a)"]),
        ("SUPABASE_ANON_KEY=eyJhbGciOiJub25lIn0.eyJyZWRhY3RlZCI6dHJ1ZX0.REDACTED", ["(a)", "(b)"]),
        ("SOME_SETTING=" + "Zq8vT3xL0pW9mN2cR7yB4kH6jD1fG5sA", ["(b)"]),
        ("NEW_THING_TOKEN=", ["(c)"]),
        ("POSTGRES_PASSWORD=", []),
        ("OPENAI_API_KEY=", []),
        ("N8N_API_KEY=", []),
        ("SEARXNG_INSTANCE_URL=http://searxng.internal.example:8080/search", []),
        ("N8N_OWNER_EMAIL=someone-with-a-long-address@example.com", []),
        ("TZ=Asia/Jerusalem", []),
        ("FORGE_BASE_URL=forge.${DEPLOYMENT_DOMAIN}", []),
        ("# POSTGRES_PASSWORD=" + "ab" * 24, []),
    ]
    bad = 0
    for line, want in cases:
        got = sorted({p.split(") ")[0].split(" ")[-1] + ")" for p in check_template(line, gen)})
        if got != sorted(want):
            bad += 1
            print(f"  self-test FAIL: {line.split('=')[0]} expected {want}, got {got}")
    texts = {"a/docker-compose.yml": "x: ${DB_PASSWORD:-CHANGE_ME}\ny: ${DB_PASSWORD:-CHANGE_ME}\nz: ${HOST:-word}\n"
                                      "w: ${API_TOKEN:-${OTHER}}\nv: ${API_TOKEN:?set it}\n"}
    found = compose_fallbacks(texts, texts.get)
    checks = [
        (check_fallbacks(found, {("a/docker-compose.yml", "DB_PASSWORD"): 2}), 0, "the baseline holds"),
        (check_fallbacks(found, {("a/docker-compose.yml", "DB_PASSWORD"): 1}), 1, "one more than the baseline"),
        (check_fallbacks(found, {("a/docker-compose.yml", "DB_PASSWORD"): 3}), 1, "fewer than the baseline"),
        (check_fallbacks(found, {}), 1, "not in the baseline"),
    ]
    for got, want, what in checks:
        if len(got) != want:
            bad += 1
            print(f"  self-test FAIL: {what}: {len(got)} finding(s), expected {want}")
    total = len(cases) + len(checks)
    print(f"G93 self-test: {total - bad} of {total} as intended")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
