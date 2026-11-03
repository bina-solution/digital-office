# Setting up a new company's office — what The Fireplace Guys taught us

From 2026-10-22 to 2026-10-30 we set up a whole client business on DGO (office `fireplace`, items
FPG-1…FPG-527). This is the order to follow next time. Each phase says what to do, what went wrong,
and what the product does now. Issue files are under `issues/`. Commits are on the release line.

## 1. Before the call

**Do.** Research the business before any code (FPG-17). Plan in six modules: accounts and secrets;
the office; the client's app; the website; defects found; the first month and handover. Put the
owner's decisions on one page, each with a recommendation. Send the data list (see the checklist)
before the call.

**Went wrong.** The client's items lived in our Plane. Moving them to the client's Plane was manual
(`no-way-to-carry-plane-items-from-one-office-to-another.yaml`). The client's plan and call notes were
committed to the product repo and had to be taken out (5b5bbdb6). Another office's machine names had
leaked into product runbooks (9c3c5f1e, FPG-3).

**Product now.** `bbox project-pln plan` applies a plan file. A processed meeting links its items both
ways (c6ea7b4b). **Still lacks:** a verb that moves items between offices (issue above, open).

## 2. The first call

**Do.** Hold it in Meet, recorded. Write the goals in the owner's words, with timestamps. Leave with
the decisions in the checklist below, or a date for each. Never let a password be said or shown. The
call becomes a transcript.

**Went wrong.** A client password was shown in the recorded call and sent in chat. It had to be
rotated (FPG-56). The first target date passed; the next target became a pilot.

## 3. The server and the domain

**Do.**
- Server in the client's name, on the client's card. Two cores and 8 GB hold the base set but not
  meetings plus transcription. Use four cores and 16 GB if Meet runs there.
- Choose `<company>.digital-office.co.il` before the install.
- Install from the release with DGO Extend, from our home office.
- Set the identity: `BUSINESS_NAME`, `DGO_HERD`, the Plane workspace, `DGO_BRANCH`. Use the `vps-2core`
  profile. Add swap. Harden SSH once the owner says yes.

**Went wrong.**
- The fresh office got the template `.env`: another office's domain and placeholder secrets
  (`dgo-extend-installs-a-fresh-office-on-the-template-env.yaml`). It also carried another company's
  name (FPG-60).
- A declaration with business apps only switched the platform off (3f7fbab6).
- The profile promised four cores on a two-core box
  (`fireplace-perf-profile-declares-four-cores-on-a-two-core-box.yaml`).
- The box ran out of memory (`fireplace-does-not-fit-eight-gigabytes-swap-full-and-browser42-was-on-again.yaml`).
- Installing an app waited forever for memory, and Debian had no swap
  (`installing-an-app-on-an-8gb-office-waits-forever-for-memory-and-no-swap.yaml`).
- The office changed its name after the install, so hosts, accounts and mailboxes had to move
  (FPG-33, FPG-34).
- The health step said "healthy" while every compose call failed (c700b01d).
- An app brief over its size budget blocked every bring-up for 12 hours
  (`meet-agent-md-over-budget-blocked-every-bring-up.yaml`).
- 33 fixes lived only in the server's checkout (FPG-62).

**Product now.** A fresh office gets its own `.env`, vault key and secrets (22538c2e, 3bf7c956). The
bare domain opens the console (03970a03). The domains app writes DNS records by code (f4659bc4).
There is a `vps-2core` profile (256bed81). `bbox rename-address` moves accounts after a rename
(1c03b703). **Still lacks:** swap and memory admission on 8 GB, a sane CPU floor, and identity asked
at install.

## 4. Mail and DNS

**Do.** Prove the office's admin mailbox in both directions first. Then add the company-domain
address. Then set the reverse DNS (PTR) in the server provider's panel. The mail server's name must
match it.

**Went wrong.**
- `https://mail.<domain>` had no HTTPS route (`mail-has-no-https-route-on-an-office-with-a-public-name.yaml`,
  fixed in 6ca1a37b).
- After the rename, mailboxes written while the mail server started were refused
  (`mailboxes-written-while-the-mail-server-starts-never-reach-dovecot.yaml`).
- The link door asked for a certificate on a host nobody declared (fixed in 10109f0e).
- The PTR stayed open.

**Product now.** The mailbox service proves each account by logging in (2ba05cd6); the issue file
still reads open. **Still lacks:** PTR is a hand step, with no issue file yet.

## 5. Sign-in and accounts

**Do.**
- Office apps use the office sign-in. A client app may have its own sign-in, so invite each person
  into it.
- Hosting, registrar, Google, the AI subscription and payments are the client's accounts. The owner
  opens them on the client's card.
- Passwords reach the office browser from the owner's password manager. An agent never types them.
- Put a copy of the backup key in the owner's password manager (FPG-58).

**Went wrong.**
- The client app's first admin needed a hand on `.env` (fixed in ab0b05c1).
- `/login` gave a 404 on refresh (`chimney-services-login-is-404-when-opened-directly.yaml`).
- The Plane tile went dead inside the console when its cookie expired (fixed in 97a65fc9, FPG-111).
- The office browser came back on the client's server, against the rule. Its task runner answers any
  caller (`browser42-task-runner-answers-any-caller.yaml`).

**Product now.** Invitations go out by e-mail (26241795), and accounts follow a domain change.

## 6. The apps they need

**Do.** Enable the smallest set: console, Plane, Drive, mail, Meet, sites, digital assets, the
agent, Obsidian, n8n. Keep the browser off the client's server. Set the office language before anyone
signs in.

**Went wrong.**
- Console search did not find an app the console does not frame (fixed in 04121c76, FPG-107).
- Plane and Obsidian windows gave a 404 on a public domain
  (`framed-hosts-404-on-a-public-domain.yaml`). An edge file written by hand now carries the client's
  domain.
- An app with no compose file in its manifest broke the whole office (fixed; gate G5, 7ef3c16f).
- `bbox n8n push` needs node on the host (`bbox-n8n-push-needs-node-on-the-host.yaml`,
  `n8n-push-needs-node-on-the-host.yaml`).
- The office was in Hebrew for English speakers (FPG-64).
- A container nobody declared served a public path
  (`drop-tmp-is-a-container-no-compose-file-declares.yaml`).

**Product now.** The Obsidian vault is generic (beef2766).

## 7. Meetings

**Do.** Run `bbox meet verify --call` after the install and before each important meeting (66c4b223,
FPG-87). Check that the MEET project exists in the office's own Plane. Give the recorder CPU and memory
floors. On a small box, hold one meeting at a time.

**Went wrong, now fixed.** The CPU budget throttled the recorder, and recordings lost sound
(`meet-recorder-throttled-to-half-a-core-recordings-lose-sound-and-time.yaml`). The transcriber
competed with it. The blurred background cost more than a core. A guest with no microphone permission
was recorded as silence. A second meeting at the same time went unrecorded, and nobody was told.

**Went wrong, still open.** The first 13 seconds are lost. Transcripts never reach an office's own
Plane; the fix there was made by hand. Installing Meet does not create its Plane project. Whisper
invents "thank you" on silence. Clipped audio has no detector. The files are listed at the end.

**Product now.** Transcripts and subtitles go to Drive by themselves (856a84df). Live captions carry the
office's own terms (FPG-471).

## 8. The client's own app

**Do.**
- One app. Never two copies side by side.
- Mark sample data, and never quote a customer from it.
- Ask the owner for real data as a list he fills in, not a hunt through screens.
- A card-payment provider needs a business entity, so the owner opens it. Until then, offer manual
  transfer: the customer uploads proof and an admin approves it.
- Review every role at phone width.
- Commit on the office branch before you deploy.

**Went wrong.**
- Two apps with one catalogue ran side by side and had to be merged (26241795).
- A copied builder carried another company's catalogue and was taken out of the repo (5b5bbdb6).
- The manifest named no compose file (`an-app-whose-manifest-names-no-compose-file-breaks-the-whole-office-compose-project.yaml`).
- Work was deployed first and committed later as "as deployed" rounds.

**Product now.** The client app has a beauty gate for every role at six widths, and it builds no
deploy package without a passing scan (FPG-498). **Still lacks:** that gate and the local test office
live in one app's `tools/`, not in the platform. No item yet.

## 9. Phones and notices

**Do.** The owner turns notices on from a menu. Send a test, then ask "did it show?". Android has a
switch for each site. Some phones show no Chrome alerts at all; Firefox works there.

**Went wrong.** The phone confirmed every test alert and showed none (FPG-501).

**Product now.** The platform's notifications send office notices by Web Push (6cdaca0b). **Still
lacks:** delivery receipts and "did it show?" exist only in the client app (FPG-501).

## 10. Handover and the first month

**Do.**
- For the first month, manage the office from our herd: a daily check, a weekly report in the
  client's language, and a daily encrypted backup off the server with a restore drill.
- Then disconnect, hand over admin in every app, and rotate every secret that passed through us
  (FPG-96).
- Keep the client's records in the client's herd.

**Went wrong.**
- Our home office was down for four days, so the backup stopped. Then the SSH key no longer matched,
  and the copy outgrew the home (`fireplace-offsite-backup-stopped-and-now-outgrows-the-home.yaml`).
- After a restart, the client office served nothing until the home re-ran its link step
  (`a-converged-far-office-serves-nothing-after-a-restart-until-the-home-reruns-its-link-step.yaml`).

**Product now.** The daily check (186f9ab2), the English weekly report (ac65ae7e) and the off-server
backup (706dd289) exist.

## Decisions only the client's owner makes

- [ ] The server's size, and who pays for it.
- [ ] The office name, decided before the install.
- [ ] The company's own domain for the site, and its DNS records at the registrar.
- [ ] The agent's AI path and its subscription.
- [ ] The payment provider: the account, the deposit rule, and who may skip a deposit.
- [ ] The business facts: price list, catalogue, service area, hours, daily capacity, teams, photos,
  past quotes.
- [ ] Where the website content comes from.
- [ ] The office language.
- [ ] Which heavy apps run on the server: meetings, transcription, the browser.
- [ ] Who gets an account, and with which role. Who receives the weekly report.
- [ ] A yes to SSH hardening.
- [ ] Which duplicate app to retire.
- [ ] The handover date.
- [ ] Owner hand acts: rotate any exposed password and add 2FA, connect accounts in the browser, set
  the registrar records, save the backup key.

## Product gaps still open

- Moving Plane items: `no-way-to-carry-plane-items-from-one-office-to-another.yaml`
- Template `.env` (in progress): `dgo-extend-installs-a-fresh-office-on-the-template-env.yaml`
- Identity not asked at install: FPG-60
- Memory and swap on 8 GB: `installing-an-app-on-an-8gb-office-waits-forever-for-memory-and-no-swap.yaml`
- CPU floor: `the-cpu-floor-of-a-tenth-core-throttles-the-health-probes.yaml`
- n8n oversized: `n8n-runs-two-workers-and-a-webhook-process-for-twenty-executions-an-hour.yaml`
- Named services ignored: `bbox-run-with-named-services-still-starts-the-left-out-recorder.yaml`
- Private GitHub in a build: FPG-66
- Framed windows, hand-written edge file: `framed-hosts-404-on-a-public-domain.yaml`
- n8n push needs node: `bbox-n8n-push-needs-node-on-the-host.yaml`
- Undeclared container: `drop-tmp-is-a-container-no-compose-file-declares.yaml`
- Office language: FPG-64
- Mailbox race (fixed in code, file open): `mailboxes-written-while-the-mail-server-starts-never-reach-dovecot.yaml`
- PTR by hand: no issue file yet
- Browser task runner: `browser42-task-runner-answers-any-caller.yaml`
- Meet:
  - `meet-recording-misses-the-first-13-seconds-of-every-meeting.yaml`
  - `meet-transcripts-never-reach-an-office-s-own-plane.yaml`
  - `meet-install-does-not-create-the-plane-project-meet.yaml`
  - `meet-whisper-hallucinates-thank-you-on-silence.yaml`
  - `meet-chopped-audio-has-no-detector-and-restore-is-manual.yaml`
  - `meet-jicofo-loses-the-recorder-after-prosody-and-jibri-restart-in-a-row.yaml`
  - `meet-plane-item-does-not-carry-capture-json-and-live-captions.yaml`
  - `meet-has-no-self-test-call.yaml` (the verb exists; the file still reads open)
- Push receipts: FPG-501
- Beauty gate in the platform: no item yet
- Backup needs the home: `fireplace-offsite-backup-stopped-and-now-outgrows-the-home.yaml`
- Link after restart: `a-converged-far-office-serves-nothing-after-a-restart-until-the-home-reruns-its-link-step.yaml`
- No agent credential: `a-converged-office-that-serves-hands-no-agent-credential-to-the-home.yaml`
- Handover: FPG-96
