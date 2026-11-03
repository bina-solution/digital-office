# Operating «מודלים מקומיים» (the `ollama` app)

Local language models on the office's own hardware: Ollama, behind the office's SSO at `/a/ollama/`.
bina-ds can route to it, and the operatives are injected on its routes. In the herd it belongs on
the Dell (`apps/computers/herd.yaml`). It ships off.

## From inside the office network (`http://ollama:11434`, capability `llm-local`)

```bash
GET  /api/tags        # the models it holds
GET  /api/ps          # what is loaded now
POST /api/generate | /api/chat | /api/embeddings   # use a model
```

From the shell, two reads: `./bbox ollama models` (what it holds) and `loaded` (what is in memory
now). The models it keeps are the list in `OLLAMA_PULL` (`.env`). At start it pulls any that are missing,
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
