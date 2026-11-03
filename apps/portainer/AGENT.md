# Operating «מכולות» (the `portainer` app)

Portainer, a screen for the engine's containers. It is **retired in the herd**
(`apps/computers/herd.yaml`: no office runs it), and it ships off. It has no console tile and no API
for agents.

## Rules

- **Do not enable it, and do not use its API.** It mounts the engine's socket read-write, so its
  admin is root on the engine, and its host is not behind the office's SSO.
  - To see or act on containers, use `./scripts/dc` and the computers or machine apps.
- Its sign-in is Portainer's own: user `admin`.
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
