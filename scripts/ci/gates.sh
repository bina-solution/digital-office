#!/usr/bin/env bash
# gates.sh — run every architecture/hardening gate. THE list lives here.
#
#   scripts/ci/gates.sh            run them all; non-zero if any fails
#   scripts/ci/gates.sh --list     print the gate script names, one per line
#   scripts/ci/gates.sh --verify-ci  assert ci-verify.yml enumerates exactly this list
#
# WHY ONE LIST. The gates were enumerated in two places that had already drifted:
# `.github/workflows/ci-verify.yml` (as named steps) and `scripts/fresh-machine-check.sh` (as a
# for-loop). `scripts/baseline.sh` — the command that calls itself the full-system proof — ran NONE
# of them, so "baseline is green" and "the invariants hold" were unrelated statements. A gate that
# some lanes run is a gate you cannot reason about.
#
# CI still declares one STEP per gate, because a named step is what turns a failure into a
# readable check rather than one red blob. That enumeration is now checked against this list by
# --verify-ci, so the two cannot drift apart silently.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}" || exit 1

# The gates, in the order a failure is most likely to explain the others.
GATES=(
  ownership-lint            # G5   nothing lives outside apps/
  compose-invocation-lint   # G7   compose carries the compiled -f list
  layering-lint             # G9   platform-base never names an app
  layer0-lint               # G31  the CLI carries no app logic; hooks are executable
  engine-bypass-lint        # G32  no bare `docker compose`, no host docker.sock
  state-writer-lint         # G33  one writer of platform.state.yaml
  legacy-ref-lint           # G34  every reference into legacy/ is declared
  browser42-site-neutrality-lint # G35 incident fixtures stay out of generic Browser42 surfaces
  portability-lint          # G10  host paths survive Linux/Windows/macOS
  registry-drift-lint       # G8   no registry advertises an uninstallable app
  compile-lint              # G12  every first-party python parses, and compiles without a warning
  blueprint-dep-lint        # G13  automations imply the automation engine
  image-pin-lint            # G15  every third-party image is pinned
  route-claim-lint          # G21  routed hosts declared, routers namespaced
  profile-gate-lint         # G22  no app hides services behind a compose profile
  gallery-default-lint      # G23  gallery apps ship disabled
  external-resource-lint    # G24  external resources are ones we provide
  data-volumes-lint         # G26  data.volumes matches what compose creates
  fresh-clone-lint          # G11  a fresh clone has everything tracked files need
  healthcheck-lint          # G18  healthchecks use binaries the image has
  workflow-input-lint       # G19  no sub-workflow call passes null
  tenancy-lint              # G28  every tenant-table access names its instance
  capability-use-lint       # G25  a declared capability is consumed
  memory-budget-lint        # G30  declared memory fits the profile's machine
  paginated-list-lint       # G36  a provider list call paginates or is explicitly bounded
  source-id-lint            # G37  SOURCE_ID is a per-document id, never a folder id or a sender
  dangling-workflow-ref-lint # G38 errorWorkflow / executeWorkflow targets a workflow that exists
  trigger-schema-drift-lint # G39  executeWorkflowTrigger's schema matches the table it upserts
  fixture-live-key-lint     # G40  a demo/QA fixture never carries a live-operational settings key
  switch-fallback-lint      # G41  a rules-mode switch has a fallback, decide/switch case coverage matches
  # G42 (direct-db-write-lint) and G43 (single-identity-lint) were RETIRED 2026-08-07. They
  # required all Postgres access / all identity arithmetic to route through `indoxDataGateway01`
  # and `indoxIdentity01` — two workflows an agent lane invented, that the owner rejected outright
  # ("not part of the existing architecture"), that never executed once, and that were disarmed on
  # 2026-08-07. Two permanently-red gates enforcing a design that does not and will not exist, and
  # a red that can never go green teaches everyone to ignore the list. See GATES.md.
  dead-activation-lint      # G44  an active workflow owns a node n8n can actually activate — KNOWN FAILING, see gate
  n8n-loop-order-lint       # G45  a loop's work lane runs before the loop is re-entered (canvas height IS execution order)
  drive-connection-lint     # G46  every driveApi01/drive canonical-op call site names an explicit profile_id/connection_id — KNOWN FAILING, see gate
  app-tag-lint              # G47  every n8n workflow blueprint carries its owning app's tag
  noop-success-lint         # G48  a skip/no-op never reports success — the reply must name its outcome
  dropped-signal-lint       # G50  a caller never silently discards what the callee told it — KNOWN FAILING, see gate
  node-credential-lint      # G52  a node that cannot work without credentials must declare them
  swallowed-subcall-lint    # G53  a sub-workflow failure turned into data must be read — KNOWN FAILING, see gate
  fixture-delete-scope-lint # G58  an E2E fixture may only delete/update its own rows, and may only
                            #      CREATE rows it can later identify — see the gate's docstring
  # ── Five gates CI has been running that THE list did not name (found 2026-08-07 by the new
  # reverse check in --verify-ci). Each was verified to PASS before being adopted, because adding a
  # red gate to the canonical list would turn `gates.sh` red for every lane rather than fixing
  # anything. G58 is the one that matters: the fixture-cleanup gate written after the incident that
  # deleted 2,432 client documents was absent from every LOCAL "run every gate" path
  # (gates.sh, fresh-machine-check.sh, baseline.sh) while --verify-ci reported "all 40 gates".
  auth-lint                 # G6   no colliding rule mixes protected and unprotected routers
  sso-provider-lint         # G20  every SSO-gated app has an authentik provider
  theme-token-lint          # G27  every bundled copy of the theme tokens matches the source
  stalled-pagination-lint   # G49  an auto-advancing pager can be stopped by its own response
  credential-blank-lint     # G63  a push never PATCHes an empty secret over a live credential
  unread-error-lint         # G66  a failure may not be reduced to a shape that looks like success
  embed-coverage-lint       # G78  the UI map's denominator builds, and every app the shell frames is in it
  dock-fit-lint             # G79  the desktop's dock asks its budget; a window's controls are not pinned ltr (static half)
  undefined-name-lint       # G80  a name a python file reads is a name it binds (the rare branch's NameError)
  desktop-windows-lint      # G81  every screen is looked at in desktop mode's window: the suite, the builder and the short tiers are there (static half)
  palette-lint              # G82  a screen names no colour of its own: the office's one palette, and a count that only falls
  embed-route-lint          # G83  every app the shell frames takes part in the route contract (one address per screen) — MIGRATING, see gate
  plane-tests-lint          # G72  a test that lives beside a plane or an app is run (7 of the planes' 10 and 20 of the apps' 21 ran nowhere)
  manifest-lint             # G73  every app manifest is one the compiler accepts (a refused one stops every render)
  compose-pin-lint          # G74  everyone who runs docker compose runs the same one (three versions among four callers)
  issue-file-lint           # G75  every issue file is one issues/schema.json accepts (62 of 99 were not)
  raw-exception-lint        # G76  a sentence a person reads never carries an exception's class name (57 did)
  screen-words-lint         # G77  a screen says it in words, in the page: no bare status code, no browser dialog, no emoji
  # The two below were steps in ci-verify.yml and absent here, so `--verify-ci` had exited 1 on every
  # branch since they landed — a check that is always red checks nothing. Both pass on a clean clone.
  cpu-budget-lint           # G65  declared CPU caps fit the machine the profile describes
  incoming-documents-writer-lint # G42  who may write public.incoming_documents (re-pointed)
  # ── Two security gates that existed, self-tested and read GREEN, but were in run-gates.py's
  # N8N_SET only — so the unwired_gates() check was satisfied while GitHub's ci-verify.yml never ran
  # them. Found 2026-10-09 by the owner's security completion-audit. Both PASS on a clean clone, so
  # adopting them turns no lane red; now CI enforces them like every other gate.
  endpoint-credential-lint  # G55  every call site of one endpoint agrees on its credential
  open-destructive-webhook-lint # G67  no unauthenticated webhook reaches a client-table DELETE/TRUNCATE
  # ── The enumerator AGENTS.md rule 8 demands, which nothing had. `core-006` replaces authentik with
  # a Go forward-auth, and the `X-authentik-*` family it produces has TEN runtime consumers where the
  # `identity` capability graph admits three (measured 2026-10-09); without this enumeration a swap
  # loses the other seven silently. Static, office-free, ~1 s — GREEN on a clean clone with five
  # documented waivers (readers whose manifests do not declare `identity` yet; `--strict` names them).
  identity-header-lint      # G86  every consumer of the identity-header family is enumerated and declares it
  # ── The static half of the exposure question the pentest behind `rap-009` answered live: what a
  # compose file puts on a HOST interface. The doc is the owner's own exported security session
  # (`ai/context/dgo-security-session.md`, re-sent 2026-10-09), and its first two rules are the ones
  # the pentest found broken — traefik publishing `6379`/`15432` on `0.0.0.0` (Docker's port publish
  # bypasses the host firewall) and the engine socket read-write in six containers. Static,
  # office-free, ~1 s — GREEN on a clean clone with 5 known red + 8 justified exposures, every one
  # named with its reason on every run (`--strict` fails on all 13, and a stale waiver fails always).
  exposure-lint             # G84  nothing reaches a host interface the security session forbids
  # ── Rule 8's enumerator for the mirror question, one layer in: not what a compose file exposes,
  # but which ROUTES of the app plane a linked office can write this office's state through. §9 of
  # the pairing contract says a request that crossed a link cannot write this office's own state and
  # named the class; measured 2026-10-09 (DGO-49) EIGHT of its routes answered a linked caller while
  # the §9 tests asked about two. Static, office-free, ~1 s — GREEN once each of the eight refuses
  # the link, with one written justification (`catalog/preview`, which writes nothing).
  link-write-guard-lint     # G85  every state-writing route of the app plane refuses a linked caller
)

#: Gates that also ship a --self-test. Proving a gate CAN fail is part of running it: a gate only
#: ever observed passing has not been tested (GATES.md, "Adding a gate", step 3).
SELF_TESTED=(image-pin-lint capability-use-lint stalled-pagination-lint unread-error-lint undefined-name-lint desktop-windows-lint palette-lint embed-coverage-lint embed-route-lint route-claim-lint screen-words-lint registry-drift-lint raw-exception-lint issue-file-lint manifest-lint layer0-lint engine-bypass-lint state-writer-lint legacy-ref-lint browser42-site-neutrality-lint paginated-list-lint source-id-lint dangling-workflow-ref-lint trigger-schema-drift-lint fixture-live-key-lint switch-fallback-lint dead-activation-lint n8n-loop-order-lint drive-connection-lint app-tag-lint noop-success-lint dropped-signal-lint node-credential-lint swallowed-subcall-lint fixture-delete-scope-lint credential-blank-lint plane-tests-lint compose-pin-lint endpoint-credential-lint open-destructive-webhook-lint identity-header-lint exposure-lint link-write-guard-lint)

#: Gates CI runs with --strict: the end state, not the scoreboard a migration reads. This runner
#: called every gate bare, so for as long as they had findings G9 (layering) and G25 (capability
#: use) FAILED in ci-verify.yml while `scripts/ci/gates.sh` and `bbox baseline` showed them green —
#: the two lists this file exists to end, one level down. --verify-ci now compares the flags too.
STRICT=(ownership-lint layering-lint blueprint-dep-lint capability-use-lint)

if [ "${1:-}" = "--list" ]; then printf '%s\n' "${GATES[@]}"; exit 0; fi

if [ "${1:-}" = "--verify-ci" ]; then
  wf="${REPO_ROOT}/.github/workflows/ci-verify.yml"
  rc=0
  for g in "${GATES[@]}"; do
    grep -q "refactor/${g}.py" "${wf}" || { echo "  MISSING from ci-verify.yml: ${g}"; rc=1; }
  done
  # ── The registration is only half the fact; the SCRIPT has to be there too. ──────────────────
  # 2026-08-06: G45's `n8n-layout-lint.py` was deleted (deliberately — replaced by
  # n8n-loop-order-lint after the owner ruled node positions are load-bearing) and ci-verify.yml
  # was updated, but scripts/ci/gates.sh still named the dead script in BOTH its GATES list and
  # SELF_TESTED. This check reported **"ci-verify.yml enumerates all 38 gates"** and exited 0 the
  # whole time, because it only ever asked whether the YAML MENTIONED each name — never whether
  # the thing it names exists. Every gate run then died with `can't open file`, which reads as a
  # broken runner rather than a broken registration.
  #
  # That is the same defect this repo keeps finding everywhere else — an operation reporting
  # success while doing nothing — sitting inside the gate whose entire job is to catch drift.
  # A name in a list is not a gate; a file that runs is.
  #
  # Existence is asserted, executability deliberately is NOT: every gate is invoked as
  # `python3 scripts/refactor/<g>.py`, so the exec bit is not load-bearing for these (unlike
  # app hooks, where `run_app_hooks` silently skips a non-executable file). A `[ -x ]` test would
  # also be meaningless on this checkout — /mnt/c reports every file 755 regardless of what git
  # recorded, so it would pass unconditionally and prove nothing. See the project note
  # "verify file modes via git".
  for g in "${GATES[@]}"; do
    [ -f "${REPO_ROOT}/scripts/refactor/${g}.py" ] || {
      echo "  REGISTERED BUT MISSING ON DISK: scripts/refactor/${g}.py"; rc=1; }
  done
  # ── THE OTHER DIRECTION, which was never checked. ────────────────────────────────────────────
  # Everything above asks "is every gate in GATES also in ci-verify.yml?". Nothing asked the
  # reverse, so a gate could run in CI and be absent from THE list — and one was:
  # `fixture-delete-scope-lint` (G58, the fixture-cleanup gate written after the incident that
  # deleted 2,432 client documents) was a named step in ci-verify.yml and missing from GATES here
  # the whole time. That meant `scripts/ci/gates.sh`, `fresh-machine-check.sh` and `baseline.sh` —
  # every local "run every gate" path — silently skipped it, while --verify-ci reported
  # "enumerates all 40 gates" and exited 0. Same shape as the drift this file was written to end,
  # just pointing the other way: a one-directional subset check reads like an equality check.
  for f in "${REPO_ROOT}"/scripts/refactor/*-lint.py; do
    g="$(basename "${f}" .py)"
    grep -q "refactor/${g}.py" "${wf}" || continue          # not run by CI: not this check's business
    # Membership WITHOUT A PIPE. This line used to be
    #     printf '%s\n' "${GATES[@]}" | grep -qx "${g}" || { … rc=1 … }
    # and under this file's own `set -uo pipefail` that is a RACE: `grep -q` exits on its first
    # match, closing the read end, and if `printf` is still writing it takes SIGPIPE — so the
    # PIPELINE reports non-zero on a name that IS in the list. Measured 2026-10-09 on an unchanged
    # tree: 6 false positives in 360 checks at HEAD, 3 in 200 in isolation, and which gate it
    # accuses is timing-dependent — five consecutive `--verify-ci` runs named five different gates
    # (and one of the five runs was green). A registry check that cries drift at random is the
    # drift it exists to catch, one level up. `case` on the joined array is the file's own idiom
    # (see the SELF_TESTED membership test below) and cannot race.
    case " ${GATES[*]} " in
      *" ${g} "*) ;;
      *) echo "  RUN BY CI BUT MISSING FROM THE GATES LIST: ${g}"; rc=1 ;;
    esac
  done
  for g in "${SELF_TESTED[@]}"; do
    [ -f "${REPO_ROOT}/scripts/refactor/${g}.py" ] || {
      echo "  SELF_TESTED BUT MISSING ON DISK: scripts/refactor/${g}.py"; rc=1; }
  done
  # A gate listed as self-tested but absent from GATES would never run at all.
  for g in "${SELF_TESTED[@]}"; do
    case " ${GATES[*]} " in
      *" ${g} "*) ;;
      *) echo "  IN SELF_TESTED BUT NOT IN GATES (never runs): ${g}"; rc=1 ;;
    esac
  done
  # ── HOW a gate is invoked is part of the fact. ───────────────────────────────────────────────
  # Everything above compares NAMES. A gate run without the flag CI gives it is a different, weaker
  # gate under the same name (see STRICT), and a self-test only CI runs is one a local change to
  # the gate never meets: two were. Both flags, both directions — and the third runner, which
  # keeps its own copy of the arguments.
  for g in "${GATES[@]}"; do
    for flag in --strict --self-test; do
      list="${STRICT[*]}"; [ "${flag}" = --self-test ] && list="${SELF_TESTED[*]}"
      here=no; case " ${list} " in *" ${g} "*) here=yes ;; esac
      ci=no; grep -q -- "refactor/${g}\.py ${flag}" "${wf}" && ci=yes
      [ "${here}" = "${ci}" ] || { echo "  ${flag} DISAGREES for ${g}: here=${here}, ci-verify.yml=${ci}"; rc=1; }
    done
  done
  for g in "${STRICT[@]}"; do
    grep -q "\"${g}\": \[\"--strict\"\]" "${REPO_ROOT}/scripts/refactor/run-gates.py" || {
      echo "  --strict HERE BUT NOT IN run-gates.py GATE_ARGS: ${g}"; rc=1; }
  done
  [ "$(grep -c '\["--strict"\]' "${REPO_ROOT}/scripts/refactor/run-gates.py")" = "${#STRICT[@]}" ] || {
    echo "  run-gates.py GATE_ARGS passes --strict to a gate the STRICT list does not name"; rc=1; }
  [ "$rc" = 0 ] && echo "gates: ci-verify.yml enumerates all ${#GATES[@]} gates with the same flags, and every gate + self-test script exists" \
                || echo "gates: registry has drifted (see above)"
  exit "$rc"
fi

fail=0; failed=()
for g in "${SELF_TESTED[@]}"; do
  if ! out=$(python3 "scripts/refactor/${g}.py" --self-test 2>&1); then
    echo "  SELF-TEST FAIL  ${g}"; printf '%s\n' "${out}" | tail -6 | sed 's/^/      /'
    fail=$((fail+1)); failed+=("${g}:self-test")
  else
    printf '  self-test  %s\n' "$(printf '%s' "${out}" | tail -1)"
  fi
done
for g in "${GATES[@]}"; do
  strict=""; case " ${STRICT[*]} " in *" ${g} "*) strict=--strict ;; esac
  if out=$(python3 "scripts/refactor/${g}.py" ${strict} 2>&1); then
    printf '  PASS  %s\n' "${g}"
  else
    printf '  FAIL  %s\n' "${g}"; printf '%s\n' "${out}" | tail -8 | sed 's/^/      /'
    fail=$((fail+1)); failed+=("${g}")
  fi
done

echo
if [ "${fail}" -eq 0 ]; then
  echo "gates: ${#GATES[@]}/${#GATES[@]} PASS (+${#SELF_TESTED[@]} self-tests)"
else
  echo "gates: ${fail} FAILING — ${failed[*]}"
fi
exit "$((fail > 0))"
