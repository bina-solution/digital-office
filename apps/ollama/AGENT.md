# Operating «מודלים מקומיים» (the `ollama` app)

Local language models on the office's own hardware: Ollama, behind the office's SSO at `/a/ollama/`.
bina-ds can route to it, and the operatives are injected on its routes. In the herd it belongs on
the Dell (`apps/computers/herd.yaml`). It ships off.

## Three services: the front, the engine and the watcher (EXU-21, DGO-1797)

`ollama` is a small Caddy front (`front/Caddyfile`). It owns the name and the port everyone uses. A browser's `/`
gets the models screen (`front/index.html`); every other request passes through to the engine, `ollama-engine`
(Ollama itself, container `ollama-engine-<office>`), streaming. To exec inside Ollama, use the service `ollama-engine`
(`dcx exec -T ollama-engine …`) or the container `ollama-engine-<office>`, never `ollama`. The old container name
`ollama-<office>` no longer exists, so a stale command fails instead of reaching Caddy.

`ollama-watch` (`watch/watch.py`) puts what the models do in «כל מקביל», row «מודלים מקומיים»: a bar for each
model while it is in memory (from `/api/ps`; «נשאר בזיכרון» when keep-alive is -1) and a bar for each
chat/generate/embed turn (from the front's access log, `/log/access.json`). It only publishes the flow.

## From inside the office network (`http://ollama:11434`, capability `llm-local`)

```bash
GET  /api/tags        # the models it holds
GET  /api/ps          # what is loaded now
POST /api/generate | /api/chat | /api/embeddings   # use a model
```

From the shell, two reads: `./bbox ollama models` (what it holds) and `loaded` (what is in memory
now); and to use a model, `generate`/`chat "<text>" -m <model>` (thinking off unless `--think`), `embed`, `show
<model>`, `unload <model>` — each with `--office <office>` for a linked office's Ollama (apps/ollama/llm.py). The
models it keeps are the list in `OLLAMA_PULL` (`.env`). At start it pulls any that are missing,
and a failed pull is retried at the next start.

## Rules

- Using a model is free of money but not of the machine: a large one takes the host's memory and
  CPU. Check load before a long run.
- **Add a model by adding it to `OLLAMA_PULL`**, with the owner's go-ahead, because a pull is
  gigabytes. Don't call `/api/pull` or `/api/delete` yourself.
- Any container on the office network can reach it, with no key: keep it on the internal network.

## Traps

- `OLLAMA_NUM_THREAD=2` is fixed in the compose, and the context is 32,768 tokens. A small GPU needs
  16,384.
- README.md names hostnames and an override file from an older deployment. The compose is current.

Gates: G23 (a gallery app ships disabled).
