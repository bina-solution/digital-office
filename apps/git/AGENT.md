# Operating `git` — the office's version control (ניהול גרסאות)

Three things under one contract: **accounts + provider-agnostic ops** (GitHub, GitLab and the office's
OWN forge, acting as the owner — issues, PR/MR, releases, files — never holding a token); **the
smart-HTTP proxy** `/git/<code>/<account>/<owner>/<repo>.git` (credential injected server-side); and
**the local forge (Forgejo)** at `forge:3000` — `http://forge.console.localhost:8080` in a browser —
which
hosts local repositories and is the **code library and the display**, mirrors included.

**account** = a connection instance (a protocol IS an auth method); **mirror** = a copy of an external
repo kept in the forge for browsing (a display, never a push target); **op** = `POST /<op>`.

Account kinds: GitHub `pat`/`fine_grained` (no delete without `delete_repo`), `app` (hourly, no
`/user`); `oauth` (self-refreshing); GitLab `pat`/`group_token`/`project_token` (a project token sees
ONE project); `deploy_token`/`generic` (code only); `git_forge_local` (our forge). A repo reference is
`owner/name`; a GitLab namespace is opaque.

## The local forge, and its credential

Nobody types a token for it: `apps/git/hooks/prepare` (`./bbox app git prepare`, and it runs during
`bbox run`) creates the admin user, mints a token and stores it in the vault as one `git_forge_local`
instance. Re-running is free — it verifies first — and it is THE recovery command.

```bash
./bbox app git prepare                 # idempotent: admin user + token → vault
curl -s http://git:8978/api/overview   # forge, repos, accounts, mirrors — each half names its own failure
```

- The owner logs into the forge UI as user `office` (password in the vault beside the token).
  `auth: "none"` there is deliberate: the forge has its own login, and the way to drop it is Forgejo's
  reverse-proxy auth (`X-authentik-username`), never a middleware in front of a login page.
- Its config is **env-only** (`FORGEJO__<section>__<KEY>` in the app's compose) — no `app.ini`.
- Forgejo, not GitLab, by resource arithmetic — the numbers and what a GitLab backend would cost are
  in `README.md`.

## Mirrors

```bash
curl -s http://git:8978/api/mirrors
curl -s -X POST http://git:8978/api/mirrors -H 'content-type: application/json' \
     -d '{"source_account":"<connection-id>","repo":"owner/name"}'
```
Ops: `listMirrors`, `createMirror` (`source_account`+`repo`), `syncMirror` (`id`), `deleteMirror`
(`id`; `delete_repo=1` also removes the forge copy — the default KEEPS it).

- The sync runs HERE, not in Forgejo (whose pull-mirror would keep the GitHub token in its database):
  the engine clones through this proxy (`…/gh/…`) and pushes into the forge through it (`…/lc/…`), so
  no third-party credential leaves the vault.
- A sync is a JOB: a first clone is minutes (the office's own: 1263 MB, ~24 min); `createMirror`
  returns at once, ONE sync runs at a time (a second caller is told `busy`).
- Guards, reported not silent: `GIT_MIRROR_MAX_BYTES` (2 GiB) / `GIT_MIRROR_MIN_FREE_MB` (2048) — an
  oversized repo fails BEFORE the push, so the forge keeps the previous copy.
- A mirrored project is a COPY: a push there is overwritten by the next sync. Real pushes go to the
  owning provider (`POST /remote`).

## The screens: accounts and mirrors — the DISPLAY is Forgejo

`/a/git-accounts/` has exactly two screens and neither shows a repository: `#/accounts` (the accounts
the office acts with, each credential's PROBED state, the connect wizard) and `#/mirrors` (the declared
copies, their forge origin, the sync). Everything that displays a repository — list, tree, file, issues,
PRs, releases — is Forgejo, reached through the shell's own tile (module `git`, `external` → the forge
host). That is the owner's direction: one open-source product instead of a second one written here.

The API still answers `GET /api/repos?account=&q=` and `GET /api/repo?account=&repo=&ref=` (both cached
briefly — providers count calls — and a failing account is reported BESIDE the others), and `listDir` is
the op behind a file tree. They are for OTHER apps; this UI does not call them.

## Ops, answers, remotes

`GET /ops` lists the ops, `GET /manifest` is the live contract; answers are `{"ok":true,…,"data"}`, a
failure carries a Hebrew `error` plus `provider_error`, and `data.applied`
(`native`|`approximated`) says whether the provider really did it. The remote for any account is
`http://git:8978/git/<gh|gl|any|lc>/<account>/<owner>/<repo>.git` (`lc` = the forge); **never look for
a token** — there is none to find (contract §5a).

## Traps

- **A large clone depends on the client's body headers being forwarded.** `git` gzips its upload-pack
  request above a few hundred bytes (`Content-Encoding: gzip`); a proxy that rebuilds its header set
  drops it, GitHub answers a bare `HTTP 400` with an EMPTY body, and the failure is size-dependent —
  small repos clone, large ones cannot. Do not "tidy" that loop in `proxy.py`.
- **Forgejo splits file create/update**: `POST …/contents/<path>` creates, `PUT` updates and needs the
  blob `sha`. **`deleteRepo` on the forge is IMMEDIATE** — ask the owner first.
- Asymmetries: `draft` is GitHub-only (Forgejo: a `Draft:` prefix, `approximated`); merge method is
  per-call on GitHub/Forgejo but a project SETTING on GitLab; `deleteRelease` never deletes the tag.
- A read-only account refuses writes with 403 (a decision, not a bug); on 429 wait, don't loop.
- New REMOTE accounts are the owner's action in the UI; never paste a token on a command line — the
  forge is no exception. An expiring credential is not a broken one: read `state`/`reason` from
  `/connections` before calling a token dead.
- Memory is this deployment's constraint: a mirror costs its repository size on disk — check `df`
  before mirroring something large.
