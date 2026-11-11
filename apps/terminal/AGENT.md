# Operating `terminal` — שורת פקודה על מחשבי הלשכה (DGO-553)

> **2026-11-11 — THE SCREEN MOVED INTO `computers` (a8e80f379, DGO-1800); this app is being retired.** Its relay never
> worked as written below: `computers` does not believe the door's headers from this app's container (it believes them
> only from the console and the door), so under `enforce`, on an enforced host and over a link every terminal was
> refused (issues/the-terminal-app-calls-computers-from-its-own-container-…). The screen is now `computers`'
> own — `/a/computers/terminal?machine=<id>`, the «טרמינל» action on a machine's row and in the host view — talking to
> `computers`' shell routes directly (`/api/computers/<id>/shell…`, see apps/computers/AGENT.md). This app's tile is
> hidden (`tile: false`); its routes still answer old bookmarks until it goes to legacy/ (G34). Read the rest below
> as history.

A browser terminal on any machine of the office, and the screen a person uses when they want to
WORK on a machine rather than read about it. One session per terminal, over the office's own SSH
key, opened as a real interactive shell (`ssh -tt`, a pty on both ends).

## The chain, and why it is what it is

    browser → terminal (this app) → computers (holds the key) → ssh → the machine

- **This app has no key, no volume and no privilege.** `COMPUTERS_URL` is its only door, and every
  call it makes is a `computers.v1` op. The key that opens a machine lives in the `computers`
  volume and never leaves it — a browser holds a session id, never a credential.
- **A proxy is not an exemption from the rule it proxies to.** The door's own headers
  (`x-dgo-office`, `x-dgo-identity`, `x-authentik-username`) are forwarded on every call, so a person
  of a linked office sees only the machines that office was given and can open a session only on
  them — measured 2026-11-01: without the pass-through the terminal asked as a LOCAL caller and
  listed this office's whole fleet. `_LIST_CACHE` is filled for local callers only, for that reason.
- **The transport is HTTP, not a websocket.** The console frames an embedded app through
  `/a/<alias>/`, and that proxy (Flask + `requests`, `_HOP`) strips `Upgrade` — a socket opened from
  a framed app never connects. So a session is `open → input → poll`, and `cursor` is an ABSOLUTE
  BYTE OFFSET of the output stream: a reader that missed a poll (a tab asleep, a phone in a lift)
  asks for what it missed and gets it, or is told it lost bytes (`lost: true`), never served a
  silent hole. `apps/computers/shell.py` is the whole argument.
- The cost is ~320 ms of poll latency on output. Keystrokes are sent immediately (one request in
  flight, the rest queued), so typing feels direct.

## What you can do from here

```bash
curl -s http://terminal:8080/api/machines | jq '.machines[] | {id,label,state}'
curl -s -X POST http://terminal:8080/api/shell -H 'content-type: application/json' \
     -d '{"machine":"computer_ssh-bacedbb6","cols":120,"rows":32}'
# → {session, output, cursor, alive}
curl -s -X POST http://terminal:8080/api/shell/input -H 'content-type: application/json' \
     -d '{"machine":"computer_ssh-bacedbb6","session":"<sid>","data":"uname -a\n","cursor":0}'
curl -s "http://terminal:8080/api/shell/poll?machine=<cid>&session=<sid>&cursor=<n>"
curl -s -X DELETE http://terminal:8080/api/shell/<cid>/<sid>
```

The owner-facing screen is `/a/terminal/` on the console host; `?machine=<cid>` opens that machine
directly, which is what the «טרמינל» action on a row of «מחשבים» does.

## Machines of a LINKED office

`/api/machines` lists them too, id `<machine>.<office>` — the merge is `computers`' (it asks the peer
and returns rows), and this app adds nothing to it. What it DOES add is honesty about the peer's
version: every remote machine carries `shell: true | false | null`, taken from that office's
`/manifest`. `false` means the office runs an app older than this op — the screen disables
«התחברות» and says «הלשכה הזו עדיין לא תומכת בטרמינל מרחוק — צריך לעדכן אותה» instead of opening a
session that dies. `null` means the office could not be asked (it is down), which is a different
sentence and not a "no". A local machine has `shell: null` — the field is about peers. The screen
fills its header with the same fact for MACHINES: `/api/machines` carries `shared_from` (which office
shares, and which one just did not answer), because a peer's rows that vanish read as a share that was
withdrawn. Both `machine` and `session` are validated before they reach a URL; an id is never a path.

## Traps

- **A machine with no SSH server has no terminal, and the screen says so** («ללא SSH»). The office's
  own machine (`computer_local-local`) is that case until an SSH server is enabled on it — the
  application is honest about it rather than pretending a shell exists.
- **A machine waiting for key approval** (`needs_action`) opens nothing: the exact command that
  approves the office key is «אישור המפתח» in «מחשבים» — and for a machine of a LINKED office that
  command is the PEER's key line, asked of the office that holds it (`/authorize-command` proxies).
- **Sessions are not persistent.** A restart of either app ends every shell, and the screen says the
  session is gone (`404`) rather than showing a dead pane. Nothing is written to disk: a session log
  on a volume would be a new place secrets accumulate.
- **Caps**: 8 sessions per machine, `COMPUTERS_SHELL_MAX` overall, 30 minutes idle
  (`COMPUTERS_SHELL_IDLE`), 256 KB of catch-up buffer (`COMPUTERS_SHELL_BUFFER`).
- Interactivity is a shell, not a root token: what a session may do is exactly what the office key
  is allowed to do on that machine.
