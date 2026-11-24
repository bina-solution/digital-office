# image-store — «מאגר התמונות», the images a take pulls instead of building

The images the line's proof built, by digest (DGO-2123; the design: `research_notes/CICD 2026-11/images.md`). A take
that pulls them builds nothing: vps1 built batch 98 for ~8 minutes at load 26 on two cores. Shipped disabled.

## Two roles, one setting (`REGISTRY_ORIGIN_URL` in the office's `.env`)
- **origin** (empty): on the machine whose CI runner builds, the Dell. The proof's tail pushes each changed image here
  through the engine at `127.0.0.1:${REGISTRY_HOST_PORT}` (5055). The office serves its door to the linked offices, a
  door with no tile (DGO-945): `serve: {services: {image-registry: {to: [vps1, hp-laptop, macbook]}}}`. The door is the
  service `image-store-door`: the same storage, read-only (`door.yml`, and its volume mounted `:ro`). A linked office
  pulls, and never pushes or deletes.
- **mirror** (set to the origin's door, `http://image-registry.<origin office>:<door port>`): on every other office. A
  pull-through cache: what the engine asks and it does not hold, it fetches over the link once, and keeps. It takes no
  push.

The engine pulls at `127.0.0.1:5055`: a loopback registry needs no TLS and no daemon setting, and the engine fetches
only the layers it lacks. The link proxy streams a blob through; it never holds one in memory.

## How to operate it
```bash
./bbox image-store status       # role, upstream, repositories, the space they hold (JSON)
curl -s http://127.0.0.1:5055/v2/_catalog                # on the office's machine
curl -s http://127.0.0.1:5055/v2/<service>/tags/list
```
- A take pulls `127.0.0.1:5055/<service>@sha256:<digest>` for each digest the line's proof named
  (`refs/images/dgo-stable`), and tags it under the name the compose file gives the service. Then it runs
  `BBOX_PREBUILT=1 bbox run`. Whatever it could not pull, it builds, as before.
- On the origin, space is given back by deleting digests older than the last green versions, then the registry's
  garbage collection. Never delete on a mirror: what it holds, it fetches again.

## What not to do
- Never publish its port on an interface: the loopback is the engine's; a linked office comes through the door.
- Never point the capability `image-registry` (the link's door) at `image-store`: that one takes pushes and deletes.
- Never push to a mirror (it refuses): images come from the proof, on the origin.
- Never start a registry by hand on the Dell, or anywhere: the owner's rule (2026-11-10) is that only the office runs
  there. It runs as this app.
