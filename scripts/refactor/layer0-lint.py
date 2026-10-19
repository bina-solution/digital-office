#!/usr/bin/env python3
"""layer0-lint — gate G31: the CLI may not carry an app's knowledge.

    python3 scripts/refactor/layer0-lint.py [--strict] [--self-test]

G9 enforces "a base app may never name a layer-3 app" across platform-base/. It never looked at
LAYER 0 — bbox, scripts/lib.sh, scripts/dc — and that is precisely where the layering broke worst
and longest. bbox carried ensure_portainer_password (one gallery app's admin secret, minted on every
run even though the app ships disabled), ensure_acme_perms (traefik's acme.json mode), and lib.sh
carried ccr_warn_browser42, an entire function keyed to one layer-3 app id, in the library every
entry point sources. G9 passed throughout, because it was not looking. A gate that cannot see the
component most likely to accumulate app knowledge is not a gate.

WHAT IS A VIOLATION, and what is emphatically not:

  violation   app-specific LOGIC in the CLI — a secret path, a container name, a workflow id, a
              hand-kept list of app names, a file-naming convention only that app knows.
  fine        DISPATCH into the app's own folder: `bash "${REPO_ROOT}/apps/indox/hooks/test"`.
              That is the CLI delegating, which is the whole design ("an app is a folder; its
              tooling belongs inside it"). The path names the app because it is ADDRESSING it.
  fine        help/usage text and error messages naming a command group.
  fine        comments — including the ones explaining why an app's bootstrap was moved out.

So the rule is narrow on purpose: an app id in a non-comment line that neither addresses that
app's own directory nor is user-facing text.

TWO BLIND SPOTS, closed here (release plan F4 / G2.2). Both hid a real violation for the whole
refactor, and both were found by scanning layer 0 BY HAND — not by this gate, which reported PASS
throughout. That is the same failure mode the file opens with, one level in.

  1. The token set was LAYER 3 ONLY. It came from G9's layer3_tokens(), which reads apps/ and
     nothing else, because G9's rule is "platform-base may not name apps/". Inheriting that scope
     turned G31's question into "does bbox name an INSTALLABLE app?" when the invariant is "bbox
     names NO app". So ensure_glitchtip_provisioned() — 19 lines in bbox, plus a dedicated
     four-service `dc up --wait` phase and a fallback re-run — was invisible, because glitchtip
     lives in platform-base. Enforcing the layering for gallery apps and not for core ones is
     precisely the blind spot G9 had before G31 existed. The tokens now come from apps/ AND
     platform-base/ (see app_tokens).

  2. Heredoc bodies were exempt WHOLESALE. `bbox help` hardcoded `indox reset|demo|sync|test` and
     `b42 dump|load|list`, and passed. The exemption's premise was "the menu necessarily names
     every command group" — which stopped being true when app_help_block() started GENERATING that
     section from <root>/<id>/hooks/*. No app verb is typed into bbox any more, so a verb in a
     heredoc is once again a real finding, and it is the finding that matters most: help text
     enumerating one app's verbs means adding an app requires editing the CLI, which IS the defect.

WHAT A HEREDOC LINE MEANS NOW. `bbox help` is columnar — `<command>   <description>`. Every
instance of the bug was in the COMMAND column, never the description, so only the command column is
scanned: everything up to the first run of two or more spaces. `bbox indox test   run the suites`
fails; the one surviving hit in the tree, `bbox baseline   …→ci-verify→indox test→any-concurrency`,
is an English sentence in the description column saying what the baseline pipeline does, and stays
legal. A heredoc line with no column break is a bare command or plain code, and is scanned whole.
The `n8n` headings in that same heredoc are safe for a different reason: names of four characters
or fewer are not tokens at all (app_tokens), so the gate cannot fire on the word.

THE RATCHET. Known remaining debt is listed in DEBT with the task that closes it. Those lines are
reported but do not fail. Anything NEW fails immediately. This is deliberate: the alternative to a
ratchet is no gate at all until every last item is fixed, which is how the debt accumulated in the
first place. Paying a debt must also DELETE its entry — an entry matching nothing is itself a
failure, so the list cannot rot into a permanent exemption.
"""
import argparse
import importlib.util
import json
import pathlib
import re
import subprocess
import sys

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required")

REPO = pathlib.Path(__file__).resolve().parents[2]
#: `scripts/onboarding` is layer 0 too and was the worst of it — a browser42 restore block, INDOX's
#: two workflow ids, and a third copy of the n8n login-and-run dance. It is orchestration: the ORDER
#: of the phases, and nothing about what any app is.
#:
#: `scripts/remote.py` was ADDED to this list when it landed (DGO-32/37): it is a `bbox` verb's whole
#: implementation, so it is layer 0 by the same argument as the rest — and the two apps it speaks to
#: (the link plane and the credential plane) are addressed the way this gate allows, by their own
#: manifests' paths, with every endpoint read out of them.
LAYER0 = ["bbox", "scripts/lib.sh", "scripts/dc", "scripts/onboarding", "scripts/remote.py"]

# Known debt: (file, substring identifying the line, task id in the release plan).
#
# EMPTY, and that is the point of the ratchet rather than an accident of it. The last two entries
# were the same remaining item — authentik's cold-start special-casing in `bbox run`: a head start
# for its own four services, and a probe of its own postgres volume to choose the wait timeout.
# Both moved into platform-base/authentik/hooks/prepare under G2.3, where the app starts what it
# owns and waits on its own SSO sentinel, so layer 0 now carries no app-specific bring-up logic at
# all. Their entries had to be DELETED and not merely left behind: a substring that matches nothing
# fails this gate, which is what stops the list rotting into a permanent exemption.
#
# Anything added here needs a task id that closes it, and the same obligation to remove it.
DEBT = []


def app_tokens(aliases=None):
    """Every app id and compose service name in the repo; CLI aliases go to `aliases` — apps/ AND platform-base/.

    Blind spot 1 (see module docstring). apps/ still comes from G9's own helper, so the two gates
    can never disagree about what a layer-3 app is; platform-base/ is added on identical terms —
    the id, plus the services its compose declares — rather than by a second, drifting rule.

    The >4-character filter is G9's too, and it is load-bearing here in a way it is not there:
    layer 0 is prose-heavy (a whole help screen), and three- and four-letter ids collide with
    English constantly. It is why `n8n` and `chat` are not tokens, and therefore why `bbox help`
    may keep its `n8n` section heading. A gate that fired on that word would be off within a week.

    `cli.alias` is the one thing exempt from that filter, and it has to be: browser42's alias is
    `b42`, three characters, and `b42 dump|load|list` is HALF of what `bbox help` hardcoded. Catch
    `browser42` but not `b42` and blind spot 2 is only half closed — the gate would have passed the
    exact text it exists to reject. An alias is safe to take unfiltered where a short id is not,
    because it is a token the CLI deliberately reserves rather than a name that happens to be
    short; a collision with English would fail this gate the day it was declared, loudly, in the
    app.json that declared it.
    """
    aliases = {} if aliases is None else aliases
    spec = importlib.util.spec_from_file_location(
        "layering_lint", REPO / "scripts" / "refactor" / "layering-lint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # setdefault throughout: an id declared in both trees stays attributed to the layer-3 app,
    # which is the stricter reading and matches G9's.
    toks = dict(mod.layer3_tokens())
    for root in ("apps", "platform-base"):
        for m in sorted((REPO / root).glob("*/app.json")):
            d = json.loads(m.read_text(encoding="utf-8"))
            alias = (d.get("cli") or {}).get("alias")
            # [2026-08-23] Aliases are collected SEPARATELY and matched only in verb
            # position (see alias_pat in scan). They cannot take the length rule that
            # guards ids: `b42` is three characters and the self-test requires it to be
            # caught in `bbox b42 dump|load|list`. But matched bare they are worse than
            # short ids -- data-management's alias is `data`, so every `data = ...` in
            # layer-0 tooling read as a layer-3 reference. Position is the thing that
            # separates the two, not length.
            if alias:
                aliases.setdefault(alias, d["id"])
            if root == "apps":
                continue                      # ids + services already came from G9's helper
            names = {d["id"]}
            comp = d.get("compose")
            if comp and (m.parent / comp).exists():
                doc = yaml.safe_load((m.parent / comp).read_text(encoding="utf-8")) or {}
                names |= set((doc.get("services") or {}).keys())
            for n in names:
                if len(n) > 4:
                    toks.setdefault(n, d["id"])
    return toks


def is_debt(rel, line):
    return any(rel == f and s in line for f, s, _ in DEBT)


def scan(overrides=None):
    """overrides: {rel: text} — scan this content instead of the file on disk, so --self-test can
    plant a violation without ever touching the real CLI."""
    overrides = overrides or {}
    aliases = {}
    toks = app_tokens(aliases)
    # Boundary is alnum/hyphen, NOT \w — underscore must not shield a name. `portainer_password.txt`
    # is the CLI knowing one gallery app's admin secret; a \w boundary called that a different word
    # and let it through, which is how ensure_portainer_password survived every gate it ran under.
    pat = re.compile(r"(?<![a-zA-Z0-9-])("
                     + "|".join(sorted(map(re.escape, toks), key=len, reverse=True))
                     + r")(?![a-zA-Z0-9-])")
    # A whole-line heading: colour on, words, colour off. Nothing else on the line.
    HEADING = re.compile(r"^\$\{c\d+\}[^$]*\$\{c0\}$")
    # An alias is a VERB, so it only counts where a verb goes: right after `bbox`.
    alias_pat = re.compile(r"(?<![a-zA-Z0-9-])bbox\s+("
                           + "|".join(sorted(map(re.escape, aliases), key=len, reverse=True))
                           + r")(?![a-zA-Z0-9-])") if aliases else None
    heredoc_open = re.compile(r"<<-?\s*(['\"]?)(\w+)\1\s*$")
    # The break between `bbox <command>` and its description in the help screen. Two spaces, because
    # one is a word gap and two is a column.
    column_break = re.compile(r"\s{2,}|\t")
    # A comment that trails code on the same line is still a comment, and the file says comments are
    # fine. Only `#` after whitespace: `${v#*x}` and `sed 's/^#: *//p'` are parameter expansion and a
    # pattern, not commentary. G9 strips the same way, for the same reason — its own fix comment
    # quotes the endpoints it removed, and a gate that reads comments reports the fix as the bug.
    trailing_comment = re.compile(r"(?<=\s)#.*$")
    findings, debt = [], []
    for rel in LAYER0:
        p = REPO / rel
        if rel in overrides:
            text = overrides[rel]
        elif p.exists():
            text = p.read_text(encoding="utf-8")
        else:
            continue
        term = None
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if term is not None:
                if s == term:
                    term = None
                    continue
                # A heredoc body is TEXT handed to a command, not shell code — but it used to be
                # skipped ENTIRELY, and that is how `bbox help` came to hardcode one app's verbs
                # (blind spot 2). Scan the COMMAND column only: `bbox indox test` is a verb someone
                # has to hand-edit when the app changes, while the description beside it is English.
                code = column_break.split(s, 1)[0]
            else:
                m_h = heredoc_open.search(line)
                if m_h:
                    term = m_h.group(2)
                    continue
                code = trailing_comment.sub("", line)
            cs = code.strip()
            if not cs or cs.startswith("#"):
                continue
            # [2026-08-23] A colourised SECTION HEADING is prose, and by construction carries
            # no command: it is the sentence above a group of `bbox <verb>` lines. The gate
            # already argues this case for short ids ("layer 0 is prose-heavy (a whole help
            # screen), and three- and four-letter ids collide with English constantly"), but
            # length does not save a SEVEN-letter id that is also an everyday word:
            #     ${c1}Move this deployment to another machine${c0}
            # was reported as a layer-3 reference to the `machine` app, which that sentence
            # has nothing to do with. Matched on SHAPE rather than exempting one string, so
            # the next heading that happens to contain "drive" or "console" is safe too.
            if HEADING.match(cs):
                continue
            m = pat.search(code)
            if not m and alias_pat is not None:
                am = alias_pat.search(code)
                if am:
                    m = am
            if not m:
                continue
            app = toks.get(m.group(1)) or aliases[m.group(1)]
            # Addressing the app's own tree is delegation, not knowledge.
            if re.search(rf"(apps|platform-base)/{re.escape(app)}/", code):
                continue
            # User-facing text: a usage line, an error, an echo. Naming a command group is not
            # carrying its logic. Tested against `code`, not the raw line: inside a heredoc that is
            # the command column, so the word "echo" in a DESCRIPTION cannot excuse the verb next
            # to it — which is exactly the shape of the help lines this gate now has to catch.
            if re.search(r"\b(die|say|echo|warn|ok|bad|printf)\b", code):
                continue
            # A case label routing to that app's group.
            if re.match(rf"\s*{re.escape(app)}\s*\)", cs) or re.match(r"\s*\w+\|\w+\s*\)", cs):
                continue
            (debt if is_debt(rel, line) else findings).append((rel, i, s[:110], app))
    return findings, debt


def unexecutable_hooks():
    """Hooks git records as non-executable. run_app_hooks skips them with `[ -x ]`, silently.

    This is the other half of the same invariant: moving an app's bootstrap into <id>/hooks/<verb>
    only works if the file actually runs. Seven hooks were committed 100644 — including the
    traefik and portainer `prepare` hooks written to REPLACE ensure_acme_perms and
    ensure_portainer_password. The logic moved out of bbox into files that never executed, so
    traefik's acme.json never got its 0600 and nothing said a word.

    It hid because of where the work was done: on WSL over /mnt/c, every file stats as 755, so
    `[ -x ]` is true on the dev machine and false on the Debian VPS that checks out git's mode.
    Ask git, not the filesystem — git's index is what production gets.
    """
    out = subprocess.run(["git", "ls-files", "-s", "apps/*/hooks/*", "platform-base/*/hooks/*"],
                         cwd=REPO, capture_output=True, text=True)
    bad = []
    for line in out.stdout.splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) == 4 and parts[0] != "100755":
            rel = parts[3].strip()
            # A hooks/ directory holds two kinds of file, and only one of them is a hook.
            # `platform-base/data-management/hooks/_client.py` is a shared module its siblings
            # import ("Shared transport for the `bbox data` verbs"); run_app_hooks would only
            # ever exec it for a verb literally named `_client.py`, which cannot happen. Marking
            # it +x to satisfy this gate would be a lie about what it is.
            #
            # The shebang is the honest discriminator: a file meant to be EXECUTED says so on
            # line 1. Anything with one must carry the bit; anything without is a module.
            try:
                with open(REPO / rel, "rb") as fh:
                    if not fh.read(2) == b"#!":
                        continue
            except OSError:
                pass    # unreadable: report it rather than silently excusing it
            bad.append((rel, parts[0]))
    return bad


#: (label, planted snippet, must this be caught?) — the second half matters as much as the first.
#: A gate that flagged the legitimate patterns would be switched off within a week.
#: A snippet may be several lines, because the two cases that used to slip through only exist
#: INSIDE a heredoc, and a planted line has to be wrapped in one to sit where the bug sat.
SELF_TEST = [
    ("bare loop over an app's containers", '  for c in portainer; do docker rm "$c"; done', True),
    ("an app's secret file",               '  pw="${REPO_ROOT}/data/portainer_password.txt"', True),
    ("an app's container name",            '  N8N_CONTAINER=incoming-documents', True),
    # Blind spot 1. glitchtip is platform-base, and this function — 19 lines of it — sat in bbox
    # through every run of this gate, because the token set stopped at apps/.
    ("a BASE app's provisioning function", '  ensure_glitchtip_provisioned() {', True),
    ("a BASE app's own services, started by name",
                                           '  dc up -d glitchtip-worker glitchtip-migrate', True),
    # Blind spot 2. The first is the shape `bbox help` used to carry (`indox reset|demo|sync|test`);
    # the second is the line still in it, which describes a pipeline rather than offering a verb.
    ("an app verb in a help heredoc",
     '  cat <<EOF\n  bbox glitchtip provision      set up error tracking\n  EOF', True),
    ("an app's ALIAS verb in a help heredoc",
     '  cat <<EOF\n  bbox b42 dump|load|list       browser42 state\n  EOF', True),
    ("a heredoc description column naming what a pipeline runs",
     '  cat <<EOF\n  bbox baseline      reset→build→up→indox test→ui-map→scorecard\n  EOF', False),
    ("dispatch into the app's own tree",   '  bash "${REPO_ROOT}/apps/indox/hooks/test" "$@"', False),
    ("dispatch into a BASE app's own tree",
                                           '  run_hook "platform-base/glitchtip/hooks/prepare"', False),
    ("an error message naming a group",    '  die "bbox indox: unknown subcommand"', False),
    ("a case label routing a group",       '  indox) shift; indox_cmd "$@" ;;', False),
    ("a comment discussing an app",        '  # portainer used to be bootstrapped here', False),
    ("a trailing comment discussing an app",
                                           '  _wt=600     # cold: glitchtip has real work to do', False),
]


def self_test():
    base = (REPO / "bbox").read_text(encoding="utf-8")
    bad = 0
    for label, snippet, should_catch in SELF_TEST:
        found, _ = scan({"bbox": base + "\n" + snippet + "\n"})
        planted = {l.strip()[:110] for l in snippet.splitlines() if l.strip()}
        caught = any(text in planted for _, _, text, _ in found)
        if caught != should_catch:
            bad += 1
        verb = "caught" if caught else "allowed"
        want = "must catch" if should_catch else "must allow"
        print(f"  [{'ok ' if caught == should_catch else 'FAIL'}] {verb:<8} ({want}): {label}")
    print(f"\nG31 self-test: {len(SELF_TEST) - bad}/{len(SELF_TEST)} passed")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="fail on known debt too (the end state, once A4/A9 land)")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the gate catches violations and allows the legitimate patterns")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    findings, debt = scan()

    if debt:
        print(f"G31 known debt ({len(debt)}) — reported, not failing; each has a task:")
        for rel, i, s, app in debt:
            task = next((t for f, sub, t in DEBT if f == rel and sub in s), "?")
            print(f"    {rel}:{i}  [{app}]  {task}")
            print(f"        {s}")

    stale = [(f, s, t) for f, s, t in DEBT
             if not any(rel == f and s in line for rel, _, line, _ in debt)]
    if stale:
        print(f"\nG31 FAIL — {len(stale)} stale DEBT entr(y/ies), matching nothing:")
        for f, s, t in stale:
            print(f"    {f}  '{s}'  ({t})")
        print("\n  Fixed? Delete the entry. Otherwise the substring drifted and the gate")
        print("  silently stopped watching that line.")
        return 1

    nox = unexecutable_hooks()
    if nox:
        print(f"\nG31 FAIL — {len(nox)} hook(s) git records as NON-EXECUTABLE:")
        for path, mode in nox:
            print(f"    {mode}  {path}")
        print("\n  run_app_hooks skips these silently, so the app bootstrap they contain never runs")
        print("  on any machine that honours git's mode (i.e. production). Fix:")
        print("    git update-index --add --chmod=+x <path>")
        return 1

    if findings:
        print(f"\nG31 FAIL — {len(findings)} layer-3 app reference(s) in layer-0 tooling:")
        for rel, i, s, app in findings:
            print(f"    {rel}:{i}  names '{app}'")
            print(f"        {s}")
        print("\n  The CLI must not carry an app's knowledge. Move it to")
        print("  <root>/<id>/hooks/<verb> and let bbox invoke it generically (run_app_hooks),")
        print("  or address the app's own directory instead of restating what it knows.")
        return 1

    if a.strict and debt:
        print("\nG31 FAIL (--strict) — known debt remains.")
        return 1
    print("\nG31 PASS — layer 0 carries no app-specific logic beyond the recorded debt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
