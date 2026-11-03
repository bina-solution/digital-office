# Operating «מעקב שגיאות» (the `glitchtip` app)

The office's error tracking: GlitchTip, a Sentry-compatible service. Apps send their exceptions to it
through a DSN. The notifications app polls its unresolved issues every minute and turns them into
notices. It is a gallery app, off by default. Its projects are compiled from each app's
`observability` block into `.generated/glitchtip.projects.yml`.

## From the server's shell

```bash
./bbox glitchtip verify            # provisioned: the poller's token is in .env
./bbox glitchtip prepare           # provision org, projects, DSNs and the poller token (runs on every bbox run);
                                   # when the glitchtip container is not running it STARTS its four
                                   # services first and waits up to 240 s for them (hooks/prepare)
./bbox rename-address --dry-run <old-domain> <new-domain>   # a domain move, previewed for EVERY enabled app, this one included
```

`backup` and `restore` are called by the deployment archive, never by hand.

## From inside the office network (`http://glitchtip:8000`)

```bash
GET /_health/
GET /api/0/organizations/<org>/issues/?query=is:unresolved     # Authorization: Bearer <token>
```

Use the read-only poller token (`*:read`); it is in `.env` as `GLITCHTIP_API_TOKEN`. Never print it.
An app reports through its DSN, which `prepare` writes into `.env` as `<PROJECT>_SENTRY_DSN`.

## Rules

- Reading issues is free. Resolve an issue in GlitchTip and its notice turns read by itself.
- **`prepare` and `push` rewrite `.env` lines** (the DSNs, the token, the admin password) and create
  the superuser, the org and the projects. They are part of bring-up, so don't run them to "fix"
  something.
- `bbox rename-address` is office-wide: it runs every enabled app's `hooks/rename-address`, and here
  it changes live user addresses. Preview it with `--dry-run`, and run it only for a domain move the
  owner made.
- `restore` drops and recreates the `glitchtip` database.

## Traps

- **No SSO, and sign-up is open by default** (`GLITCHTIP_ENABLE_REGISTRATION`, true): anyone who
  reaches the host can make an account. Don't publish its host.
- **The admin password's one source is `.env`.** Every `bbox run` sets it back from there, so change
  it in `.env`, not on GlitchTip's own screen.
- A DSN is derived from `SECRET_KEY` and the project. Rotating the secret changes every DSN, and
  every app then needs a restart.
- DSNs point at the internal `glitchtip:8000`. An event sent to an outside host is dropped.
- E-mail is log-only by default (`consolemail://`): GlitchTip mails nobody.
- README.md and blueprint.yml name scripts that no longer exist.

Gates: no registered gate names this app yet (the inventory's gate cell); `bbox glitchtip verify`
checks provisioning.
