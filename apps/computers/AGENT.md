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
# run a command ON a machine — the only correct way to act on the host or on a remote server
curl -s -X POST http://computers:8977/api/computers/<id>/exec \
     -H 'content-type: application/json' -d '{"command":"df -h /","timeout":60}'
curl -s http://computers:8977/api/computers/<id>/status
```

`exec` returns `{code, stdout, stderr, timed_out}` — the remote shell's real exit code. `/exec` is
the deliberate door for "this must run on the machine itself"; `ssh` (or the engine socket) from
inside a container is not.

## Moving a volume between two machines — `stream`

```bash
# a docker volume from one machine to another, RESUMABLE and with live progress.
# `transfer` is the same door under its older name.
curl -s -X POST http://computers:8977/api/computers/<src>/stream -H 'content-type: application/json' \
     -d '{"to":"<dst>","volume":"drive_uploads","dest_volume":"deployment-hacohen_drive_uploads"}'
curl -s http://computers:8977/api/transfers/<job>          # phase, bytes, done_bytes, total, percent, rate, eta
curl -s -X POST http://computers:8977/api/transfers/<job>/cancel   # pause: the staging file stays
```

Body flags: `restart` (wipe a previous attempt and start over), `verify` (sha256 of the archive against
the source, default `true`), `measure` (measure the archive on the source first, default `true`),
`resume:false` (stream straight into the destination volume — no staging file, so **no resume**, and it
is the only shape that fits when the destination cannot hold the archive twice).

How it behaves, and the three things an `ok` means:

- The archive in flight lives in ONE file on the destination (`/var/lib/bina-transfer/<src>__<dst>.tar`);
  the destination's volume is untouched until the archive is complete and verified.
- A dropped link — or this app restarting — resumes at that file's own size (`tail -c +N+1` at the
  source, `cat >>` at the destination). `cancel` is therefore a **pause**, not a discard.
- A resume is refused when the source volume changed since the first attempt (its fingerprint is stored
  beside the staging file); `restart:true` is the deliberate override.
- `ok` = the staging file reached the measured total, its bytes matched the source's own `tar`
  byte-for-byte, and it extracted. Fewer than all three is reported as a failure, not as "mostly done".

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
