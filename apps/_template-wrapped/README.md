# `_template-wrapped`: the starting files of a wrapped official app

The pattern and its reasons are in [ai/context/wrapped-official-app.md](../../ai/context/wrapped-official-app.md).
Gate G108 (`scripts/refactor/wrapped-app-lint.py`) holds the result to the four channels.

## Making an app from it

1. Copy every file here EXCEPT this README to `apps/<id>/`. Then drop every `.template` suffix, and rename
   `hooks.template/` to `hooks/`.
2. Leave `hooks/flow.when-it-publishes` aside until the adapter really publishes on `dgo:flow:<id>`
   (`platform-base/redis/flowpub.py`), then rename it to `hooks/flow`. G108 counts the hook, not the
   publisher: a flow hook with nothing behind it passes the gate and shows an empty stream. Until then the
   wrap gets a KNOWN line in wrapped-app-lint.py that says why it has no flow yet.
3. Copy the front door in: `cp apps/bina-claude/adapter/gate.mjs apps/<id>/desktop/gate.mjs`, then replace its
   leading `//` header with the two lines element's, signal's and slack's copies carry, the first being
   `// Lifted from apps/bina-claude/adapter/gate.mjs — keep the copies in step (G110 holds them to it).` —
   without that line G110 does not see the copy, and nothing keeps it the same door. An app never reaches into
   another's folder, so the door is copied, not referenced. (Its log lines still say «bina-claude», and it
   reads its settings under bina-claude's names; desktop/svc-gate/run sets them.)
4. Replace every placeholder:
   - the app: `<id>` (its id), `<ID>` (the id in capitals with `_` for `-`, for the variables), `<Name>`
     (English), `<שם בעברית>`, `<short name>` (the CLI alias);
   - the vendor: `<Vendor client>`, `<vendor>` (a short name for the key and the list), `<VENDOR KEY URL>`,
     `<VENDOR KEY FINGERPRINT>`, `<VENDOR APT URL>`, `<suite>`, `<vendor-package>`, `<vendor-binary>`;
   - the base image: `<tag>` and `<digest>` (the digest of the tag you measured);
   - the contract: `<capability>`, `<interface>`, `<adapter port>`;
   - the prose in angle brackets in app.json and AGENT.md.

   `grep -rn '<[^>]*>' apps/<id>/` lists what is left (the copied gate.mjs has none).
5. hooks/status reads the adapter with node. A Python adapter makes the same read with `python3 -c`.
6. Make the hooks runnable, and commit the mode: `git update-index --add --chmod=+x apps/<id>/hooks/*`.
7. Write the adapter (below). Then go through the seven-step check in wrapped-official-app.md before the app
   enters the catalogue.

## Why nothing here is an app

The folder has no `app.json`, no `docker-compose.yml` and no `hooks/`. So:
- the compiler, `bbox` (its app list and `bbox help`) and the gates that start from an app's app.json pass
  it by;
- G31 checks the mode of `apps/*/hooks/*` only, and the hooks wait in `hooks.template/`.

Some gates read every file of a kind, wherever it is, so they read these files too. They pass them:
- G74 and G18 read every `Dockerfile*`;
- G88, G90 and G105 read shell files, scripts and pages;
- G11, G92 and G94.

## The files

| file | what to fill in | taken from |
|---|---|---|
| `app.json.template` | id, titles, `wraps`, the capability's interface + endpoint + `required_ops`, the tile and its `sso` block | apps/bina-claude/app.json |
| `docker-compose.yml.template` | the desktop (the screen), the one shot that makes its home, the adapter (the headless side), one volume | apps/bina-claude/docker-compose.yml |
| `Dockerfile.desktop.template` | the base image's digest, the vendor's repository, its key fingerprint, its package | apps/bina-claude/Dockerfile.desktop |
| `desktop/autostart.template` | how the client starts, and how its updater is turned off | apps/bina-claude/desktop/autostart |
| `desktop/svc-gate/run.template` | nothing but `<id>`: the s6 service that runs the front door | apps/bina-claude/desktop/svc-bina-gate |
| `hooks.template/status` | one read of the adapter, the standard's exits | apps/bina-claude/hooks/status |
| `hooks.template/flow.when-it-publishes` | the event stream, the platform's own reader (step 2) | build-your-first-app.md «The event stream» |
| `AGENT.md.template` | what an agent may do through the client | apps/bina-claude/AGENT.md |

The adapter, the headless side behind the contract, is the vendor's own and is not templated. bina-claude's
`adapter/server.mjs` (agent.v1 over Claude Code) is the worked example, and cad-api is a second one over
`freecadcmd`.
