#!/usr/bin/env python3
"""test_env_step — a fresh office gets its OWN .env, with its vault key minted (FPG-8, S26).

`debian-install.sh` (run by the engine step, which comes before env) copies `.env.ex` to `.env`, so
step_env used to find a file on every fresh machine, never ran `ci-env.sh`, and the office came up on
the template's placeholder secrets and its home domain — measured on fireplace, 2026-10-22. And no
generator minted CONNECTIONS_ROOT_KEY, so compose fell back to CHANGE_ME. These run the two scripts
step_env sends to the machine (`TEMPLATE_CHECK`, `ENV_MERGE`) in a scratch folder.

Run: python3 apps/dgo-extend/tests/test_env_step.py  (inside the app's image, or with its deps)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import converge  # noqa: E402

TEMPLATE = ("COMPANY_SLUG=hacohen\nDEPLOYMENT_DOMAIN=${COMPANY_SLUG}.digital-office.co.il\n"
            "POSTGRES_PASSWORD=change-this-postgres\nN8N_ENCRYPTION_KEY=template-n8n-key\n"
            "MAIL_BASE_URL=mail.${DEPLOYMENT_DOMAIN}\n")
FAIL = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def run(script, env_text, mint=None, rename=None, aside=None):
    """(facts printed, .env afterwards) of one of step_env's scripts, run where the files are.
    `rename` = (old, new) domains; `aside` collects the files the script left beside .env."""
    with tempfile.TemporaryDirectory() as d:
        Path(d, ".env.ex").write_text(TEMPLATE)
        Path(d, ".env").write_text(env_text)
        extra = {} if mint is None else {"DGO_MINT": mint}
        if rename:
            extra |= {"DGO_RENAME_FROM": rename[0], "DGO_RENAME_TO": rename[1]}
        out = subprocess.run([sys.executable, "-"], input=script, text=True, capture_output=True,
                             cwd=d, env={**os.environ, **extra}, timeout=30)
        check(out.returncode == 0, f"the script failed: {out.stderr[-400:]}")
        if aside is not None:
            aside.extend((p.name, p.read_text()) for p in Path(d).glob(".env.before-rename-*"))
        return converge.parse_facts(out.stdout), Path(d, ".env").read_text(), out.stdout


def main() -> int:
    copy = run(converge.TEMPLATE_CHECK, TEMPLATE)[0]
    check(copy.get("TEMPLATE") == "1", f"the installer's copy of .env.ex reads as a copy: {copy}")
    normalised = TEMPLATE.replace("mail.${DEPLOYMENT_DOMAIN}", "mail.hacohen.digital-office.co.il")
    check(run(converge.TEMPLATE_CHECK, normalised)[0].get("TEMPLATE") == "1",
          "a copy whose URLs an earlier merge normalised is still a copy")
    generated = TEMPLATE.replace("change-this-postgres", "9f1c…random").replace("template-n8n-key", "3ab…random")
    check(run(converge.TEMPLATE_CHECK, generated)[0].get("TEMPLATE") == "0",
          "a generated .env (every secret its own) is never taken for the template")
    half = TEMPLATE.replace("template-n8n-key", "3ab…random")
    check(run(converge.TEMPLATE_CHECK, half)[0].get("TEMPLATE") == "0",
          "one secret changed by hand is an office's file, not the template")

    facts, env, stdout = run(converge.ENV_MERGE, generated, mint="1")
    key = next((ln.split("=", 1)[1] for ln in env.splitlines() if ln.startswith("CONNECTIONS_ROOT_KEY=")), "")
    check(facts.get("MINTED") == "CONNECTIONS_ROOT_KEY" and len(key) >= 40,
          f"a fresh .env gets a minted vault key: {facts.get('MINTED')!r}, length {len(key)}")
    check(key and key not in stdout, "the minted key is never printed")
    facts, env, _ = run(converge.ENV_MERGE, generated, mint="0")
    check(not facts.get("MINTED") and "CONNECTIONS_ROOT_KEY" not in env,
          "an existing office's .env is never given a new vault key (it would lock the vault)")
    # …nor the template's placeholder by the "keys this version needs" step (hos-002): with no line the vault
    # runs under compose's default, and an appended CHANGE_ME would switch its key
    saved = TEMPLATE
    globals()["TEMPLATE"] = saved + "CONNECTIONS_ROOT_KEY=CHANGE_ME\n"
    try:
        facts, env, _ = run(converge.ENV_MERGE, generated, mint="0")
    finally:
        globals()["TEMPLATE"] = saved
    check("CONNECTIONS_ROOT_KEY" not in env and "CONNECTIONS_ROOT_KEY" not in (facts.get("ADDED") or ""),
          "the template's placeholder vault key is never appended to an existing office's .env")
    # …nor the template's identity (release 0.3.0): an office with no DGO_IDENTITY line runs authentik
    # (traefik's compose default), and an appended forward-auth would point its edge at a sign-in it lacks
    globals()["TEMPLATE"] = saved + "DGO_IDENTITY=forward-auth\nA_KEY_THIS_VERSION_NEEDS=1\n"
    try:
        facts, env, _ = run(converge.ENV_MERGE, generated, mint="0")
    finally:
        globals()["TEMPLATE"] = saved
    check("DGO_IDENTITY" not in env and "A_KEY_THIS_VERSION_NEEDS=1" in env,
          "the template's identity is never appended to an existing office's .env; other new keys still are")
    facts, env, _ = run(converge.ENV_MERGE, generated + "CONNECTIONS_ROOT_KEY=CHANGE_ME\n", mint="1")
    check(facts.get("MINTED") == "CONNECTIONS_ROOT_KEY" and "CHANGE_ME" not in env
          and env.count("CONNECTIONS_ROOT_KEY=") == 1, "a placeholder key in a fresh .env is replaced, once")
    facts, env, _ = run(converge.ENV_MERGE, generated + "CONNECTIONS_ROOT_KEY=an-office-own-key-0123456789\n",
                        mint="1")
    check(not facts.get("MINTED") and "an-office-own-key-0123456789" in env, "a real key is kept")
    facts, env, _ = run(converge.ENV_MERGE, generated + "CONNECTIONS_ROOT_KEY=dev-root-key-not-for-production\n",
                        mint="1")
    check(facts.get("MINTED") == "CONNECTIONS_ROOT_KEY" and "dev-root-key" not in env,
          "compose's published default (the repo's spelling) is a placeholder too")
    facts, env, _ = run(converge.ENV_MERGE, generated + "CONNECTIONS_ROOT_KEY=CHANGE_ME # set me\n", mint="1")
    check(facts.get("MINTED") == "CONNECTIONS_ROOT_KEY", "a placeholder followed by a comment is still one")
    facts, env, _ = run(converge.ENV_MERGE, generated + "CONNECTIONS_ROOT_KEY=CHANGE_ME\n"
                        "CONNECTIONS_ROOT_KEY=an-office-own-key-0123456789\n", mint="1")
    check(not facts.get("MINTED") and "an-office-own-key-0123456789" in env,
          "a real key anywhere in the file is kept, even after a placeholder line")

    own = (generated + "MCP_AUTH_TOKEN=CHANGE_ME\nOPENHANDS_JWT_SECRET=change_me_to_random_32_hex_chars\n"
           "OPENAI_API_KEY=CHANGE_ME\nTELEGRAM_BOT_TOKEN=your-telegram-bot-token-here\n"
           "DISPATCHER_TOKEN=a-real-token-0123456789\n")
    facts, env, stdout = run(converge.ENV_MERGE, own, mint="1")
    got = set((facts.get("MINTED") or "").split(","))
    jwt = next((ln.split("=", 1)[1] for ln in env.splitlines() if ln.startswith("OPENHANDS_JWT_SECRET=")), "")
    check({"MCP_AUTH_TOKEN", "OPENHANDS_JWT_SECRET"} <= got and "CHANGE_ME\n" not in env.split("OPENAI_API_KEY=")[0]
          and len(jwt) == 32, f"an own secret the template asks to replace is minted (32 hex where asked): {got}")
    check("OPENAI_API_KEY=CHANGE_ME" in env and "your-telegram-bot-token-here" in env
          and "a-real-token-0123456789" in env and not ({"OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "DISPATCHER_TOKEN"} & got),
          "an outside provider's key and a real value are left as they are")
    check(not run(converge.ENV_MERGE, own, mint="0")[0].get("MINTED"), "…and nothing at all without DGO_MINT")
    facts, env, _ = run(converge.ENV_MERGE, generated + "A_TOKEN=CHANGE_ME\nA_TOKEN=CHANGE_ME\n", mint="1")
    values = [ln.split("=", 1)[1] for ln in env.splitlines() if ln.startswith("A_TOKEN=")]
    check((facts.get("MINTED") or "").split(",").count("A_TOKEN") == 1 and len(values) == 2
          and values[0] == values[1] != "CHANGE_ME",
          f"a key listed twice gets one value on every line: {len(values)} line(s)")

    # FPG-33: an installed office moves to another domain, from exactly the one its .env names
    old, new = "thefireplaceguys.digital-office.co.il", "fpg.digital-office.co.il"
    office_env = (f"DEPLOYMENT_DOMAIN={old}\nCONSOLE_BASE_URL=console.{old}\nAUTH_EXTERNAL_URL=auth.{old}\n"
                  f"PLANE_OWNER_EMAIL=owner@{old}\nN8N_BASE_URL=https://n8n.{old}/\n"
                  f"OTHER_SITE=x{old}\nSITE_URL=https://{old}.example.net/\nDB_PASSWORD=s3cr3t-{new}-like\n"
                  f"# a comment that names {old}\n")
    kept = []
    facts, env, stdout = run(converge.ENV_MERGE, office_env, mint="0", rename=(old, new), aside=kept)
    names = set((facts.get("RENAMED") or "").split(","))
    check(names == {"DEPLOYMENT_DOMAIN", "CONSOLE_BASE_URL", "AUTH_EXTERNAL_URL", "N8N_BASE_URL"},
          f"every host naming the old domain as a whole word, and only those, is renamed: {sorted(names)}")
    check(facts.get("DOMAIN") == new and f"CONSOLE_BASE_URL=console.{new}\n" in env
          and f"N8N_BASE_URL=https://n8n.{new}/\n" in env,
          f"the hosts and the URLs carry the new domain: {facts.get('DOMAIN')}")
    check(f"PLANE_OWNER_EMAIL=owner@{old}\n" in env and facts.get("EMAILS_KEPT") == "PLANE_OWNER_EMAIL",
          f"an account's sign-in address is kept, and named: {facts.get('EMAILS_KEPT')!r}")
    check(".env.rename-tmp" not in stdout, "nothing but the facts is printed")
    check(f"OTHER_SITE=x{old}\n" in env and f"SITE_URL=https://{old}.example.net/\n" in env,
          "a longer name that only contains the old one is left alone")
    check(f"# a comment that names {old}\n" in env and "DB_PASSWORD=s3cr3t-" in env, "comments and secrets are kept")
    check(len(kept) == 1 and kept[0][1] == office_env, "the file before the rename is kept beside it, whole")
    check("s3cr3t" not in stdout and old not in stdout.replace(f"DOMAIN={new}", ""),
          f"only key names are printed: {stdout!r}")
    again = []
    facts, env2, _ = run(converge.ENV_MERGE, env, mint="0", rename=(old, new), aside=again)
    check(not facts.get("RENAMED") and env2 == env and not again, "a second run renames nothing and copies nothing")
    other = office_env.replace(old, "someone-else.example.com")
    facts, env3, _ = run(converge.ENV_MERGE, other, mint="0", rename=(old, new))
    check(not facts.get("RENAMED") and facts.get("DOMAIN") == "someone-else.example.com"
          and all(ln in env3.splitlines() for ln in other.splitlines()),
          "a .env on a third domain is not renamed (step_env then refuses the mismatch)")
    nested = "DEPLOYMENT_DOMAIN=x.co.il\nCONSOLE_BASE_URL=console.staging.x.co.il\n"
    facts, env5, _ = run(converge.ENV_MERGE, nested, mint="0", rename=("x.co.il", "staging.x.co.il"))
    check(not facts.get("RENAMED") and "console.staging.x.co.il\n" in env5,
          "a rename into a subdomain of the old name (or out of one) is not attempted")
    composed = "COMPANY_SLUG=thefireplaceguys\nDEPLOYMENT_DOMAIN=${COMPANY_SLUG}.digital-office.co.il\n" \
               "MAIL_BASE_URL=mail.${DEPLOYMENT_DOMAIN}\n"
    facts, env4, _ = run(converge.ENV_MERGE, composed, mint="0", rename=(old, new))
    check(facts.get("DOMAIN") == new and f"DEPLOYMENT_DOMAIN={new}\n" in env4 and f"MAIL_BASE_URL=mail.{new}" in env4,
          f"a composed domain is written literally, and what it composes follows: {facts.get('DOMAIN')}")

    # every shape of address stays; a URL's userinfo is not an address (the third reader)
    shapes = (f"DEPLOYMENT_DOMAIN={old}\nFROM=noreply@mail.{old}\nDSN=https://u:p@{old}/x\n"
              f"MAILTO=mailto:admin@{old}\nOWNER=admin@${{DEPLOYMENT_DOMAIN}}\nBOTH=https://app.{old},ops@{old}\n")
    facts, env6, _ = run(converge.ENV_MERGE, shapes, mint="0", rename=(old, new))
    got_kept = set((facts.get("EMAILS_KEPT") or "").split(","))
    check(got_kept == {"FROM", "MAILTO", "OWNER", "BOTH"} and f"FROM=noreply@mail.{old}\n" in env6
          and f"MAILTO=mailto:admin@{old}\n" in env6 and f"OWNER=admin@{old}\n" in env6,
          f"addresses stay on the old name, a composed one too, and are named: {sorted(got_kept)}")
    check(f"DSN=https://u:p@{new}/x\n" in env6 and f"BOTH=https://app.{new},ops@{old}\n" in env6,
          "a URL's host moves even after userinfo, and a host beside an address in one value moves alone")

    # a packaged office links .env to its real file: the file is renamed, the link stays a link
    with tempfile.TemporaryDirectory() as d:
        etc = Path(d, "etc")
        etc.mkdir()
        Path(etc, "binaos.env").write_text(office_env)
        os.chmod(Path(etc, "binaos.env"), 0o600)
        Path(d, ".env").symlink_to(Path(etc, "binaos.env"))
        Path(d, ".env.ex").write_text(TEMPLATE)
        Path(etc, "binaos.env.rename-tmp").write_text("a leftover\n")
        out = subprocess.run([sys.executable, "-"], input=converge.ENV_MERGE, text=True, capture_output=True, cwd=d,
                             env={**os.environ, "DGO_MINT": "0", "DGO_RENAME_FROM": old, "DGO_RENAME_TO": new}, timeout=30)
        real = Path(etc, "binaos.env")
        check(out.returncode == 0 and Path(d, ".env").is_symlink() and f"CONSOLE_BASE_URL=console.{new}" in real.read_text()
              and (real.stat().st_mode & 0o777) == 0o600 and not Path(etc, "binaos.env.rename-tmp").exists(),
              f"a linked .env: the real file renamed, still 0600, the link kept, the leftover gone: {out.stderr[-300:]}")

    # the office's data decides whether the template copy may be replaced (the second reader, 2026-10-22)
    office = {"id": "fireplace", "path": "/opt/digital-office/fireplace", "machine": "m", "domain": "x.example"}
    seen = []
    real_exec, real_must = converge.exec_on, converge.must
    try:
        converge.exec_on = lambda m, cmd, t=0: seen.append(cmd) or {"code": 0, "stdout": "3\n"}
        check(converge._office_data(office) == 3 and "connections_vault" in seen[-1]
              and "supabase_db_data" in seen[-1] and "|| exit 7" in seen[-1],
              f"the vault and the databases are counted by suffix, and docker's failure is not hidden: {seen[-1:]}")
        for broken in ({"code": 255, "stdout": ""}, {"code": 7, "stdout": ""}, {"code": 0, "stdout": "garbage"}):
            converge.exec_on = lambda m, cmd, t=0, b=broken: b
            try:
                converge._office_data(office)
                check(False, f"an unknown count must stop the step, not read as 0: {broken}")
            except converge.StepFailed:
                pass
        moved = []
        converge.exec_on = lambda m, cmd, t=0: {"code": 0, "stdout": "2\n"}
        converge.must = lambda m, cmd, t, why: moved.append(cmd) or "TEMPLATE=1\n"
        try:
            converge.step_env(office, {}, lambda *_: None)
            check(False, "a template .env over existing data must stop the step")
        except converge.StepFailed:
            check(not any(c.startswith("cd") and " mv .env" in c for c in moved),
                  "…and nothing is moved or regenerated over the data")
        ran = []
        converge.exec_on = lambda m, cmd, t=0: {"code": 1 if cmd.startswith("test -s") else 0, "stdout": "2\n"}
        converge.must = lambda m, cmd, t, why: ran.append(cmd) or ""
        try:
            converge.step_env(office, {}, lambda *_: None)
            check(False, "no .env over existing data must stop the step")
        except converge.StepFailed:
            check(not any("ci-env.sh" in c for c in ran), "…and ci-env.sh never writes new passwords over it")
        # the record's previous domain reaches the machine's script; without one, nothing is renamed
        sent = []
        converge.exec_on = lambda m, cmd, t=0: {"code": 0, "stdout": "2\n"}
        # the first script asked is the template check, the second the merge
        converge.must = lambda m, cmd, t, why: sent.append(cmd) or (
            "TEMPLATE=0\n" if len(sent) == 1 else "DOMAIN=x.example\nRENAMED=A,B\n")
        res = converge.step_env(dict(office, renamed_from="old.example"), {}, lambda *_: None)
        check("DGO_RENAME_FROM=old.example" in sent[-1] and "DGO_RENAME_TO=x.example" in sent[-1]
              and res.get("renamed") == ["A", "B"], f"a renamed office sends both names: {sent[-1][-120:]}")
        sent.clear()
        converge.step_env(office, {}, lambda *_: None)
        check("DGO_RENAME" not in sent[-1], "an office that was never renamed sends no rename")
    finally:
        converge.exec_on, converge.must = real_exec, real_must
    for f in FAIL:
        print("FAIL", f)
    print("PASS test_env_step" if not FAIL else f"{len(FAIL)} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
