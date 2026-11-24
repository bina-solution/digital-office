# Operating «קליטת אירועי GitHub» (the `github-hooks` app)

The public door GitHub posts its webhook events to (DGO-2155). It keeps each delivery exactly as it came, answers
GitHub within milliseconds, and decides nothing. It knows no secret, no token and no account. The `git` app, which
the internet never reaches, verifies each delivery's HMAC with the GitHub App's `webhook_secret` from the vault,
drops duplicates, and records the event (apps/git/webhooks.py).

Disabled by default. An office enables it only when it takes GitHub's events: vps1, once the GitHub App exists
(DGO-2144). It also needs the router named in that office's `public:` and `GITHUB_APP_IDS` in its `.env`.

## Doors

```text
POST /github/webhook     :8979, GitHub's (router github-hooks, auth none). 202 kept, 200 duplicate
GET  /healthz            :8979, the container's health
GET  /internal/batch     :8980, git's: the oldest deliveries (≤100, ≤2 MB), each with its spool name
POST /internal/ack       :8980, git's: {"drop": [names], "reject": [names]}
```

No router names :8980, so it is reached on the office network only. It answers the `git` service's address alone,
and only with the drain's header `X-Webhook-Drain: git`. git's smart-HTTP proxy also calls out from that address, to
bases that accounts name, and it never sends that header. Anyone else gets 403. git logs a 403 as «REFUSES the drain»,
a fault: the queue fills behind it. An ack names files by the spool's own pattern only, so it can never reach outside
the spool. Each door takes 4 requests at once.

## What the public door refuses (before anything is written)

- every path and method but `POST /github/webhook`;
- a body over 1 MB (413), one that does not start with `{`, or one with a raw control byte (415); the body is never
  parsed, and is kept as UTF-8 (under twice its size on disk);
- a delivery without GitHub's headers, or with an id that is not a GUID (400);
- an App id the office did not declare in `GITHUB_APP_IDS` (403);
- more than 50 posts a second (429), more than 4 at once (503), a full spool (507: 2000 files or 100 MB);
- a body that does not arrive within 10 s, which closes the connection.

## Rules

- Never put a secret in this app's environment or spool. Verification is git's, with the vault's key.
- GitHub does not redeliver on its own. A delivery refused here (507, 503) is recovered through the App's
  «redeliver» API, never by loosening a limit.
- The spool is `data/github-hooks/spool`. `.rejected/` holds the newest 200 that failed their signature, for a
  person to read. Nothing acts on them.
- To read the drain's state: `./bbox remote <office> git /api/webhooks`.

## Proof

`python3 apps/github-hooks/test_intake.py` drives the public door and git's door on loopback, with a temp spool.
`python3 apps/git/tests/test_webhooks.py` drives the drain through the same door, from delivery to a recorded
event.
