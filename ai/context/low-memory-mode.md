# Low-memory mode — free RAM to stabilize the stack (option when hitting memory limits)

## Why
The full stack (n8n + 2 workers + supabase + authentik + glitchtip + apitools + browser42 + whatsapp)
can overcommit the memory available to the engine. Under memory pressure the engine's
networking/embedded DNS gets flaky — observed as `"DNS server returned an error"` / `EAI_AGAIN` on
googleapis.com calls and intermittent Docker-API 500s. `supabase-kong` runs pinned at ~99% of its 512 MB
limit (the supabase API gateway), so supabase calls degrade first. Freeing host RAM gives the engine
headroom and reduces the flakiness. (See also the dns fix in `platform-base/n8n/docker-compose.yml` —
pinned 8.8.8.8/1.1.1.1 on n8n+workers.)

**On Windows, the engine's memory ceiling is WSL's, not Docker Desktop's.** The project engine runs
inside the `Ubuntu` WSL distro (see [running-on-wsl.md](running-on-wsl.md)), so the limit is whatever
`C:\Users\<you>\.wslconfig` grants the WSL VM — there is no Docker Desktop "Settings → Resources"
slider in this setup, and changing one would not affect this stack.

## When to use
Hitting flakiness that correlates with memory pressure: container OOM/restarts, kong at limit,
`docker stats` showing the host near full, repeated DNS/500 errors during INDOX runs.

## What to stop (NON-essential for INDOX backend processing — INDOX needs n8n+workers, supabase, redis, apitools)
```
docker stop \
  browser42-browser-shlomo-laptop browser42-mcp-shlomo-laptop \
  browser42-caddy-shlomo-laptop browser42-reaper-shlomo-laptop \
  chat \
  homepage-shlomo-laptop redisinsight-shlomo-laptop portainer-shlomo-laptop
```
Further (only if still pressured — these ARE used elsewhere, stop knowingly):
- `glitchtip-shlomo-laptop glitchtip-worker-shlomo-laptop glitchtip-postgres-shlomo-laptop glitchtip-valkey-shlomo-laptop` (error tracking)
- ⚠️ `authentik-server-/worker-/postgres-…` — **STOPPING AUTHENTIK 404s EVERY `*.localhost` APP** (it's the Traefik forward-auth outpost): supabase.localhost / n8n.localhost / etc. all return 404 while it's down. Only stop authentik if you do NOT need the web UIs. To restore: `docker start authentik-postgres-… && sleep 3 && docker start authentik-server-… authentik-worker-… authentik-bootstrap-…`, wait ~30s for the outpost to register (you'll see 502 briefly, then 200). INDOX *backend* processing (n8n→supabase, poll, scanners) does NOT need authentik — only the browser-facing UIs do.

## Check
```
docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' | sort -t$'\t' -k3 -rh
```
Watch for any container near 100% of its own limit (esp. supabase-kong) and total host headroom.

## Restore
```
docker compose up -d        # brings stopped services back per compose.yml
```
KEEP RUNNING for INDOX: n8n, n8n-worker-1/2 (+runners), n8n-postgres, supabase-* (db/kong/rest/meta/storage/studio),
redis, apitools. Never stop these during an INDOX run.

## Better long-term fix
Raise the WSL VM's memory in `C:\Users\<you>\.wslconfig` (`[wsl2] memory=`) if the host has it to
spare — that is the engine's real ceiling on Windows; then `wsl --shutdown` to apply. Or trim
per-service `deploy.resources.limits` so committed memory fits the host.
