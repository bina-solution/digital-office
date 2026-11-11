# Operating `https-redirect` — «הפניה ל-HTTPS» (DGO-1595)

The office's answer on **port 80 of a server office**: `308` to the same host and path over https,
and nothing else. It is not a screen, it has no host of its own, and nothing a person browses ever
reaches it directly — traefik asks it, once per request that arrives on the `web` entrypoint.

## Why it exists (measured, 2026-11-09)

Every app publishes a `-http` router on traefik's `web`, so `http://n8n.exampleu…/` answered 200 with
the editor, `/rest/settings` 200 to anyone, and `http://meet.exampleu…/` 200 (Jitsi) — in cleartext,
with no HSTS anywhere. traefik v3.3's own redirect middlewares (`redirectScheme`, `redirectRegex`,
the entrypoint redirection) answer **301 or 302 only** — measured on this engine, and v3.5's
reference has no status-code field either. A 301 turns a POST into a GET at the client, so a webhook
that had been configured with `http://` would arrive as nothing. 308 is the only status that keeps
the method and the body.

## How it is wired (and what to check when it is not working)

```
request → traefik `web` → router `dgo-port80` (file provider) → forwardAuth → https-redirect:8079
                          rule: PathPrefix(`/`) && !PathPrefix(`/.well-known/acme-challenge/`)
                          priority 1000000, so no app's `-http` router outranks it
```

- The router and its `forwardAuth` middleware are **rendered by the compiler** into
  `platform-base/traefik/config/zz-https.yaml`, and only when this office is a SERVER office
  (`DEPLOYMENT_DOMAIN` has a dot and the edge has a certificate resolver). A `*.localhost` office
  has no certificate — there port 80 IS the office, and nothing may redirect it.
- `/.well-known/acme-challenge/` is deliberately NOT redirected: HTTP-01 renewals are answered by
  traefik on that entrypoint, and a redirect there would break every renewal on the office.
- The `Location` is built from traefik's own `X-Forwarded-Host`/`X-Forwarded-Uri` (a client cannot
  set them: traefik rebuilds them from the request). No host → 400, never a redirect to nowhere.

## Traps

- **On a server office this is the first thing a scanner sees**: `http://<app>.<domain>/` must answer
  308, never 200 with app content. That is the whole test (`curl -sI http://n8n.<domain>/`).
- A 308 to a host that does not serve https (a `*.localhost` name on that machine) is a dead end —
  which is why the router exists only where a certificate does.
- `/healthz` on this service answers `{"ok":true}` and is NOT redirected; the container's own
  healthcheck uses it through loopback.
