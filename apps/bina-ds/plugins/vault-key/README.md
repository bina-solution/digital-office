# vault-key — the office vault as a live credential source

The harness's credential service (`credentials`) is mounted by `@deepseek-ai/dsh-credentials-local`:
settings name a REFERENCE (`DEEPSEEK_API_KEY`), the file `.credentials.yaml` (or the launch
environment, or `.env`) holds its value, and every provider adapter resolves that reference **per
request** — the seam's own contract, so a changed value reaches the next operation with no restart.

This plugin **is** that service. It keeps the file-backed behaviour exactly as shipped and adds one
value shape:

```
refs:
  DEEPSEEK_API_KEY: vault:deepseek-key      # a POINTER at one connection, not a key
```

For such a reference the value is fetched from the office's credential plane (`connections`) at the
moment it is used, through the **broker** (`POST /api/broker/lease`), in this container's own name —
the broker grants only what `apps/bina-ds/app.json` declares (`deepseek-key`, `openai-key`,
`anthropic-key`) and audits every grant. Nothing is written back: the key lives in the vault, in this
process's short cache (`cacheSeconds`), and nowhere else. It never lands in `.credentials.yaml`, in
the harness volume, in this browser, or in a log line.

## Why, when `inject.sh` already injects secrets

`inject.sh` hands every app its declared connections as environment variables at **boot**. That is a
snapshot: rotating a key needs a container restart, the Models page cannot show where a key comes
from, and a key typed into that page is a copy on the harness volume instead of the vault. This adds
the live half (owner, 2026-11-03: «שאפלקציית בינה יכולה לבחור מתוך אפלקציית סודות … ולהזרים את המפתח
מהסודות»).

## Precedence

A LITERAL stored value keeps the shipped layering untouched: launch environment, then
`.credentials.yaml`, then `.env`. Only a `vault:` value changes the answer, and only for itself — an
operator who bound a reference to a connection meant the vault, so the vault wins over a stale copy
in the launch environment. Removing the binding (`unset`) leaves the reference unconfigured: a
pointer is the whole value, so there is nothing to fall back to.

## The screen

`lib/client.js` registers into the Models page's own extension seat,
`settings.models.provider-card` (keyed by the settings namespace, declared by
`@deepseek-ai/dsh-client-ui-settings-models`), and adds one row per provider card:

```
מקור המפתח   מהסודות של הלשכה: DeepSeek API key   deepseek-key        [בחר מהסודות] [נתק]
```

The pick writes `vault:<connection-id>` through the harness's own `credentials/set` — the same route
a pasted key takes — so no new HTTP surface and no value ever crosses back into the browser. The
binding is **read back from the host**: `describe()` reports `source: "office-vault:<connection>"`,
which is the one credential field the harness's API passes through unchanged, so the row is right
after a reload and after another tab changed it.

Which reference a card owns is the table at the top of `lib/client.js` (`OFFERS`), spelled the way
the page derives it (`<ROUTE>_API_KEY`). A provider route that is not in that table renders nothing —
a button that wrote to a reference nobody reads would be worse than no button. Adding a provider's
key is one entry there, plus the connection in `apps/bina-ds/app.json`.

## Failure behaviour

- The vault cannot be reached or refuses the lease → `resolve()` **throws** with the vault's reason
  in the message (the adapter surfaces it), rather than reporting a missing credential that sends
  someone hunting for the wrong thing.
- The connection holds nothing (a placeholder, or nobody filled it in) → the credential reads as
  **unconfigured**, and `describe()` logs the connection name.

## Configuration (`apps/bina-ds/harness/profile/cordis.patch.yml`)

| key | default | what it is |
|---|---|---|
| `vaultUrl` | `http://connections:8990` | the credential plane on the office network |
| `service` | `bina-ds` | this app's compose service — the broker's cross-check |
| `cacheSeconds` | `30` | how long one connection's lease is reused |
| `timeoutMs` | `4000` | one lease's whole timeout |

## Tests

```bash
node --test apps/bina-ds/plugins/vault-key/test/
```
