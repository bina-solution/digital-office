# ops — the self-hosted runner box

Notes on the `portable-ssd` machine that runs this repo's CI, written down because both problems
below presented as something else entirely and cost real time to trace.

## Jobs write root-owned files, checkout then cannot clean, and every job fails in 0.16s

**Symptom.** Every job across `ci-verify`, `ui-map` and `indox-e2e` fails inside
`actions/checkout@v4` after about 0.16 seconds. 30 consecutive jobs. The commits are fine and the
repo's gates pass locally, so nothing in the PR view explains it.

**What it looks like first.** The workspace contains the source tree but no `.git`, and git says:

```
fatal: not a git repository (or any of the parent directories): .git
```

Resetting the workspace makes exactly ONE job pass, and then it breaks again — which is the clue
that the reset treats a symptom.

**Actual cause.** Jobs here run Docker containers that write into the checkout **as root**:
benchmark output under `legacy/feature-validation`, `__pycache__`, `ci-artifacts`. The runner user
cannot delete those. `actions/checkout` cleans the workspace before fetching, fails part-way through
on the root-owned paths, and leaves a directory with files but no repository. Every job after that
fails the same way. Measured on 2026-07-28: **40 root-owned files**, timestamped inside a job that
had just run.

**The safety net.** The runner's `.env` already sets

```
ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/actions-runner/prejob_fixperms.sh
```

but **that script did not exist**, so the hook ran nothing. [`prejob_fixperms.sh`](prejob_fixperms.sh)
in this directory is that script: before each job it takes ownership of the work folder if anything
is not owned by the runner user, and stays silent otherwise. It needs one narrow sudo rule —
wildcards are not allowed in sudoers command arguments, so it names the work folder exactly:

```
shlomy ALL=(root) NOPASSWD: /usr/bin/chown -R shlomy\:shlomy /opt/actions-runner/_work
```

Validate with `visudo -c -f` BEFORE installing. An unparseable file in `/etc/sudoers.d` makes sudo
refuse to run at all, which on a machine reached only over ssh is a bad place to be.

**The real fix** is for the jobs to stop writing as root — `docker run --user "$(id -u):$(id -g)"`,
or chowning what they produce. The hook only stops one such job from wedging the runner for every
job after it.

**Watch out.** An EMPTY commit does not verify any of this. Both workflows carry a `paths-ignore`
filter, and GitHub skips a workflow when a push changes no files at all — so `git commit
--allow-empty` produces no run and reads as "still broken". Push a real change, or use
`workflow_dispatch`.

**Not the cause, though it looks like one.** `pip install pyyaml` fails on this box with
`error: externally-managed-environment` (Ubuntu 26.04, PEP 668). That is real, and
`scripts/ci/pip-ensure.sh` handles it — but the runner's `.env` already sets
`PIP_BREAK_SYSTEM_PACKAGES=1`, so it was never what failed the jobs. The step list in the worker log
settles it: `setup_job → Pre Job Hook → actions/checkout → complete_job`, and nothing after.

## `ci-watch` leaked one `tail -f` per CI job

**Symptom.** The 4-core box sat at a load average of **282** with 332 runnable processes. An
unrelated Docker stack's healthchecks began flapping, which is how it was noticed.

**Cause.** `/usr/local/bin/ci-watch` — a local "live CI dashboard", not the runner and not a
workflow step — followed the newest per-job worker log like this:

```bash
if [ -n "$l" ] && [ "$l" != "$cur" ]; then
  cur="$l"
  tail -n +1 -f "$l" &        # the previous one is never killed
fi
```

One leaked tail per job, for as long as the dashboard stayed open. After ~20 hours and 329 jobs
there were 185 of them, each spinning about 10% CPU.

**Fix.** [`ci-watch`](ci-watch) in this directory, installed to `/usr/local/bin/ci-watch`. It kills
the previous tail before starting the next, backgrounds `journalctl` and `wait`s on it (bash defers
traps until the foreground command finishes, and `journalctl -f` never finishes, so the cleanup trap
never ran on Ctrl-C), and kills only its own children rather than `kill 0` — which signals the whole
process group and would take the calling shell with it when invoked non-interactively.

Verified across 12 real CI jobs: the tail count stayed flat, load went 282 → 0.87.

## The platform and CI can share this machine, except for ports

A BinaOS install here runs a PRIVATE engine — its own socket, data-root, bridge, address pool and
containerd namespace — so containers, images, volumes and networks cannot collide with CI's:

```
/var/run/docker.sock      engine 29.1.3   0 containers   74 images    0 volumes
/run/binaos-docker.sock   engine 28.5.2  33 containers   27 images   20 volumes
```

Host **ports** are the exception, and no amount of engine isolation helps: both stacks publish
80/443/5432/6379, so whichever starts second fails to bind. Set `BINAOS_PORT_OFFSET` in
`/etc/binaos/binaos.env` before installing (8000 puts http on 8080, https on 8443).

`packaging/linux/check-coexistence.sh` reports all of the above and names the port conflict
explicitly, rather than implying that separate engines make the two fully independent.
