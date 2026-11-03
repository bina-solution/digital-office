# Operating «ניהול אפליקציות» (the `app-management` app)

The office's control plane: which apps are installed, on or off, and where they run. The «אפליקציות»
screen is built on it (tabs: installed, store, core). It reads every `app.json` and
`platform.state.yaml` from the mounted checkout and the live containers. It changes state only
through the compiler (`reconcile.py set-state` + `render`), and it starts containers through
`scripts/dc`.

## From inside the office network (`http://app-management:8080`)

```bash
GET  /api/apps                         # every app: declared state and running state
GET  /api/apps/<id>/room               # does this machine have room for it (cpu, memory)
GET  /api/apps/<id>/job                # the progress or result of the last lifecycle call
GET  /api/catalog                      # the store; POST /api/catalog/preview stages a package, writes nothing
GET  /api/remote | /api/office         # the linked offices' apps shown here / this office's record
POST /api/apps/<id>/enable | disable | archive | unarchive | uninstall | move | apply
POST /api/reconcile                    # converge running to declared (adds, never removes; reports drift)
POST /api/catalog/install · PUT /api/remote · PUT /api/office   # install an app, the linked offices' block, this office's identity
```

From the shell: `./bbox apps list|validate` read. `./bbox apps enable|disable <id>` only writes the
state and renders: it starts and stops nothing, and skips this API's core-app and `required_by`
checks. `./bbox run` converges through `/api/reconcile`. This API's reads, with running state:
`./bbox app-management apps|room <id>|job <id>|catalog|office`.

## What each lifecycle call does

- **enable**: writes the state, renders, runs the app's `prepare`, brings it up, waits for health,
  refreshes sign-in, runs `onboard`, pushes its n8n workflows.
  - It answers **202 after 20 s** while the work goes on: poll `GET /api/apps/<id>/job` until it says
    done.
- **disable**: stops its containers and removes its n8n workflows, and keeps its data.
  - While an enabled app still requires it, the state is written but its containers and workflows
    stay up, and the answer's `required_by` says who keeps them.
  - Off is then not stopped: read `required_by` before you report the app as down.
- **archive**: drops containers and images, keeps the volumes.
- **uninstall**: removes the containers and runs the app's own `hooks/uninstall` (its database rows,
  n8n blueprints, sign-in).
  - With `{"purge": true}` it **deletes every volume in the app's `data.volumes`**.
  - With no body the manifest's `on_uninstall` decides, and some declare `purge` (raphael,
    google-workspace-agent). Always send `{"purge": false}` unless the owner said purge.
- **move `{"to": "<office>"}`**: the other office checks it has room, takes the data over the link and
  brings the app up; only then is it switched off here. Nothing is deleted.

## Rules

- Reading is free. **Enable, disable, archive, uninstall, move, install and the two PUTs are the
  owner's decisions.** Each starts or stops services other people use, or rewrites what this office
  is. Do one only when he asked for it by name.
- **Never `purge`** without the owner's words for that app. An app's `data.volumes` can name a
  volume another app lives on: any-concurrency's names n8n's.
- A core app (`platform-base/`) answers 403 to every lifecycle call, by design.
- A call that arrives from a linked office (the door's `X-DGO-Office` header) is refused on every
  write. The one exception is `enable` carrying an archive to restore. Change another office's apps
  on that office.

## Traps

- One worker process: jobs, the lifecycle lock and staged installs are in memory. After a restart,
  `/job` answers 404 for a call that was running.
- An app declared off and still running is reported as **drift** (`/api/reconcile`'s
  `skipped[].drift`). It is not stopped for you.
- The repo is mounted at its host path and the docker socket read-write. This is the one service
  that may, so nothing else should copy what it does.

Gates: G16 (app conditions and the failure taxonomy), G27, G85 (every write route refuses a linked
office); its own tests.
