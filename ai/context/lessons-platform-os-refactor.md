# What this refactor taught, and the evidence for each

Written 2026-07-30, at the end of the consolidation that produced gates G31–G34, the generic CLI and
the `prepare`/`onboard`/`verify` hook model.

Every entry below is a *failure that reported success*. That is the through-line: none of these were
crashes. Each one produced a green board, a healthy status line, or a clean diff, and was found by
accident or by a gate written afterwards. The repo's convention is that a lesson lives in a comment
next to the code that embodies it — this page exists for the ones that are **cross-cutting**, and
each links to where the detail lives.

---

## 1. A gate cannot see its own blind spot — so state what it does NOT check

**G31** asserts "layer 0 carries no app-specific logic". It reported PASS for the entire refactor
while `bbox` contained `ensure_glitchtip_provisioned()` — a 19-line function, a dedicated
four-service `dc up --wait` phase, and a fallback re-run.

Two independent reasons, both structural:

- It inherited its token set from **G9**, whose rule is "platform-base may not name `apps/`". So its
  tokens were layer-3 only, and the question it actually asked was *"does bbox name an INSTALLABLE
  app?"* when the invariant is *"bbox names NO app"*. glitchtip is layer 2 → invisible.
- It exempted **heredoc bodies wholesale**, because `bbox help` "necessarily" named every command
  group. That premise was true when written and stopped being true the moment help was generated.

**The lesson is not "be more careful."** It is that a gate inherits the scope of whatever it borrows
from, and an exemption encodes a premise that can expire. Both are invisible in a passing run.
→ `scripts/refactor/layer0-lint.py` docstring; release plan F4/G2.2.

## 2. A gate that flags the legitimate pattern gets switched off

The first cut of **G32** (engine/compose bypass) returned **57 findings**, nearly all prose:
docstrings explaining the trap, `bbox reset`'s confirmation message quoting the command it runs, and
— best of all — **gate G7's own PASS message**.

A gate with that signal-to-noise gets disabled within a week, and then the invariant has *no*
enforcement while everyone believes it has some. Tightened to command position only, with heredocs,
docstrings and `docker compose version` (a capability probe, not an invocation) exempt.

Corollary, learned immediately after: **a gate must not treat another gate's test fixtures as the
offence.** G7 began failing on G32's self-test strings. G7 already had an exemption list for exactly
this; G32 joined it. → `scripts/refactor/engine-bypass-lint.py`.

## 3. Depth is part of a script's contract with its location

Hit **twice**, both times silently:

| file | had | after the move | consequence |
|---|---|---|---|
| `extract-gate` | `. "${SELF_DIR}/lib.sh"` | `apps/indox/hooks/lib.sh` | loud failure — the good case |
| `run-suites.sh` | `REPO_ROOT="${SCRIPT_DIR}/.."` | resolved to `legacy/` | **silent** — no `.env`, default deployment name, no container matched, reported "no feature-validation-api" |

The second is the dangerous shape: a wrong path that still *resolves*, to a directory that exists.
Nothing errors; the script simply describes a world that isn't there.

**When moving a file, grep it for `SCRIPT_DIR`, `SELF_DIR`, `dirname`, `../` before anything else.**

## 4. Splitting a file splits its appliers — and nobody checks the remainder

Commit `0f69eb7e` split one fixtures file into three. Exactly one kept an applier:

```
apps/indox/blueprint/fixtures/schema.sql   → applied by the INDOX workflow   ✅
platform-base/n8n/schema/01_platform.sql   → applied by NOTHING              ❌
platform-base/n8n/schema/99_grants.sql     → applied by NOTHING              ❌
```

The refactor was correct in intent (an app owns its own schema) and left two orphans. → §5.

## 5. Atomic rollback makes a partial failure look like total absence

`01_platform.sql` defines `public.touch_updated_at()`. INDOX's `schema.sql:197` attaches a trigger to
it. The n8n Postgres node sends all 26 KB as **one multi-statement query**, which Postgres runs as a
single implicit transaction — so when the trigger failed, the ~100 `create table` statements that had
already succeeded **rolled back with it**.

The symptom was therefore *zero* INDOX tables, not a partial schema — which reads exactly like "the
fixtures file is missing or unmounted". That is the hypothesis I pursued and it was **refuted**: the
file served fine, HTTP 200, byte-identical. **A total absence is evidence of a transaction, not of a
missing file.** → the schema-apply step in `platform-base/n8n/hooks/push` (originally landed in a
separate `hooks/onboard`, later folded into `push` itself so every caller — CLI, app-management,
reconcile — gets it for free instead of needing to remember a second hook).

## 6. "Triggered" is not "done"

`scripts/onboarding` printed *"INDOX Reset + Setup triggered"* and moved on. Triggering returns as
soon as n8n accepts the execution. The workflow then failed (§5), and onboarding declared success on
a deployment with no INDOX schema — after which the scheduled workflows erred every 30 s, **40 errors
to 23 successes**.

An orchestrator must assert the **effect**, not the **call**. `apps/indox/hooks/onboard` now waits
for `public.settings` to exist and says so in red when it does not.

## 7. A verification that cannot fail is not a verification

`run_app_hooks` swallowed every hook's exit code (`bash "${hook}" || say "… (continuing)"`). Correct
for `prepare` — one app's broken bootstrap must not deny every later app its own. **Wrong the moment
a `verify` verb existed**, because the only way a caller could learn of a failure was to capture
stdout and grep for that sentence: a string contract between two files that becomes a lie the first
time someone rewords the message or a hook writes to stderr.

It now **returns a failure count and still never stops early** — two separate promises. Callers
choose: bring-up verbs append `|| true`; `bbox baseline` does not. → `scripts/lib.sh`.

## 8. A value the schema permits but the emitter doesn't implement resolves to the permissive default

`routing[].auth` declared `enum: [sso, none, basic]`. The label emitter attaches authentik's
forwardAuth on an exact `auth == "sso"`. **`basic` was implemented nowhere** — so it fell through and
published the app with *no authentication*, as did `"SSO"`, `"ssoo"`, `"sso "`, `""` and an explicit
`null`, because `validate()` only ever hardcoded two enum checks and every nested enum was decorative.

Two rules fell out: **validate every enum the schema declares, generically** (which closed
`module.group` too), and **a gap between what the schema permits and what the emitter implements must
fail loudly, never resolve to the safe-looking default.** → `platform/manager/reconcile.py`.

## 9. The dev platform's filesystem lies, and production doesn't

`/mnt/c` under WSL reports **every file as mode 755**. So `[ -x ]` is true on the dev machine and
false on Debian, which honours what git recorded.

Seven `hooks/*` files were committed **100644**, including the traefik and portainer `prepare` hooks
written to replace `ensure_acme_perms` and `ensure_portainer_password`. `run_app_hooks` skips a
non-executable file **silently**, so that logic left `bbox` and landed somewhere inert — traefik's
`acme.json` never got its 0600, which makes traefik skip the ACME resolver and serve a self-signed
cert. Every check passed, because every check ran on WSL.

Same family, found later: `digital-office/sim/build.mjs` cannot run under WSL at all — its
`node_modules` holds Windows rollup binaries.

**Ask git, not the filesystem** (`git ls-files -s`), and treat "verified on WSL only" as unverified.
G31 now enforces the mode. → release plan D2/G3.

## 10. An archive README is a claim, and claims rot

`attic/README.md` said nothing referenced it. **Four things did**, and a reader acting on that README
would have broken CI. 293 files stayed alive for one of them.

The fix is not a better README. It is **G34**, which requires every reference into `legacy/` to be
declared with a reason, and **fails on a declared entry that matches nothing** — so retiring a
consumer forces deleting its declaration. Prose cannot ratchet; a gate can.

## 11. Verify a defect the way the system runs it — twice I did not

Two tasks I filed and had to withdraw:

- **"G16 cannot run — no pytest in the app-management image."** I ran pytest *inside the container*.
  CI runs it on the *runner* via `pip-ensure.sh`. 21 tests pass.
- **"baseline curls `<host>.localhost`, which WSL cannot resolve."** True of *my own scratch script*.
  `scripts/baseline.sh` contains no `curl` at all.

Both were real observations attached to the wrong subject. A false task in a plan is worse than a
missing one: someone will spend time on it, and it erodes trust in the entries that are real.

## 12. Two lists of the same thing have already drifted

Every instance found here:

| duplicated | drift that had already happened |
|---|---|
| the gate list (CI steps vs `fresh-machine-check.sh`) | **G22 ran on `fresh` only, never in CI** |
| `CCR_FIRSTPARTY_BUILD` vs services with a `build:` | the hand list omitted `app-management` |
| disposition parsing (×3 in `app.py`) | an app absent from state read **enabled** in the UI and **disabled** to the compiler |
| a cpus-capping script inline in 3 workflows | one copy carried a fix the other two never got |
| the compose `-f` list (`make-runtime-compose.py`) | plus a bare `docker compose`, in the tool that builds the shipped artifact |

The pattern is not that duplication *might* drift. **Every single duplicate found had already
drifted**, and in each case the copies disagreed in the direction nobody was looking.

---

## The shortest version

1. Ask what a gate **cannot** see, and write it in the docstring.
2. A gate with false positives is a gate that gets disabled.
3. Grep for `SCRIPT_DIR`/`../` before moving any file.
4. Assert the **effect**, never the call.
5. Total absence is evidence of a transaction.
6. If it can't fail, it isn't a check.
7. Permitted-but-unimplemented must fail loudly, not default open.
8. WSL's filesystem lies about modes — ask git.
9. Prose can't ratchet; a gate can.
10. Verify a defect the way the system runs it.
