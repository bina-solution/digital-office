# ci-runner — «מריץ CI», the office's GitHub Actions runner

The office's runner for the repository's self-hosted jobs, as an app the owner sees and switches (DGO-1797), not a
service installed by hand on a machine. It runs where an office enables it (the Dell first); it is shipped disabled.

## What it is
- `ci-runner` — the screen, the API and the CLI (`http://ci-runner:8988`), and the one that puts the runner's events
  on the office's stream.
- `ci-runner-agent` — GitHub's runner (version and sha256 pinned in `Dockerfile.agent` as a floor; it updates itself
  when GitHub asks), kept by a small supervisor (`agent.sh`): a heartbeat every 10 s, the listener restarted when it
  ends (every five minutes after three quick failures), a registration placed on the volume taken without a restart.
- Every job passes the office's door first (`prejob.sh`; its header says why each step): it takes the office's ONE
  heavy-job slot (heavy_admit's flock) through `scripts/ops/heavy-hold.sh` — held until `postjob.sh` or the job's
  Runner.Worker ends, at most 2 h — then waits, under the slot, for memory by its class (`classes.yaml`), heat and a
  fresh boot; the desk is said («would wait»), not waited for. One bound (45 min); a refused job gives the slot back.
  Each job is recorded (`record.py` → `/state/jobs.jsonl`).
- The work folder is a host directory mounted at the SAME path (`CI_RUNNER_WORK`): jobs drive the office's engine
  through its socket, and the engine resolves a job's bind mounts on the host. The steps a job runs in the agent are
  bounded by its ceiling (2 cores, 4 GB); what it starts through the socket runs beside it — the slot is what keeps
  one heavy job at a time.

## How to operate it
- `./bbox ci-runner status` — up or not (from the heartbeat: older than a minute is «לא רץ»), the labels GitHub holds
  for this runner, the job running now. `--json` for a program.
- `./bbox ci-runner jobs [n]` — the last job events: who asked, which workflow and commit, how long it waited.
- `./bbox ci-runner queue` — every queued run of the repository on GitHub (needs the office's GitHub token in the
  vault; says so if not).
- `./bbox ci-runner pause` / `resume` — the listener stops BETWEEN jobs: the job running finishes, the next ones stay
  queued on GitHub for another runner with the same labels (the HP's) / it starts again.
- `./bbox ci-runner flow` — the event stream: `job.waiting`, `job.started` with `job.ended` or `job.failed` (refused
  at the door) as one bar on «כל מקביל», `runner.paused`, `runner.resumed`.
- API: `GET /api/status`, `GET /api/jobs?n=`, `GET /api/queue`, `POST /api/pause`, `POST /api/resume`; the writes are
  the app's own CLI's (loopback) for now.

## The job door (package 9; `door.py`'s header has all of it)
A linked office asks for a NAMED job, never a shell: `jobs.json`, argv templates (v1: read-only `bbox` verbs, no
heavy slot, ≤ 300 s). Who: the app's CLI (loopback), or an office listed in `CI_RUNNER_ACCEPT_FROM` (empty = nobody)
whose request the link's door SIGNED — the platform's one verifier, `platform-base/connections/link_identity.py`,
mounted at `/opt/dgo`; an address is never enough here. The server queues; `door.py work` (kept alive by `agent.sh`)
runs one at a time in the office's checkout, in a clean environment and its own process group; each is a bar on
«כל מקביל». `./bbox ci-runner door [<words…>]`; API `/api/door/names`, `/api/door/jobs[/<id>[/log]]`.

## Not yet — said, not hidden
- The desk as a condition (after a week of «would wait» lines, AGENTS rule 8); load never is. A short job (`decide`)
  waits for the slot like a long one. The holder's end on a real job is read from the runner's source (hooks run as
  `bash -e`; the orphan cleanup comes after the completed hook): `postjob.sh` records «given back» on every job.
- `/dev/kvm`: not mounted, so the runner carries the `portable` label only; the `ssd` jobs (Android, export-verify)
  stay with the host's runner until the emulator is an app. The screen warns when GitHub gives this runner `ssd`.
- Its registration: a SECOND registration of the repository, labelled `self-hosted,portable`, placed on the volume
  (`/state/registration`) — an owner's step on the item; the agent only copies what is placed.
- A stop of the agent mid-job loses the job (60 s grace); pause first. A pause from the screen, and asking the job
  door from it, wait for the office's one shared sign-in check (its own item).
- The door's heavy jobs (`gates`, `go-test`, `baseline`, `drill` at a sha), each its own decision. BEFORE ANY OFFICE
  SETS `CI_RUNNER_ACCEPT_FROM`: the vault must stop handing a pair's `dgo_link` secret to any container (its issue,
  the-vault-hands-a-link-s-pair-token-…) — today any container can sign as a linked office; and a job that WRITES
  needs a signature over its method, path and body (v1's covers office, user, time — replayable for 300 s).

## What not to do
- Never print the registration or any token. No office secret is in the agent's environment, and neither are the
  slot's paths: every job step inherits it (a test a job ran once found the office's real slot through it).
- Never start a job's workload on the machine's host by hand: the owner's rule for the Dell is that only the office
  runs there. A job that cannot start waits at the door and says why on the screen.
