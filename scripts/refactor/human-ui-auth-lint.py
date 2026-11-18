#!/usr/bin/env python3
"""human-ui-auth-lint — gate G96: a host that serves a SCREEN to a person is not open to the world.

    python3 scripts/refactor/human-ui-auth-lint.py [<tree>] [--self-test] [--quiet]

WHY THIS EXISTS. `apps/n8n/app.json` declared `{"host": "n8n", "auth": "none", "emit_labels": false}`
and the app carried its own traefik labels, none of which named `authentik@file`. So on every office
the editor, n8n's own sign-in page and `/rest/settings` answered the whole internet: measured
2026-11-09 07:50-08:05 UTC from outside — `https://n8n.exampleu.digital-office.co.il/` and `/signin`
answered `200` (not `302` to the sign-in), `/rest/settings` answered `200` to anyone, and within two
minutes of Exampleu's edge restarting two scanners (93.184.216.47, 93.184.216.48) loaded the editor with
every asset. The same on vps1, the herd's public door. n8n's own password was the only lock left
(DGO-1594).

Every other `emit_labels: false` app — drive, chat, browser42, my-docs, redisinsight, apitools,
any-concurrency, indox, supabase-studio — hand-writes `authentik@file` on its routers. The rule is
therefore not "no app is open" (webhooks, DSN ingestion and a customer's own form must be), it is:
**an app the office shows a PERSON must not declare itself open**. `auth` is the one declaration the
compiler reads, so a manifest that says `none` while its labels say nothing is an app whose gate exists
on no one's review.

WHAT IT READS. Every `apps/*/app.json` and `platform-base/*/app.json` — the manifest is the only thing
the platform reads about an app, so it is the only thing that can lie about a door. YAML/JSON is read
with the standard library; no stack, no `.env`, no docker daemon, ~0.2 s.

THE RULE. A routing entry FAILS when all three hold:
  * `auth` is `"none"` — explicitly. An absent `auth` is `"sso"` by the schema's own default, which is
    the safe answer, and this gate does not re-implement that default as a finding.
  * it surfaces a screen: it carries a `module` block and `module.tile` is not `false`. That is the
    console's own vocabulary — a `module` is "surface this app to a person" and `tile: false` is "this
    app's screen lives in another app" (machine's power card, DGO-890).
  * it names a `host` of its own. An entry with no host (drive's in-network API) is not a door.

WHAT IT IS NOT. It does not judge whether the compose labels match the declaration (G6 asks whether two
routers of one rule disagree, G20 whether an `sso` entry has a provider, G21 whether a declared
middleware exists at all). It does not look at paths: an app that must serve BOTH a screen and a public
endpoint (n8n's `/webhook/`) serves the open half from routers of its own —
n8n's are hand-written labels on its `n8n-webhook` service — and that is the fix this gate's message
asks for, not silence here.

It also does NOT judge a host that carries no console `module` at all. `forward-auth` (the sign-in's
own page) is a screen with no tile; whether a host like it should also sit behind the office's sign-in
is a decision of its own (and G84/the pentest own the exposure question), and inventing it here would
make this gate the author of a policy nobody reviewed. `supabase-studio` and `portainer` (DGO-1762),
once named here, have since declared their screens behind the sign-in.

EXEMPTIONS, each with the reason it is one. An exemption that stops matching FAILS (G31/G84's
anti-rot rule): a list that outlived what it excused is how a gate starts lying.
"""
import argparse
import glob
import json
import os
import pathlib
import sys

# The sentences this gate prints quote hosts AND app names that are Hebrew, and python on Windows
# writes them in the console's codepage — it dies on its own output before it reports anything (G10
# caught exactly that here). A .py that prints to a person carries the remedy in itself.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]

# (app id, host) -> why THAT screen may be open to the internet. Every one of these is a DECISION,
# not a leftover: a host whose callers are not the office's people, or whose gate is the app itself.
# Keyed by the pair and not by the app: an exemption excuses one door, never every door its owner
# opens later (glitchtip's UI would not be covered by an exemption granted for its DSN host).
ALLOWED = {
    ("authentik", "auth"): "the office's sign-in cannot sit behind itself — this host IS the gate "
                           "every other entry in this file is sent to (platform-base/authentik is "
                           "the identity provider).",
    ("examplech-services", "services"): "the app's callers are the business's CUSTOMERS, not the "
                                      "office's people: a quote request is the product, and the "
                                      "office's own staff use the same screen. Gating it with the "
                                      "office sign-in would close the shop.",
    ("examplex", "examplex"): "the app's callers are suppliers and stores, not the office's people (DGO-1837, the owner: a "
                        "supplier «can just open an account and start uploading»); they sign in to Examplex's OWN accounts "
                        "(apps/examplex/accounts.py, the Services way), and an office person's headers are believed from the "
                        "console's proxy only — the office sign-in would shut the market out.",
    ("dgo-cloud", "dgo-cloud"): "the app's callers are DGO Cloud's CUSTOMERS, who sign up, pay and run their office there "
                                "(DGO-1893); they sign in to its OWN accounts (apps/dgo-cloud/accounts.py: a session cookie "
                                "or a Bearer key, no forwarded identity header believed), and its admin is an account "
                                "proven by a verify link, a reset or Google — the office sign-in would close the service.",
    # (glitchtip, glitchtip) was here on the reason that gating the host breaks error reporting. It never did:
    # every DSN is the internal glitchtip:8000 (hooks/push), so its screen is now behind the sign-in (DGO-1729).
}


def screens(entries):
    """[(app_id, host)] — the entries that put a screen on a host of their own."""
    out = []
    for aid, app in entries:
        for r in (app.get("routing") or []):
            if not isinstance(r, dict):
                continue
            if r.get("auth") != "none":
                continue
            m = r.get("module") or {}
            if not m or m.get("tile") is False:
                continue
            if not r.get("host"):
                continue
            out.append((aid, r.get("host")))
    return out


def scan(entries):
    """(findings, stale, counts) over [(app_id, app.json dict)]."""
    read_entries = sum(len(a.get("routing") or []) for _aid, a in entries for a in [a])
    found = screens(entries)
    open_pairs = set(found)
    findings = [(aid, host) for aid, host in found if (aid, host) not in ALLOWED]
    stale = [f"{aid} ({host})" for aid, host in sorted(ALLOWED) if (aid, host) not in open_pairs]
    return findings, stale, (len(entries), read_entries, len(found))


def load(root):
    entries = []
    for pattern in ("apps/*/app.json", "platform-base/*/app.json"):
        for path in sorted(glob.glob(str(root / pattern))):
            try:
                app = json.load(open(path, encoding="utf-8"))
            except Exception as e:                     # noqa: BLE001 — an unreadable manifest is named
                print(f"  ! {os.path.relpath(path, root)}: {e}")
                continue
            entries.append((app.get("id") or pathlib.Path(path).parent.name, app))
    return entries


def report(findings, stale, counts, quiet=False):
    manifests, routes, counted = counts
    if findings:
        print("A HOST THAT SHOWS A PERSON A SCREEN IS OPEN TO THE INTERNET")
        print("-" * 78)
        for aid, host in findings:
            print(f"  {aid:24} host {host!r} declares auth: none")
        print("-" * 78)
        print("  -> the office's sign-in is the declaration, not the labels: set\n"
              '       "auth": "sso",\n'
              '       "sso": { "slug": "<app>", "display_name": "<App>", "default_host": "<app>.localhost",\n'
              '                "base_url_env": "<APP>_BASE_URL", "local_twin": true }\n'
              "     and let the compiler emit the routers (`emit_labels` true, the default). An endpoint\n"
              "     that must stay public (a webhook, a DSN) is served by routers of its OWN — n8n's are\n"
              "     hand-written labels on its `n8n-webhook` service — never the whole host, and never a\n"
              "     `sub_routes` entry (a sub-route inherits the sign-in).\n"
              "     A door whose callers are not the office's people is declared in this gate's ALLOWED,\n"
              "     in one line with its reason.")
    if stale:
        print("EXEMPTIONS THAT NO LONGER MATCH (they excuse nothing — remove them)")
        print("-" * 78)
        for pair in stale:
            print(f"  {pair:32} declares no open screen on that host")
        print("-" * 78)
    if not quiet or findings or stale:
        print(f"\nG96 {'FAIL' if (findings or stale) else 'PASS'} — {counted} screen(s) on their own host, "
              f"{len(findings)} open without a reason, {len(stale)} stale exemption(s); read "
              f"{manifests} manifest(s), {routes} routing entr(y/ies).")
    return 1 if (findings or stale) else 0


def self_test():
    """Prove the rule on synthetic manifests, both ways, and that an empty scan fails."""
    ok = 0

    def check(name, want, entries, want_stale=None):
        nonlocal ok
        findings, stale, _ = scan(entries)
        got = [(a, h) for a, h in findings]
        if got != want or (want_stale is not None and stale != want_stale):
            raise SystemExit(f"self-test FAILED ({name}): findings {got!r} stale {stale!r}, "
                             f"want {want!r} / {want_stale!r}")
        ok += 1

    mod = {"group": "עסק", "icon": "x", "embed": False}
    check("auth none + a tile + a host", [("a", "a")], [("a", {"routing": [
        {"host": "a", "port": 1, "auth": "none", "module": dict(mod)}]})])
    check("tile: true spelled out", [("a", "a")], [("a", {"routing": [
        {"host": "a", "port": 1, "auth": "none", "module": dict(mod, tile=True)}]})])
    check("auth sso", [], [("a", {"routing": [
        {"host": "a", "port": 1, "auth": "sso", "module": dict(mod)}]})])
    check("auth absent — the schema's own default is sso", [], [("a", {"routing": [
        {"host": "a", "port": 1, "module": dict(mod)}]})])
    check("tile: false — the screen lives in another app", [], [("a", {"routing": [
        {"host": "a", "port": 1, "auth": "none", "module": dict(mod, tile=False)}]})])
    check("no module — an API, not a screen", [], [("a", {"routing": [
        {"host": "a", "port": 1, "auth": "none"}]})])
    check("no host — an in-network endpoint", [], [("a", {"routing": [
        {"port": 1, "auth": "none", "module": dict(mod)}]})])
    check("an exempted app is not a finding", [], [("authentik", {"routing": [
        {"host": "auth", "port": 1, "auth": "none", "module": dict(mod)}]})])
    check("…but the exemption covers THAT host, not the app's next screen", [("authentik", "other")],
          [("authentik", {"routing": [{"host": "other", "port": 1, "auth": "none", "module": dict(mod)}]})])
    stale_pairs = [f"{aid} ({host})" for aid, host in sorted(ALLOWED)]
    check("an exemption that stopped matching is stale", [], [("a", {"routing": []})],
          want_stale=stale_pairs)
    check("an empty scan is not a pass", [], [], want_stale=stale_pairs)
    if not ALLOWED:
        raise SystemExit("self-test FAILED: ALLOWED is empty — the gate would pass by explaining nothing")
    ok += 1
    # the real tree: the gate must be able to run against it at all (the denominator is not zero)
    real = load(REPO)
    if len(real) < 10:
        raise SystemExit(f"self-test FAILED: read {len(real)} manifest(s) — that is not this tree")
    ok += 1
    print(f"self-test OK — {ok} checks")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description="G96 — a host that shows a person a screen is not open.")
    ap.add_argument("tree", nargs="?", default=str(REPO),
                    help="a checkout to read (default: this one) — that is how the gate is proven on "
                         "the PRE-fix tree: `git worktree add /tmp/pre <commit>`")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="speak only about findings")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    entries = load(pathlib.Path(a.tree))
    if not entries:
        print("G96 FAIL — no app.json was read; a scan that finds nothing proves nothing.")
        return 1
    findings, stale, counts = scan(entries)
    return report(findings, stale, counts, quiet=a.quiet)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
