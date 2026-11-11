# containers — «מכולות», the one app that runs containers

The owner, 2026-11-09 (DGO-1723): one app owns everything about running containers, and every app that
needs a container uses it as a dependency. This is D2 of [packaging/native-plan.md](../../packaging/native-plan.md),
"the engine is a platform capability".

**What it provides:** `container-runtime`. **Who requires it:** every app whose manifest declares `compose`.
No manifest says so: the compiler implies it where the resolver reads `use[]` — `uses_of()` in
[reconcile.py](../../platform/manager/reconcile.py), `usesOf()` in its Go twin
([resolve.go](../../packaging/dgo/internal/compiler/resolve.go)). An app that provides the runtime, or declares
its own use of it, is read as written. So enabling any container app pulls `containers` in, as a database
app pulls `postgres` in.

**It runs no container of its own.** Its manifest has no `compose`: the runtime is the office's engine, and
how the office gets one is the one thing that differs per OS. Which backend each OS has follows the research of
DGO-1725 (`reports/DGO as an operating system.md`, «Containers run at native speed only while data stays inside
the guest» and «Android can host the office; an iPhone can only reach it»): one long-lived Linux guest wherever
the host is not Linux, the Docker Engine API as the contract the compiler and `scripts/dc` speak, and the office's
data on the guest's own disk, never on a host share.

| OS | the engine today | the research's choice | who provides it |
|---|---|---|---|
| Linux | Docker 28.5.2 on the host | the same API, on containerd 2.x + crun + cgroups v2; the 28.5.2 pin retired by fixing traefik | `debian-install.sh`, bbox's `need_docker` |
| macOS | the Lima/vz guest's Docker | Lima on VZ, kept (Apple's per-container VMs only as an isolation option) | `packaging/macos/engine.sh`, `bbox engine` |
| Windows | the WSL distro's Docker | DGO's own WSL2 distro, its disk sparse with its own trims, mirrored networking | `bbox.cmd` |
| Android | the office's machine with Docker: QEMU (TCG), AVF where granted | AVF with DGO's guest kernel where the phone has non-protected pKVM (a one-time grant), QEMU TCG elsewhere | the app's `EngineService`, started by the native core |
| iOS | none | none possible (no hypervisor, no JIT): the app reaches offices running elsewhere | — |

**On unless an office says otherwise** (`ON_UNLESS_SAID` in reconcile.py, the same rule in the Go twin and in
app-management): every office's own containers run on its engine already, so a state that does not name
`containers` has it on, and an office that names it (off, or archived) is read as written.

On every OS but Android, the office's own base still runs in containers today, so the engine is there
before anything else and `containers` is simply running. On Android the base runs natively (the core:
`dgo be-child native` and forward-auth); there the runtime is the office's machine, and the core's own
apps that run in containers (connections, notifications, dgo-extend, computers) still start it with the
core. That the phone's base starts without it, and that «מכולות» is installed when the owner asks for it,
is the next step (DGO-1723, with the app's status screen).

`dgo engine doctor` reports the engine this office runs on, the same checks on every OS.
