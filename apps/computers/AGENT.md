# Operating `computers`

The office's fleet. Every machine the deployment can act on is a **connection instance** of protocol
`computer_ssh` in the credential plane (`http://connections:8990`), not a row in this app's config —
so the fleet is the same list the console's account switcher shows, and it survives this app being
rebuilt.

Vocabulary: a **machine** is an instance (`computer_local-local` is the host running the deployment,
built in and **never deletable**); an **office key** is the ed25519 keypair this app minted into its
own volume — it is not the owner's key and is never handed out; a machine is usable only once the
owner has approved the public half in that machine's `authorized_keys`.

## What you can do from here

```bash
# the fleet, with live state (hostname/os/load/mem/disk) — ?probe=0 skips the SSH round trip
curl -s http://computers:8977/api/computers
# run a command ON a machine (a write: it needs the token, DGO-1304; never print it, no curl -v)
curl -s -X POST http://computers:8977/api/computers/<id>/exec -H "authorization: Bearer $DSH_COMPUTERS_EXEC_TOKEN" \
     -H 'content-type: application/json' -d '{"command":"df -h /","timeout":60}'
curl -s http://computers:8977/api/computers/<id>/status
```

`exec` returns `{code, stdout, stderr, timed_out}` — the remote shell's real exit code. `/exec` is
the deliberate door for "this must run on the machine itself"; `ssh` (or the engine socket) from
inside a container is not.

## The herd: every office's computer (DGO-890), and where each app belongs (DGO-911)

```bash
curl -s http://computers:8977/api/herd                                     # this office + every linked one
curl -s http://computers:8977/api/hosts/vps1/machine/api/overview?brief=1   # a computer's resources, via its door
curl -s http://computers:8977/api/hosts/vps1/security/api/summary?hours=24  # its network, from ITS security app
./bbox computers herd [--json]   # every office against herd.yaml: MOVE · LEFT OVER · MISSING · ANOTHER DEPLOYMENT
```

- A read is one GET to a path on `herd.ALLOW`; anything else is a 403 before any network.
- A computer running security without machine (the Mac) is drawn from `security/api/host/overview`.
- The one write is a cleanup on THIS computer (`POST /api/hosts/local/machine/cleanup/<id>`).
- `herd.yaml` is the business's placement: one office per app, the base everywhere
  (`ai/context/dgo-herd.md`). Change it there, in one commit.
- `herd` exits 0 when the herd matches, 1 when it does not, 2 when it cannot read.

## Moving a volume between two machines — `stream`

`POST /api/computers/<src>/stream {"to","volume","dest_volume"}` moves a volume, resumable and verified;
`GET /api/transfers/<job>` follows it, `POST …/cancel` pauses it. Its flags and what an `ok` means: README.md.

## Sharing a computer with another office — `shares`

`POST /api/computers/<id>/shares {"to","public_key"}` (the borrower's `GET /api/office-key`) lends a
machine over HTTPS and returns the `door` (`wss://<host>/share/<token>`, shown ONCE); the borrower
adds it with `POST /api/computers {"door",…}` and exec/probe/stream then go through it. Revoke:
`DELETE /api/shares/<sid>` (lists at `GET /api/shares`). No SSO on that one path — never widen it.

## A terminal on a machine — the shell routes and the screen (DGO-1800)

- `POST /api/computers/<id>/shell` opens a login shell; `…/shell/<sid>/input`, `GET …/shell/<sid>?cursor=<n>`,
  `DELETE …/shell/<sid>`. The calls and their limits: README.md.
- The screen is this app's: `/a/computers/terminal?machine=<id>` — «טרמינל» on a machine's row and in the host
  view. (apps/terminal relayed it from its own container, which this app rightly does not believe; it is retired.)
- Writes pass the same caller check as `exec`; a session belongs to whoever opened it (another caller's answers as
  one that does not exist); a caller that claims an office and fails the claim is refused in every mode.

## Machines a linked office shares — `<machine>.<office>` (DGO-553)

- `GET /api/computers` lists, from each linked office, the ONE machine it gives (its own, `computer_local-local`) as
  `computer_local-local.<office>`, and `shared_from` says which office answered and which did not.
- Anything for `/api/computers/<machine>.<office>/…` goes to that office through the link's door and is answered as
  it answers — only a command, a terminal and its poll, from an identified caller; a request that came through a
  door is not passed on to a third office. That office runs it with ITS key under ITS caller check.
- `./bbox computers callers` counts the reads other offices make here through the link (README.md).

## Traps

- **Only machines in `GET /api/computers` exist.** Never construct a host from memory, and never
  act on the owner's Mac directly — it is reachable only as what the fleet says it is.
- Choosing a **destination machine matters**: running on `computer_local-local` is running on the
  box that runs the whole office (that is where the checkout and `./bbox` live), not a sandbox.
- A command that needs a login shell, a TTY or an interactive prompt will hang until the timeout.
- Adding a machine is an owner action in the UI (`/a/computers/`): the app shows the public key and
  the exact `authorized_keys` line. You never create, delete or re-key a machine on your own.
- `CONNECTIONS_URL` down = an empty-looking fleet. `{"computers": []}` and "the vault is unreachable"
  are different states: read the `reason`/error, do not report "no machines".
- **A `stream` needs room for the archive AND the extracted copy** on the destination (about twice the
  data); the refusal says the number. `resume:false` trades that space for the ability to resume.
- **One transfer at a time.** A second `stream` is refused by name (`active_job`), not queued: the
  office's link is shared, and two copies at once is how both of them end up slow.
