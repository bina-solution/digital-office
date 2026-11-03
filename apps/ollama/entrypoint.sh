#!/bin/sh
# The Ollama app's own start: serve, then make sure every model the OFFICE declares is present.
#
# OLLAMA_PULL (.env, a space- or comma-separated list of library tags, e.g. `lfm2.5:8b`) is the
# declaration; nobody runs `ollama pull` by hand. Only a MISSING model is pulled: a model that is
# there is left exactly as it is, so a restart never swaps it for a newer upload under the same tag.
# A pull that fails (no internet, an unknown tag) is said and tried again on the next start, and an
# office that is offline serves what it has (DGO-825). The pulls run beside the server, so a stop is
# answered at once even in the middle of a download of gigabytes.
set -u
ollama serve &
serve=$!
pulls=""
trap 'kill -TERM "$serve" $pulls 2>/dev/null; wait "$serve"; exit 0' TERM INT
(
  i=0
  until ollama list >/dev/null 2>&1; do
    i=$((i + 1)); [ "$i" -lt 120 ] || { echo "[ollama] the server did not answer in 120 s — not pulling" >&2; exit 0; }
    sleep 1
  done
  for m in $(printf '%s' "${OLLAMA_PULL:-}" | tr ',' ' '); do
    if ollama show "${m}" >/dev/null 2>&1; then echo "[ollama] declared model ${m}: present"; continue; fi
    echo "[ollama] declared model ${m}: pulling"
    # the pull draws a progress spinner; the log gets one line per model, and the error when it fails
    # (the container has no TMPDIR, so it is /tmp there; its test gives each run a directory of its own)
    log="${TMPDIR:-/tmp}/ollama-pull.log"
    if ollama pull "${m}" >"${log}" 2>&1; then
      echo "[ollama] declared model ${m}: pulled"
    else
      echo "[ollama] ${m} could not be pulled now (offline, or no such tag) — tried again on the next start: $(tail -c 300 "${log}" | sed 's/\x1b\[[0-9;?]*[A-Za-z]//g' | tr -d '\r' | tail -1)" >&2
    fi
  done
) &
pulls=$!
wait "$serve"
