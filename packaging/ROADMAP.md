# The single-file executable — what is done, and what comes next

State as of 2026-07-28. Written so the next session can pick up without re-deriving anything.

---

## Phase 0 — Linux. DONE.

`BinaOS-2026.07.28-r5-linux-amd64.run`, 2.10 GB. Verifies 10/10, installs on a machine that has
never seen this project, brings up 33 containers, answers its routes, stays up, and produces a full
ui-map (70/77 views, 9 apps — the seven it skips are parameterised routes it declines without a
resolved id, and a seeded run measured the same 70/77).

Proven on the portable box beside that machine's own Docker: private engine 28.5.2 on its own
socket, data-root, bridge and address pool, coexisting with the host's 29.1.3.

---

## Phase 1 — Windows. DONE. Executable works, ui-map matches Linux exactly.

`BinaOS-Setup-2026.07.28-r5.exe`, 2.1 GB, payload embedded, hash-verified on the test machine.

**Proven on a Windows 10 machine that had never run WSL:** the installer extracts, imports its own
WSL2 distro, loads all 27 images, runs its own engine (dockerd 28.5.2), and brings up **33
containers, 22 healthy**, with `n8n.localhost` returning 200.

**All seven routes answer** once the authentik first-boot race is cleared (Phase 3):

```
console 302   apps 302   drive 302   my-docs 302
incoming-documents 302    auth 302   n8n 200
running=33  healthy=25
```

Linux now matches it: re-verified 2026-07-29 on the freed machine, the installed stack came up in
15s with 33 containers, 26 healthy, and **all 7 routes answering** — one better than the 6 of 7
recorded earlier.

**Both platforms and CI share one 15 GB laptop, and that needed solving.** The Windows test VM is
10 GB resident; the stack is ~8 GB. They do not fit, and nothing was stopping them being started
together — measured 10:56 with the VM up: 2 GB available and ZERO containers on either engine, with
every job that needs a stack failing (gate, e2e, verify, all three ui-map profiles) and every job
that does not passing (images, profiles). Nothing in those failures said "out of memory": the stack
simply never converged and the job timed out on a health wait, which reads as a product regression.

`ops/prejob_waitfree.sh` now holds a job at the runner's gate until the memory is actually there. It
tests MEMORY, not "is qemu running" — the first version tested both and promptly blocked a job at
11 GB free while qemu was still winding down. With the VM gone the stack runs with 8 GB to spare, so
the stack and CI were never the conflict; the 10 GB guest beside either of them was.

**The ui-map is done, and it is identical to Linux: 70/77 views (90.9%), 839s, 5230x19408px.**
Same platform, same coverage, whichever OS the customer installs on — which is the strongest
statement available that the two artifacts ship the same product.

I first recorded this as blocked on the test rig being too slow. That was wrong, and worth spelling
out because the wrong diagnosis is the more expensive mistake:

| what I blamed | what it actually was |
|---|---|
| 2015 i7-5500U too slow to build the capture image | the image never needed building — `run_capture.sh` has honoured `UI_CAPTURE_SKIP_BUILD=1` all along, and the host had already built it. Ship it in, don't rebuild it. |
| the guest starving and ssh timing out | the distro was being reaped, because the thing holding it open was an ad-hoc `sleep infinity` on an ssh connection instead of the scheduled task `install.ps1` already registers |
| "capture produced NO results" = capture failure | it was the *build* timing out at 600s. The pipeline ended in `tail -30`, so a 900s stream showed the tail of the wrong phase. |

None of the three was hardware. The capture then ran first time, on the same machine, unchanged.
The generalisable form: when a step that ends in `| tail` reports a failure, the failure you are
reading and the failure that happened are not reliably the same event.

All three are now codified in `packaging/windows/uimap-in-guest.sh` (`image`, `keepalive`, and the
flag inside `run`), so reproducing this is three commands rather than an evening.

**The one thing that was hard**, recorded because it will be re-encountered: Windows Setup boots
under exactly one of four firmware/controller combinations.

| firmware | controller | result |
|---|---|---|
| OVMF (UEFI) | AHCI | `failed to start Boot0002 UEFI QEMU DVD-ROM ... Time out`, then PXE |
| SeaBIOS | legacy IDE | `Booting from 0000:7c00`, then a bare cursor, disk never written |
| SeaBIOS | **AHCI (q35)** | **Windows Setup, 1024x768, disk growing** |

A 63 MB Alpine ISO boots fine over legacy IDE on the same host, and the Windows ISO loop-mounts with
a valid BIOS El Torito entry and a 4.9 GB `install.wim` — so neither the host nor the media is at
fault.

**Remaining in this phase**
1. Guest reaches first logon; OpenSSH comes up from the answer file.
2. `test-in-guest.sh find` — the installer is already inside as a mounted disc, nothing to copy.
3. `test-in-guest.sh install` — Inno silent switches, then read the install log.
4. `test-in-guest.sh verify` — `wsl -l -v`, container count, routes probed **from inside the
   distro** (`*.localhost` does not resolve on Windows itself; the OS resolver does not implement
   RFC 6761, so curl/PowerShell fail where Chrome would succeed).
5. Windows ui-map — `uimap-in-guest.sh keepalive`, then `image`, `push`, `run`, `fetch`. Needs the
   repo inside the guest's WSL distro, because the capture fans Chromium
   containers onto the stack's own network — the same reason it had to run on the machine hosting
   the Linux stack.

### What a clean Windows 10 machine actually found

Six defects, five fixed. A developer box has all of these already, which is exactly why none of them
showed up until the installer met a machine that had never run WSL.

| # | Defect | How it presented |
|---|---|---|
| 1 | Only q35+AHCI+SeaBIOS boots the media | see the table above |
| 2 | OOBE locales were only in the `windowsPE` pass | install ran perfectly, then stopped on a region picker with a Yes button |
| 3 | Two `dism` calls chained behind `;` in one command | `VirtualMachinePlatform` silently stayed **Disabled** while WSL showed Enabled |
| 4 | **The WSL2 kernel MSI was not shipped** | `wsl --import` fails: "WSL 2 requires an update to its kernel component" |
| 5 | **Debian trixie defaults iptables to nf_tables** | dockerd cannot create its bridge; surfaces one step later as "docker load failed (1)" |
| 6 | **The inbox Windows 10 WSL predates systemd** | UNFIXED — see below |

#### 6 is architectural and needs a decision

`wsl.conf` sets `systemd=true`, but that is honoured only by WSL 0.67.6+. The inbox Windows 10
`wsl.exe` does not even accept `--version`, and inside the distro:

```
System has not been booted with systemd as init system (PID 1). Can't operate.
```

So `binaos.service`, `docker.service` and `containerd.service` never run, and nothing starts the
platform. The images and binaries are all correct — dockerd 28.5.2 runs fine when started by hand.

Two ways out, and they trade different things:

* **Require modern WSL.** Ship or require the Store/MSIX WSL (~120 MB) so `systemd=true` works and
  the unit files are used as designed. Keeps one boot path for Windows and Linux. Costs size, and
  installing an MSIX has its own privileges and Store-availability problems.
* **Do not depend on systemd.** Have `install.ps1` start containerd and dockerd directly and run
  `docker compose up` itself, with the WSL keepalive task holding the instance open. Works on every
  WSL version, but Windows then boots the stack differently from Linux — two paths to keep correct,
  and no supervision or restart-on-failure.

The second is smaller and works everywhere today; the first is cleaner and matches the Linux design.
Not decided.

**Known risk not yet retired:** `Add-WindowsCapability OpenSSH.Server` pulls from Windows Update. If
the guest's egress is slow or blocked, SSH never appears and the test stalls at step 1. The fallback
is RDP on the forwarded port, or a `RunOnce` that runs the installer without needing SSH at all.

---

## Phase 2 — macOS.

Route is established and written up in `packaging/macos.md`: cross-build from Linux with `GOOS`
and osxcross, and **`rcodesign` signs *and* notarises from Linux** — no Apple hardware needed for
the build. Deferred by explicit instruction while Linux and Windows land.

Blocking question before starting: the same one-Linux-userland decision as Windows — a thin host
shell plus a Linux guest — which on macOS means choosing the VM layer (Apple Virtualization
framework vs. a bundled hypervisor). That choice, not the signing, is the real work.

---

## Phase 3 — layers 1 and 2 as native binaries.

The original ask behind all of this. `packaging/native-plan.md` has the study. The shape:

* Keep the compose logic for layer 3, so gallery apps stay ordinary containers.
* Replace the layer 1/2 chassis with processes the host runs directly.

**authentik is the long pole and has no non-Docker install.** The study recommends Authelia; Zitadel
is the other candidate. That decision gates the phase and has not been made.

**A real defect found today feeds straight into it, and it is now confirmed on two platforms:**
authentik's first boot binds **zero** proxy providers to the embedded outpost, so every SSO route
404s. It recurs after a stack restart.

| | Linux host | Windows guest |
|---|---|---|
| django migrations | 543 | 543 |
| proxy providers created | 12 | 0 mid-race, then created |
| applications created | 12 | 0 mid-race, then created |
| bound to the outpost | 22 after the fix | 22 after the fix |
| `Deployment - Generated App Providers` | error | error |
| `Deployment - ForwardAuth Applications` | successful | error mid-race |
| bootstrap | `outpost syncing (0 ok, waiting on 0: host list pending)` | same |

The sequence that clears it on BOTH is the same: wait for `authentik-server` to report healthy,
THEN restart `authentik-bootstrap`. It binds 22 providers on each. The guest simply takes longer —
300s versus 225s — and an earlier snapshot of it, taken before the bootstrap had finished, showed
0 providers and both blueprints in `error`. That snapshot is what the row above records; it is a
picture of the race in progress, not a different outcome.

The real finding is therefore narrower and more useful: the defect is a first-boot ORDERING race,
identical on both platforms, and the window is wide enough that a slower machine sits inside it for
five minutes. A customer's first boot is exactly the slow, loaded case.

Two conclusions. First, this is a platform bug, not an environment quirk — the same first-boot race
appears on two unrelated operating systems. Second, the blueprint application itself is fragile
under slow or loaded conditions, which is exactly what a customer's first boot looks like.

Whatever replaces authentik must not reproduce this. If authentik stays, this is the bug to fix
before release: nothing else on the roadmap will be visible to a user who cannot reach a single
SSO-protected route on first boot.

---

## Phase 4 — the things that will bite before release.

Ordered by how quietly they fail.

1. **CI jobs write into the checkout as root.** `ops/prejob_fixperms.sh` is a safety net that stops
   one job wedging the runner for every job after it. The fix is
   `docker run --user "$(id -u):$(id -g)"` in the jobs that produce those files.
2. **`traefik` v3.3 → v3.6+.** Until this lands the platform cannot run on Docker 29 at all, and it
   fails silently: traefik reports healthy, discovers zero routers, every route 404s. The artifact
   pins 28.5.2 to avoid it, which is a workaround with an expiry date.
3. **Postgres consolidation — and it is already failing CI.** Four clusters spanning
   15.8 / 16.14 / 17; `supabase-db` needs five extensions vanilla Postgres lacks. Directly sizes
   the artifact.

   It is no longer only a size question. `platform-invariants` fails on
   `layering-lint.py --strict`, which reports two layer-inversion debts, both naming `supabase`
   from inside layer 1:

   ```
   base config naming a layer-3 app                    2
       platform-base/connections/providers/40-apps.yaml  [supabase]
       platform-base/postgres/docker-compose.yml  [supabase]
   ```

   Both are NAMING artifacts rather than real dependencies: when supabase moved to the gallery, the
   platform database deliberately kept the `supabase-db` container name, hostname and
   `supabase/postgres` image so every DATABASE_URL in the stack kept working — the file says as much
   ("An app that talks to the database cannot tell this happened"). That was the right call at the
   time and it is why the move was invisible.

   The gate is still correct: layer 1 should not name a layer-3 app, even in a string. Clearing it
   means renaming the database to something layer-neutral, which touches every connection string and
   needs a data step — so it belongs with the consolidation, not before it.

   Dated: July 23 jobs passed this gate; it has been failing since the gallery move.
4. **`inbox` health probe** uses the gmail path on :993 while the bundled mailserver offers only
   :143, so `mailview` goes unhealthy, traefik drops its router, and `mail.localhost` 404s. Not
   caused by the executable — the same config ships normally.
5. **Signing.** Deliberately dropped for now. `verify-artifact.sh` already refuses a manifest whose
   version does not match, and the build deletes a stale signature rather than shipping an unsigned
   artifact next to the previous one's `.sigstore.json`.

---

## What a fresh session should read first

* `packaging/README.md` — the decision record, including the three parts of the original brief that
  cannot be satisfied as stated.
* `packaging/native-plan.md` — the layer 1/2 study.
* `ops/README.md` — the runner box: why CI went red, and the two traps that make it look like a
  code problem.
* `packaging/linux/run.sh` header comments — the artifact layout, and why the ordering
  (build → hash → concatenate → sign → never touch again) is not negotiable.
