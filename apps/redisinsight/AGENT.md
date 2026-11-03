# Operating «מפקח Redis» (the `redisinsight` app)

RedisInsight, a browser and debugger for the office's Redis (the cache and the job queues), behind
the office's SSO, opened in its own tab. It is **retired in the herd** (`apps/computers/herd.yaml`:
no office runs it), and it ships off. No connection is pre-wired: a person adds `redis:6379` with
`REDIS_PASSWORD` (the connection `redis-password`).

## Rules

- **Agents do not use it.** To read Redis, use `redis-cli` inside the redis container through
  `./scripts/dc`.
- It connects with the full password and has no read-only mode. A `DEL` or a `FLUSH` here hits the
  shared Redis, which holds n8n's queue and authentik's data (database 1). Only on the owner's words.
- Uninstalling it asks about its volume (`on_uninstall: prompt`).

Gates: G23 (a gallery app ships disabled).
