#!/usr/bin/env python3
"""run-gates — the sanctioned way to run gates on this repo, because `$?` lies here.

    python3 scripts/refactor/run-gates.py                 # the n8n/blueprint gate set
    python3 scripts/refactor/run-gates.py --all           # every gate in scripts/refactor/
    python3 scripts/refactor/run-gates.py G44 app-tag-lint  # by number or by script stem
    python3 scripts/refactor/run-gates.py --self-test     # prove the harness itself

WHY THIS EXISTS — a verification tool that reports false green is worse than no tool.

On the Windows-host/WSL setup this repo is developed on, the exit status of a command run
through `wsl.exe bash -lc '...'` is **not reliably propagated back to the caller**. Measured
on 2026-08-06, same host, same shell:

    wsl bash -lc 'exit 7'            -> rc=7   correct
    wsl bash -lc 'false; echo $?'    -> 0      WRONG
    wsl bash -lc 'python3 scripts/refactor/dead-activation-lint.py; echo "rc=$?"'
                                     -> prints the full G44 FAIL report, then `rc=` (empty)

So the idiom every agent reaches for first — run the gate, read `$?`, report PASS — reports
**PASS on a gate that just printed its own failure**. This is the repo's dominant defect class
(an operation reporting success while doing nothing) reproduced inside the tooling meant to
catch it. One agent reported five gates green this way and had to re-verify all five.

The fix is not a shell idiom. It is: never ask the shell for the status. This harness runs each
gate with `subprocess.run(...)` in-process and reads `CompletedProcess.returncode`, which is the
real waitpid status and cannot be lost by an intervening shell. `--self-test` proves that on this
host by running a known-exit-3 child.

DO NOT write a fourth version of this. If a gate needs different arguments, add it to GATE_ARGS.

Exit status of this script: 0 only if every gate it ran returned 0. Gates listed in KNOWN_RED
are still run and still reported, but do not by themselves fail the harness -- they are the
gates GATES.md documents as deliberately-wired-while-failing. `--strict` ignores KNOWN_RED and
demands everything be green.
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import re
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE_DIR = REPO / "scripts" / "refactor"

# Gates that touch n8n blueprints / workflow wiring — the default set, cheap and static.
N8N_SET = [
    "dead-activation-lint",
    "dangling-workflow-ref-lint",
    "trigger-schema-drift-lint",
    "switch-fallback-lint",
    "driver-dispatch-drift-lint",
    "workflow-input-lint",
    "app-tag-lint",
    "noop-success-lint",
    "n8n-loop-order-lint",
    "legacy-ref-lint",
    # G42 direct-db-write-lint / G43 single-identity-lint RETIRED 2026-08-07 — they mandated
    # `indoxDataGateway01` / `indoxIdentity01`, an agent-invented design the owner rejected and
    # which was disarmed. See GATES.md.
    "drive-connection-lint",
    "source-id-lint",
    "tenancy-lint",
    "fixture-live-key-lint",
    "value-domain-lint",         # G54
    "endpoint-credential-lint",  # G55
    "fixture-delete-scope-lint", # G58
    "dead-fallback-lint",        # G59
    "one-branch-guard-lint",   # G60
    "mail-connection-lint",      # G62 — FOUND UNWIRED 2026-08-09. The gate existed, self-tested
                                 #       and was named by no runner at all — the exact defect
                                 #       G61's comment above describes, sitting in the same
                                 #       directory. KNOWN FAILING and NOT added to
                                 #       gates.sh/ci-verify.yml: reddening the required lanes is
                                 #       the owner's call. Here it is at least visible and runnable.
    "profile-passthrough-lint",  # G57/G31 — FOUND UNWIRED 2026-08-09 by unwired_gates(), the last
                                 #       one left. GREEN as measured the same day (5 profiles, 7
                                 #       knobs, 270 vars), static, no stack — so there was no
                                 #       reason for it to be unwired beyond nobody having added the
                                 #       line. Wiring a green gate costs one run and removes the
                                 #       only remaining check in this directory whose evidence was
                                 #       an absence.
    "credential-blank-lint",     # G63 — a push must never PATCH an empty secret over a live
                                 #       credential. Static: reads the hook + blueprint + .env.ex,
                                 #       never the untracked .env and never the stack.
    "test-registry-scope-lint",  # G64 — a test may only drive its OWN registry, bound to a LOCAL
                                 #       connection. Landed GREEN 2026-08-09 together with the
                                 #       three blueprint fixes it describes, and proven by
                                 #       re-introducing the real defect into the real file
                                 #       (sv3Inject3x001's live-registry read + conditional
                                 #       spread), watching it fail naming both nodes, then
                                 #       restoring to a byte-identical sha256.
    "open-destructive-webhook-lint",  # G67 - written 2026-08-24 and, in the exact mistake the
                                 #       LIVE_SET comment below describes, left wired into
                                 #       NOTHING for a day. Caught by this harness's own
                                 #       unwired_gates() check, which is the second time that
                                 #       check has earned its place. Static: it walks the
                                 #       executeWorkflow graph in the blueprints and needs no
                                 #       stack. It is KNOWN_RED, see below.
    "shipped-tenant-data-lint", # G56 - measured GREEN (206 hits, all within the 206-hit
                                #       baseline). Its GATES.md row claimed lanes "ci,
                                #       fresh" while NO runner invoked it - a promise in
                                #       the file that nothing kept, found by unwired_gates().
    "app-coupling-lint",        # G33 (by its own docstring) - an app may not name another app's
                                #       id in code; waivers live in platform/app-coupling-waivers.yaml.
                                #       Written 2026-08-12, wired 2026-09-03: found by unwired_gates()
                                #       and RED on arrival (console→chat, data-management→indox/n8n),
                                #       so it is KNOWN_RED below rather than silently green.
    "decide-lane-reachability-lint",  # (no number yet) - every Action Router lane must have a decide
                                #       that returns it, and every decide return must have a lane.
                                #       Written 2026-08-30, wired 2026-09-03, RED on arrival: 10 router
                                #       lanes no decide feeds (11 before source_feedback, fed by a
                                #       concatenated name, was exempted with its executed proof).
                                #       Those are the nodes a 100%-coverage run
                                #       can never touch, which is why the gate is wired the same day
                                #       the coverage bar was raised; KNOWN_RED until each lane is
                                #       removed or its decide branch restored (owner's call per lane).
    "rules-lib-parity-lint",    # G71 - the mail organizer's browser-side rule evaluator
                                #       (mailview/static/rules-lib.js) must be byte-identical
                                #       to the engine's (mailLabelEngine01) helper and builder
                                #       regions, so the preview a user sees is the verdict the
                                #       engine will reach. Static: reads two files. Wired the
                                #       day it was written (2026-09-03) - unwired_gates() named
                                #       it within the hour, which is the harness doing its job.
    "identity-header-lint",     # G86 - the consumers of the `X-authentik-*` identity-header family,
                                #       enumerated MECHANICALLY (file:line, and the file count it
                                #       scanned) and checked against the manifests that declare them.
                                #       Written 2026-10-09 as step 0 of `core-006` (authentik -> a Go
                                #       forward-auth): the survey behind that note counted 10 runtime
                                #       consumers where the `identity` capability graph admitted 3.
                                #       Static and office-free: no network, no stack, ~1 s. GREEN with
                                #       five documented waivers; `--strict` names them.
    "exposure-lint",            # G84 - what reaches a HOST interface, from the compose files alone:
                                #       a port published on 0.0.0.0 (the doc's one front door is 80/443;
                                #       a debug port goes on 127.0.0.1), an engine socket held read-write
                                #       where `:ro` would do, and `privileged` / a root override of a
                                #       Dockerfile's own USER. Wired the day it was written (2026-10-09),
                                #       because `unwired_gates()` had named every gate that was not.
                                #       Static and office-free; the pentest behind `rap-009` measured
                                #       the same facts live (traefik publishing 6379/15432 on 0.0.0.0,
                                #       the socket read-write in six containers) and this is the half a
                                #       NEXT COMMIT meets. GREEN with 5 known red + 8 justified, each
                                #       named with its reason on every run; `--strict` fails on all 13.
    "link-write-guard-lint",    # G85 - AGENTS.md rule 8's enumerator for the routes of the app plane
                                #       that write THIS office's state, asked whether each refuses a
                                #       caller that arrived over a link. §9 of the pairing contract
                                #       says a request that crossed a link cannot write this office's
                                #       own state, and named the class; measured 2026-10-09 (DGO-49)
                                #       EIGHT of its routes answered a linked caller (enable without
                                #       `restore`, disable, archive, unarchive, uninstall, move,
                                #       catalog/install, POST /api/reconcile) while the §9 tests asked
                                #       about two. Routes are read from the file with `ast`, the class
                                #       is computed (a call-graph walk to the write sinks, plus every
                                #       write verb), and an exemption is a written justification that
                                #       FAILS when stale. Static and office-free, ~1 s.
]

# Gates that REQUIRE A LIVE STACK. They are not in N8N_SET because a stackless lane would fail
# them by design — and, correctly, they refuse to pass when they cannot reach the thing they
# check, so they cannot be run speculatively either.
#
# THIS LIST EXISTS BECAUSE ITS ABSENCE WAS THE BUG. `published-drift-lint` (G61) was written,
# self-tested 5/5, argued out of the static set for good reasons — and then wired into nothing at
# all. A gate that exists, passes its own self-test and is never invoked is exactly the defect
# class this repo spent 2026-08-07 cataloguing, reproduced inside the tooling built to catch it.
# `--live` is its home; `unwired_gates()` below is what stops the next one.
#
# ...AND A LIST IS NOT A CALLER. For six weeks nothing invoked `--live` either: every gate here
# counted as wired, and none of them ran unless somebody typed it. `bbox baseline` runs this lane
# as `P3 live-gates` since 2026-10-07 — the day two of the five turned out to be looking at
# nothing where they did run (a ported office, an office without indox).
LIVE_SET = [
    "published-drift-lint",      # G61 — draft vs published body; needs the n8n database
    "declared-host-routing-lint", # G70 — a hostname .env DECLARES must have a router. The
                                 #       failure it catches comes up GREEN: traefik healthy,
                                 #       console router fine, then a bare 404 from authentik at
                                 #       first login because its outpost matches providers by
                                 #       external_host. Live-only: it reads docker labels.
                                 #       Also asked by `bbox run` at the end of a whole-stack
                                 #       bring-up (--quiet, said not fatal).
    "declared-db-objects-lint",  # G69 — every object a tracked .sql DECLARES must EXIST after
                                 #       onboard. dashboard-stats-schema.sql declared two tables
                                 #       and a trigger function that NOTHING applied, so no fresh
                                 #       deploy ever had them and the INDOX dashboard 404d out of
                                 #       the box. Live-only by nature: the question is what the
                                 #       DATABASE contains, which a stackless lane cannot answer.
    "dock-fit-lint",             # Dock capacity (no number yet) — the desktop dock's row is a function
                                 #       of the VIEWPORT, not of how many apps exist
                                 #       (issues/console-desktop-dock-overflows-its-pill-and-hides-17-
                                 #       apps.yaml: 17 of 40 tiles were unreachable by pointer). Static
                                 #       invariants + the arithmetic test always; the rendered
                                 #       measurement at 1294/1440/1920 when a console answers.
                                 #       WIRED 2026-10-05 IN WARN MODE for one release (design doc §8.5,
                                 #       AGENTS.md's staged rollout): GATE_ARGS passes --live --warn, so a
                                 #       failed measurement is printed and exits 0. The flip is removing
                                 #       --warn from GATE_ARGS, and nothing else.
    "env-drift-lint",            # G68 — containers created BEFORE the current .env are running on
                                 #       stale config. Needs docker: it inspects each container's
                                 #       baked env, so a stackless lane has nothing to inspect and
                                 #       it refuses to pass rather than reporting green over zero.
                                 #       Wired here on the day it was written, because the comment
                                 #       above this list is about exactly the mistake of not doing
                                 #       so. Found a live defect on its first run: connections
                                 #       still carried CONSOLE_BASE_URL=console2.localhost while
                                 #       .env said console3, so it built links to a host that no
                                 #       longer existed.
    "plane-tests-lint",          # G72 — here with --in-images (LIVE_ARGS): the static lane runs the
                                 #       tests this machine can run; an OFFICE also has the images,
                                 #       so a test that needs its app's packages (the console's 17,
                                 #       data-management's pull) is run in a throwaway container of
                                 #       that image — 16 of 46 files were run by no lane at all.
    "desktop-windows-lint",      # G81 — here with --live (LIVE_ARGS): flow-qa's `windows` suite (every
                                 #       screen in desktop mode's window, as opened and at its smallest,
                                 #       photographed) and `connect` are RUN against the office. A suite
                                 #       is run by whoever remembers it: `connect` was red for a day.
]

# What a gate is given in the live lane ON TOP of GATE_ARGS: the same script asked the question
# only an office can answer.
LIVE_ARGS = {
    "plane-tests-lint": ["--in-images"],
    "desktop-windows-lint": ["--live"],
}

# Extra flags a gate needs, mirroring how ci-verify.yml invokes it.
GATE_ARGS = {
    "dock-fit-lint": ["--live", "--warn"],
    "ownership-lint": ["--strict"],
    "layering-lint": ["--strict"],
    "blueprint-dep-lint": ["--strict"],
    "capability-use-lint": ["--strict"],
}

# Documented in GATES.md as "KNOWN FAILING ... wired anyway". Reported, not counted as a
# regression. Anything NOT on this list going red is a regression this harness must catch.
KNOWN_RED = {
    # G9 layering-lint sat here for a few hours on 2026-10-07 (5 findings under --strict, which
    # scripts/ci/gates.sh had not been passing). The reason written then — "INDOX extractors parked
    # in the central blueprint; move them to apps/indox on an office that runs INDOX" — did not
    # survive investigation, which is what this roster demands: the five were RETIRED extractors
    # that nothing calls, brought back into the base by `pull all` from instances that still held
    # them. They left with apps/n8n/retired-workflows.txt and G9 is green.
    # G42/G43 were here and are RETIRED, not merely un-listed: a gate whose premise was deleted
    # does not belong on a "known red" roster either. Keeping them here would have preserved the
    # exact thing that made them harmful — a permanent red nobody can act on.
    # G45 n8n-loop-order-lint was here and is now GREEN — removed 2026-08-07, deliberately.
    # Its 3 "known red" findings were not cosmetic: 1 was a live defect (mailLabelEngine01 took
    # 12m28s for 10 items because the loop drained before its work lane ever ran), 1 was in dead
    # code, and 1 was a FALSE POSITIVE the gate itself was manufacturing by comparing targets
    # across mutually-exclusive output indices. Sitting on this roster is what let a real
    # user-visible bug read as background noise for weeks. A gate parked here must have a reason
    # that survives someone actually investigating it — these did not.
    # G67 reports 9 reachability findings across 4 unauthenticated webhook paths. It is red
    # because the finding is REAL, not because the gate is wrong: /webhook/indox-manage takes no
    # authentication and its Action switch routes RESET into IndoxResetFull01, whose 'Clear Table'
    # empties public.incoming_documents — a table whose production baseline is ~39,000 client
    # documents. Exactly one of the nine is proven routable end to end; the rest are an
    # over-approximation the gate's own docstring labels as such.
    #
    # It stays red deliberately, and the reason survives investigation (which is what this roster
    # demands): closing it is a PAIRED change. Setting `authentication` on the webhook breaks every
    # caller that does not send the credential, and the BFF's _svc_call sends none today — so the
    # webhook and the BFF must move together. Whether that ships before release also depends on
    # whether the VPS is reachable from outside, which is an owner decision still open at the time
    # of writing. Un-park this the moment that answer lands; do not let it become background noise,
    # which is the failure mode this roster's own comment above warns about.
    "open-destructive-webhook-lint",
    "swallowed-subcall-lint",    # G53 — 22 sub-calls whose failure nothing reads. Each needs its
                                 #       owner's verdict (deliberate fire-and-forget, or a failure
                                 #       nobody has ever seen); seeding 22 invented reasons to make
                                 #       it green would be the false-clean it exists to prevent.
    "dead-fallback-lint",        # G59 — 1 finding, and it is the one the gate was written for:
                                 #       syncV3Deliver0001's `Proj Kind` gmail fallback, with
                                 #       `Label Req` behind it, is unreachable because every
                                 #       inbound already requires src_kind=='drive'. Real dead
                                 #       code; deleting it is another lane's call, and the
                                 #       finding is the gate working, not a regression.
    "mail-connection-lint",      # G62 — 3 n8n call sites as read on 2026-10-07. From 2026-08-16
                                 #       until then its n8n half globbed `*.json`, scanned zero
                                 #       workflows, and this gate PASSED while sitting on this
                                 #       roster — a known red that went green with nobody fixing
                                 #       it, and nobody asking why. The history, as written then:
                                 #       13 n8n call sites with no explicit connection_id (was 16
                                 #       before the three `/organizer/settings` FALSE findings were
                                 #       removed 2026-08-09: that route is exempt in the service by
                                 #       design and the gate was demanding an id mailapi does not
                                 #       want). Confirmed LIVE, not theoretical: mailapi's access
                                 #       log returns 404 for a message id with `connection_id=`
                                 #       empty and 200 for the SAME id with an explicit one, and
                                 #       that 404 is a running n8n error class. Fixing it means
                                 #       editing 13 automation call sites plus the `mail-private`
                                 #       registry row (whose declared id has not existed since the
                                 #       local instance was removed) — a push-and-verify job of its
                                 #       own.
                                 #
                                 #       THE PYTHON HALF IS NOW GREEN AND THAT IS A NEW FACT, not a
                                 #       continuation: until 2026-08-09 this gate's Python glob was
                                 #       `apps/*/app/**/*.py`, which matches `apps/indox/app/…` and
                                 #       NOTHING ELSE — 47 of 209 first-party app files. It read
                                 #       green over `apps/mail/mailview/app.py`'s twelve bare
                                 #       canonical-op calls for as long as they existed, and those
                                 #       twelve took the client's mail UI to 500 the moment the
                                 #       service-side guard landed. Re-measured after the glob fix:
                                 #       338 files scanned, the pre-fix mailview reproduces 14
                                 #       findings, the fixed one reproduces 0.
    "one-branch-guard-lint",     # G60 - 1 finding, and it is this gate author's own
                                 #       code: the `else if (Array.isArray(j.ids))` branch
                                 #       kept in indoxV2GDocTest01/Batch Config "so the
                                 #       guard stays total" is dead, because `ids` is a
                                 #       string literal. A genuine finding - whether
                                 #       defensive totality justifies a provably-dead
                                 #       branch is a house-style call, not the gate being
                                 #       wrong. Left red until that is decided.
    "dropped-signal-lint",       # G50 — 2 dropped signals in api/__init__.py's _move_items,
                                 #       owned by another lane. Remove this entry when they land;
                                 #       the gate is green everywhere else in the tree today.
    "app-coupling-lint",         # G33 — 3 cross-app references (console→chat, data-management→
                                 #       indox/n8n), unwaived. Wired 2026-09-03 red rather than
                                 #       left unwired green; each needs a waiver with a reason or
                                 #       a manifest lookup — not this release's scope.
    "decide-lane-reachability-lint",  # 11 dead router lanes + 12 advisory no-lane returns,
                                 #       measured 2026-09-03 the day the gate was wired. Each is an
                                 #       owner decision (remove the lane / restore the branch).
    # G41 switch-fallback-lint and G46 drive-connection-lint were listed KNOWN FAILING in
    # GATES.md but measured GREEN on 2026-08-06 — left off this list so they stay enforced.
    # G44 dead-activation-lint went green the same day (whatsappSendDoc01 deactivated).
    #
    # G83 embed-route-lint is RED DELIBERATELY and it is a MIGRATION, not a wrong gate: the owner
    # asked on 2026-10-12 that the console URL be the state of the office in EVERY app — and, when
    # the first cut asked the apps to carry an office protocol, that it be «בלי סריקות וקוד מורכב»:
    # the console's tail IS the app's own URL (identity, under the app's mount) and the shell reads
    # the frame's own navigations. The mechanism is shipped (console `watchFrameRoute`, measured in
    # ci-artifacts/route-contract/navigate-probe.py); what is left is the apps whose screens are not
    # in their URL at all — and this gate IS that list (seven the day it was re-aimed, one of them
    # allowed by name). It leaves this roster when the last one routes.
    "embed-route-lint",
}

# Scripts under scripts/refactor/ that are not gates (libraries, generators, self-tests).
# `n8n-position-restore` is a working-tree repair tool, not a gate: it compares against HEAD, so it
# is trivially green on any committed tree and would report nothing useful in CI. The invariant it
# protects is enforced in CI by G45 (`n8n-loop-order-lint`), which reads only the file in front of it.
NOT_A_GATE = {"n8n-layout", "n8n-position-restore",
              "run-gates",
              # A real lint (charset must be in the first bytes of <head>) that is
              # wired into nothing, and GATES.md already says so under "Files in this
              # directory that are NOT gates". Declared here so unwired_gates() stops
              # reporting what the file already admits -- an honest exclusion, not a
              # silenced finding.
              "charset-first-lint",
              # The blueprint READER every gate imports (`from n8n_blueprint import load`). It has
              # a __main__ for ad-hoc inspection, which is what made unwired_gates() list it;
              # a library is not a check.
              "n8n_blueprint",
              # How a gate looks at a running office with a browser (G79, G81): also a library.
              "office_browser"}


def gate_number(stem: str) -> str:
    """Best-effort 'G44' for a gate stem, read from its own docstring (the code is the thing
    that runs — GATES.md defers to the script, see GATES.md's own resolution table)."""
    try:
        head = (GATE_DIR / f"{stem}.py").read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return "?"
    m = re.search(r"\bG(\d{1,2})\b", head)
    return f"G{m.group(1)}" if m else "?"


def declared_number(stem: str) -> str | None:
    """The gate number a script DECLARES, from the FIRST LINE of its module docstring.

    The house form is `\"\"\"<stem> — gate G48: <the claim>.\"\"\"`, and this matches only that:
    `gate G<n>` followed by a colon, on line one of the docstring, parsed with `ast` rather than
    read off the raw text.

    EVERY ONE OF THOSE NARROWINGS IS PAID FOR. The first version of this function scanned the first
    2000 characters of the FILE for `gate G<n>`, and on its first real run it reported three
    collisions of which TWO WERE ITS OWN FALSE POSITIVES: `sso-provider-lint.py` (really G20) was
    credited with G9 because a body comment forty lines down says "gate G9's business, not this
    one's", and a sibling lane's gate was credited with a number it had already renumbered away
    from. A collision report that cannot be trusted is worse than no report, because the next
    person to see one assumes it is noise — which is exactly how the duplicate numbering survived
    this long. Citations live in prose; declarations live on line one with a colon.
    """
    try:
        src = (GATE_DIR / f"{stem}.py").read_text(encoding="utf-8", errors="replace")
        doc = ast.get_docstring(ast.parse(src)) or ""
    except (OSError, SyntaxError):
        return None
    first = doc.strip().splitlines()[0] if doc.strip() else ""
    m = re.search(r"gate\s+G(\d{1,3})\s*:", first)
    return f"G{m.group(1)}" if m else None


def duplicate_numbers() -> dict[str, list[str]]:
    """number -> the >1 gate scripts claiming it.

    WHY THIS IS CHECKED AT ALL. `GATES.md` opens by recording that three numbers were each used
    twice, and resolves them "in favour of whichever script declared the number in its own
    docstring, because the code is the thing that runs". That rule cannot break a tie where BOTH
    scripts declare it — which is the only kind of tie that has actually happened since. On
    2026-08-06 alone: `layer0-lint` and `profile-passthrough-lint` both declare G31; `G49` was
    claimed twice in one session (resolved by renumbering to G50); and two lanes independently took
    G52 and G53 while a third had to move to G54/G55. A duplicated number means "G31 failed" names
    two different gates and a failure cannot be looked up — the registry's whole purpose.

    Reported alongside the gate results rather than instead of them: a harness that refuses to run
    because the numbering is untidy would be its own kind of unhelpful.
    """
    claims: dict[str, list[str]] = {}
    for stem in discover_all():
        n = declared_number(stem)
        if n:
            claims.setdefault(n, []).append(stem)
    return {n: sorted(s) for n, s in claims.items() if len(s) > 1}


def discover_all() -> list[str]:
    return sorted(p.stem for p in GATE_DIR.glob("*.py") if p.stem not in NOT_A_GATE)


def unwired_gates() -> list[str]:
    """Gate scripts that NO runner invokes — not this harness, not ci-verify.yml.

    WHY THIS EXISTS. On 2026-08-07 a reverse-check found five gates present in `GATES.md` but
    absent from every runner. It could not have found `published-drift-lint`, because that gate
    was in NEITHER list — a `GATES.md ⊆ runners` check and its reverse both compare two lists,
    and a script missing from both is invisible to either direction. The only reliable basis is
    the FILESYSTEM: every `*.py` in this directory is either a gate someone runs, or declared
    NOT_A_GATE, or a bug.

    That is the same reasoning as `duplicate_numbers()` — do not trust a list, derive the answer
    from the thing that exists — and the same reasoning this repo applied all day to predicates,
    guards and switch branches. A gate nobody runs is a check whose evidence is an absence.
    """
    ci = ""
    for p in (REPO / ".github" / "workflows").glob("*.yml"):
        try:
            ci += p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    # LIVE_SET counts as wired only while something RUNS this harness with --live: the list was
    # there for six weeks with no caller, and every gate in it read as wired the whole time.
    try:
        live_called = "run-gates.py\" --live" in (REPO / "scripts" / "baseline.sh").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        live_called = False
    wired = set(N8N_SET) | (set(LIVE_SET) if live_called else set()) | set(GATE_ARGS)
    return [s for s in discover_all() if s not in wired and s not in ci]


def run_one(stem: str, live: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE_DIR / f"{stem}.py"), *GATE_ARGS.get(stem, []),
         *(LIVE_ARGS.get(stem, []) if live else [])],
        capture_output=True, text=True, cwd=REPO, encoding="utf-8", errors="replace",
    )


def self_test() -> int:
    """Prove the harness reads a real exit status on THIS host."""
    p = subprocess.run([sys.executable, "-c", "import sys; sys.exit(3)"],
                       capture_output=True, text=True)
    ok = p.returncode == 3
    print(f"  [{'ok ' if ok else 'FAIL'}] subprocess reports a real exit status "
          f"(expected 3, got {p.returncode})")
    print("\nrun-gates self-test: " + ("1/1 passed" if ok else "0/1 passed — "
          "subprocess status is unreliable here too; do not trust any gate result"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("gates", nargs="*", help="gate stems or G-numbers; default = the n8n set")
    ap.add_argument("--all", action="store_true", help="run every gate in scripts/refactor/")
    ap.add_argument("--live", action="store_true",
                    help="run the LIVE_SET — gates that need a running stack")
    ap.add_argument("--strict", action="store_true", help="KNOWN_RED gates count as failures too")
    ap.add_argument("--verbose", "-v", action="store_true", help="print full output of every gate")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()

    if a.self_test:
        return self_test()

    if a.live:
        gates = list(LIVE_SET)
    elif a.all:
        gates = discover_all()
    elif a.gates:
        by_num = {gate_number(s): s for s in discover_all()}
        gates = [by_num.get(g.upper(), g) for g in a.gates]
    else:
        gates = list(N8N_SET)

    missing = [g for g in gates if not (GATE_DIR / f"{g}.py").exists()]
    if missing:
        print(f"no such gate: {', '.join(missing)}")
        return 2

    regressions: list[str] = []
    known: list[str] = []
    for stem in gates:
        p = run_one(stem, a.live)
        out = (p.stdout or "") + (p.stderr or "")
        first = next((ln for ln in out.strip().splitlines() if ln.strip()), "")
        red = p.returncode != 0
        tag = "PASS" if not red else ("FAIL" if (a.strict or stem not in KNOWN_RED) else "red*")
        print(f"{tag:<5} {gate_number(stem):>4}  {stem:<30} rc={p.returncode}  {first[:96]}")
        if a.verbose or (red and tag == "FAIL"):
            for ln in out.strip().splitlines()[1:20]:
                print(f"          | {ln[:150]}")
        if red:
            (known if (stem in KNOWN_RED and not a.strict) else regressions).append(stem)

    dupes = duplicate_numbers()
    unwired = unwired_gates()

    print(f"\n{len(gates)} gate(s) run · {len(regressions)} regression(s) · "
          f"{len(known)} known-red (GATES.md documents these as wired-while-failing)")
    if known:
        print("  known-red: " + ", ".join(f"{gate_number(s)} {s}" for s in known))
    if regressions:
        print("  REGRESSION: " + ", ".join(f"{gate_number(s)} {s}" for s in regressions))
    if dupes:
        print(f"\n  DUPLICATE GATE NUMBER(S) — {len(dupes)}. \"{list(dupes)[0]} failed\" currently "
              f"names more than one gate, so a failure cannot be looked up:")
        for num, stems in sorted(dupes.items()):
            print(f"    {num}: " + ", ".join(f"{s}.py" for s in stems))
        print("    Pick the one that MOVES (prefer the newer / less-referenced), retag its "
              "docstring,\n    its GATES.md row, its ci-verify.yml step and its scripts/ci/gates.sh "
              "comment.\n    Naming the collision is the point: GATES.md's rule — 'whichever script "
              "declared it in\n    its own docstring' — cannot break a tie where both scripts do, "
              "and that is the only\n    kind of tie that has actually happened.")
    if unwired:
        print(f"\n  UNWIRED GATE(S) — {len(unwired)}. These exist in scripts/refactor/ and NO "
              f"runner invokes them:")
        for s in unwired:
            print(f"    {gate_number(s)} {s}.py")
        print("    A gate nobody runs is a check whose evidence is an absence — it passes its own\n"
              "    self-test, reads as green, and has never looked at anything. Add it to N8N_SET,\n"
              "    to LIVE_SET if it needs a stack, to a ci-verify.yml step, or to NOT_A_GATE with\n"
              "    a reason. `published-drift-lint` sat in this state on the day this check was\n"
              "    written, which is why the check derives from the FILESYSTEM rather than from\n"
              "    GATES.md: a script missing from both lists is invisible to a list comparison.")
    return 1 if (regressions or dupes or unwired) else 0


if __name__ == "__main__":
    sys.exit(main())
