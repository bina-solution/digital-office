# Operating «מכולות» (the `portainer` app)

Portainer, a screen for the engine's containers. It is **retired in the herd**
(`apps/computers/herd.yaml`: no office runs it), and it ships off. It has no console tile and no API
for agents; where an office has it on, the console's screen search finds it and opens it in its own
tab (`module` with `embed: false`).

## Rules

- **Do not enable it, and do not use its API.** It mounts the engine's socket read-write, so its
  admin is root on the engine.
  - Its host sits behind the office's sign-in (`auth: sso`; the compiler emits its routers), and
    Portainer's own login after it (DGO-1762). Before that it was open to anyone who reached the host.
  - To see or act on containers, use `./scripts/dc` and the computers or machine apps.
- Its own login, after the office's sign-in, is user `admin`.
  - `hooks/prepare` writes the password file `apps/portainer/portainer_password.txt` (gitignored)
    once: from `.env`'s `PORTAINER_ADMIN_PASSWORD`, or a random one when `.env` has none.
  - It never rewrites a file that exists, so a later `.env` change does not reach it.
  - Portainer reads the file only on its first start, with an empty data volume.
  - Never print it.

## Traps

- The password file must have no trailing newline, or every login fails; `prepare` writes it with
  `printf`. If the file is missing, docker makes a directory in its place, and `prepare` removes it.
- `app.json` still names `debian-install.sh` as the file's writer. It is `hooks/prepare` now.

Gates: G23 (a gallery app ships disabled). It also appears in G11's and G84's exemption lists (the
generated password file, the socket mount).
