# computers — the details its brief points to

`AGENT.md` is injected into every agent session, so it holds what the app is for, its vocabulary and its traps
(the 6000-byte budget, G73). The calls and the behaviour a task needs only when it touches them are here.

## Moving a volume between two machines — `stream`

```bash
# a volume between machines, resumable (`transfer` = its older name)
curl -s -X POST http://computers:8977/api/computers/<src>/stream -H 'content-type: application/json' \
     -d '{"to":"<dst>","volume":"drive_uploads","dest_volume":"digital-office_drive_uploads"}'
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

## A terminal on a machine — the shell routes (DGO-1800)

```bash
# open (an interactive login shell over the office key), type, poll from a byte cursor, resize, close
curl -s -X POST http://computers:8977/api/computers/<id>/shell -d '{"cols":120,"rows":32}' -H 'content-type: application/json'
curl -s -X POST http://computers:8977/api/computers/<id>/shell/<sid>/input -d '{"data":"uname -a\n","cursor":0}' -H 'content-type: application/json'
curl -s "http://computers:8977/api/computers/<id>/shell/<sid>?cursor=<n>"
curl -s -X DELETE http://computers:8977/api/computers/<id>/shell/<sid>
```

- One read ends at 256 KB / 0.25 s, a write the far side does not take ends in 2 s (503 — the session lives on), a
  read never ends inside a character. 8 sessions a machine, 30 minutes idle.

## Machines a linked office shares — the count of its reads (DGO-553)

- `./bbox computers callers` also counts the READS other offices make here through the link (`door_reads`) — the
  first stage of narrowing what a client office reads (issues/a-linked-office-reading-computers-…).
