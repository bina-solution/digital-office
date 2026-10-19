#!/usr/bin/env python3
"""credential-blank-lint — gate G63: a push may never blank a live credential.

(G62 belongs to `mail-connection-lint.py`, which declares it in its own docstring. This gate took
the next free number instead — GATES.md's opening section records what re-used numbers cost.)

    python3 scripts/refactor/credential-blank-lint.py [--self-test]

`apps/n8n/blueprint.yml`'s `credential_overrides:` block declares, per n8n credential id,
which `.env` variables fill which fields. Step 1.5 of `apps/n8n/hooks/push` resolves each
`${VAR}` and PATCHes the result into the live credential, which re-encrypts it under the current
`N8N_ENCRYPTION_KEY`. That is the mechanism that makes env-driven credentials survive key drift, and
it is correct — as long as it only ever writes values it actually has.

WHAT BROKE (measured 2026-08-09). The resolver read

    v.replace(/\\$\\{(\\w+)\\}/g, (_, n) => process.env[n] !== undefined ? process.env[n] : "")

so an UNSET-or-EMPTY variable resolved to the empty string and was PATCHed in as if it were a value.
`.env` carried `GEMINI_API_KEY=` (empty; `.env.ex` carries a real one), so **every push** re-encrypted
an empty `apiKey` over credential `6mfcsdRaqQ4IdQ8Y` (ai-studio-bs-extraction). The workflow
`Balance Sheet Extractor - v2- shmuel` then failed 100% of runs with
"Forbidden - perhaps check your credentials?" out of its Google Gemini node — a live credential
destroyed by a routine push, with no error, no warning and no diff to point at. `BmKlKWiEeZAxNWyi`
(Chat Auth) went the same way via CHAT_AUTH_USER/CHAT_AUTH_PASS, which are not in `.env` at all;
three more (Priority Production, priority test, Document AI Connection) were spared only because
they had never been populated in the first place. Replaying the shipped resolver against the real
blueprint showed **20 PATCHes, 5 of them carrying an empty field**.

Worse, this step is INSTANCE-GLOBAL: `bbox n8n <app> push` narrows only which WORKFLOWS are staged
(the hook says so in step 2), so pushing *one* app re-seeds *every* credential. That is how a
`scope=mail` push destroyed the credential of an unrelated document-extraction app.

THE INVARIANT. A credential is reseeded only when every `${VAR}` it references resolves to a
non-empty value. Otherwise it is SKIPPED — loudly — and the live blob is left alone. "I have no
value for this" is not "set this to empty".

WHAT THIS GATE ASSERTS
  1. the reseed step still records unresolved vars and still SKIPS on them (the guard cannot be
     quietly deleted or refactored away);
  2. every `${VAR}` the overrides reference is declared in `.env.ex`, the committed template — an
     undeclared var can only ever resolve to empty on a fresh clone, which is precisely how Chat
     Auth was lost.

`.env` itself is deliberately NOT checked: it is untracked, per-machine, and legitimately empty for
optional integrations. An empty `.env` var is now a SKIP at push time, not a corruption — which is
the whole point of the fix. This gate keeps that true.
"""
import argparse
import json
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
HOOK = REPO / "apps" / "n8n" / "hooks" / "push"
BLUEPRINT = REPO / "apps" / "n8n" / "blueprint.yml"
ENV_EX = REPO / ".env.ex"

ENTRY_RE = re.compile(r"^\s{2}([A-Za-z0-9_-]+):\s*(\{.*\})\s*$", re.M)
VAR_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


def reseed_js(hook_text):
    """The single-quoted `node -e '...'` body of step 1.5, anchored on the step's own log line
    (the hook has several `node -e` blocks; the first one is the owner bootstrap)."""
    try:
        anchor = hook_text.index("Reseeding env-driven credentials from .env")
        i = hook_text.index("node -e ", anchor)
    except ValueError:
        return None
    start = hook_text.index("'", i) + 1
    end = hook_text.index("'", start)          # the block contains no other single quote
    return hook_text[start:end]


def check_guard(hook_text):
    """Assertion 1 — the skip-on-unset guard is present in the reseed resolver."""
    js = reseed_js(hook_text)
    if js is None:
        return ["step 1.5 reseed block not found in the push hook (did the log line change?)"]
    bad = []
    # the resolver must NOTICE an unset/empty var ...
    notices = re.search(r"===\s*undefined\s*\|\|\s*\w+\s*===\s*[\"']{2}", js) or \
        re.search(r"===\s*[\"']{2}\s*\|\|\s*\w+\s*===\s*undefined", js)
    if not notices:
        bad.append("the resolver does not test for BOTH undefined and empty-string; an unset or "
                   "blank ${VAR} will resolve to \"\" and be PATCHed in as a real value")
    # ... record it ...
    if "unset" not in js:
        bad.append("the resolver does not collect unresolved variable names (no `unset` list)")
    # ... and SKIP the PATCH because of it.
    if not re.search(r"unset(\.length|\s*&&)[^\n]*", js) or "continue" not in js:
        bad.append("the PATCH loop does not skip credentials with unresolved variables "
                   "(expected an `if (it.unset.length) { ...; continue; }` guard before the PATCH)")
    return bad


def overrides():
    if not BLUEPRINT.exists():
        return {}
    blk = BLUEPRINT.read_text(encoding="utf-8", errors="replace")
    if "credential_overrides:" not in blk:
        return {}
    blk = blk.split("credential_overrides:", 1)[1]
    out = {}
    for m in ENTRY_RE.finditer(blk):
        cid, spec = m.group(1), m.group(2)
        try:
            name = json.loads(spec).get("name", cid)
        except Exception:
            name = cid
        out[cid] = (name, sorted(set(VAR_RE.findall(spec))))
    return out


def check_env_ex():
    """Assertion 2 — every referenced var is declared in the committed template."""
    if not ENV_EX.exists():
        return []
    declared = set(re.findall(r"^([A-Z0-9_]+)=", ENV_EX.read_text(encoding="utf-8",
                                                                  errors="replace"), re.M))
    bad = []
    for cid, (name, vars_) in sorted(overrides().items()):
        for v in vars_:
            if v not in declared:
                bad.append((cid, name, v))
    return bad


def self_test():
    """The gate must FAIL the pre-fix resolver and PASS the current one."""
    pre_fix = (
        'log "Reseeding env-driven credentials from .env (credential_overrides)..."\n'
        "docker exec node -e '\n"
        '  const data={};\n'
        '  for(const [k,v] of Object.entries(spec.data||{})) '
        'data[k]=(typeof v==="string")?v.replace(/x/g,(_,n)=>process.env[n]!==undefined?'
        'process.env[n]:""):v;\n'
        '  for(const it of items){ await req("/rest/credentials/"+it.id,"PATCH",it); }\n'
        "'\n")
    results = []
    pre = check_guard(pre_fix)
    results.append(("pre-fix resolver is rejected", bool(pre)))
    cur = check_guard(HOOK.read_text(encoding="utf-8", errors="replace"))
    results.append(("current hook passes the guard check", not cur))
    results.append(("reseed block is locatable in the live hook",
                    reseed_js(HOOK.read_text(encoding="utf-8", errors="replace")) is not None))
    results.append(("overrides parse from the blueprint", len(overrides()) > 0))
    results.append((".env.ex is readable", ENV_EX.exists()))
    ok = 0
    for label, passed in results:
        print(f"    [{'ok' if passed else 'FAIL'}] {label}")
        ok += bool(passed)
    print(f"G63 self-test {ok}/{len(results)}")
    if cur:
        for b in cur:
            print(f"      current-hook finding: {b}")
    return 0 if ok == len(results) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    if not HOOK.exists():
        print("G63 FAIL — apps/n8n/hooks/push not found.")
        return 1

    guard = check_guard(HOOK.read_text(encoding="utf-8", errors="replace"))
    undeclared = check_env_ex()

    if guard or undeclared:
        print("G63 FAIL — a push could blank a live credential.")
        if guard:
            print("\n  The reseed guard (push step 1.5) is not intact:")
            for b in guard:
                print(f"    - {b}")
            print("\n  An unset/empty ${VAR} must SKIP the credential, not PATCH \"\" over it.")
        if undeclared:
            print(f"\n  {len(undeclared)} credential_overrides variable(s) are not declared in .env.ex,")
            print("  so on a fresh clone they resolve to empty:")
            for cid, name, v in undeclared:
                print(f"    - {v:<28} ({cid}  {name})")
            print("\n  Declare each in .env.ex (an empty value is fine — the push now skips those).")
        return 1

    n = len(overrides())
    print(f"G63 PASS — reseed skips unresolved vars; all {n} credential_overrides entries "
          f"reference only .env.ex-declared variables.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
