"""cli — apitools' engines (speech, OCR), for agents and for the person at the server's shell. Reads only.

The hooks pipe THIS file into the apitools container (`dcx exec -T apitools python - <verb> <
apps/apitools/cli.py`), so it runs from the checkout with no image rebuild. The web container answers
OCR and the ledger on 127.0.0.1:8080; the speech service is `apitools-asr:8987` on the same network.

    speech-health            the speech model's state (loaded or not), the queue's depth, the limits
    speech-jobs              the 20 most recent transcription jobs, and the queue's counts
    speech-models            the models it can run (ivrit, whisper), and which one is the default
    ocr-health               the web container's health (storage writable; it does not prove the OCR key).
                             When no worker is free within the minute it asks the master's health
                             sidecar (:8082) and says the pool is busy — busy, not down

Transcribing, OCR and every ledger call are the apps' own work, through their API (AGENT.md); the
documents themselves are read with `bbox my-docs`.
"""
import json
import os
import socket
import sys
import urllib.error
import urllib.request

WEB = "http://127.0.0.1:8080"
ASR = "http://apitools-asr:8987"
ROUTES = {"speech-health": ASR + "/speechHealth", "speech-jobs": ASR + "/speechJobs",
          "speech-models": ASR + "/speechModels", "ocr-health": WEB + "/health"}
# gunicorn.conf.py: the master answers here whatever the workers are doing — what the health checks ask
SIDECAR = f"http://127.0.0.1:{os.getenv('GUNICORN_HEALTH_PORT', '8082')}/"


def busy():
    """True when the master's sidecar answers: /health timed out on a full worker pool, not a dead one."""
    try:
        with urllib.request.urlopen(SIDECAR, timeout=5) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def main(argv):
    url = ROUTES.get(argv[0] if argv else "")
    if not url:
        sys.exit(__doc__)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"apitools: {e.reason} (HTTP {e.code}) from {url}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        slow = (TimeoutError, socket.timeout)         # one class from 3.10; two before
        timed_out = isinstance(e, slow) or isinstance(getattr(e, "reason", None), slow)
        if argv[0] == "ocr-health" and timed_out and busy():      # refused or reset is not "busy"
            sys.exit(f"apitools: every worker is busy — {url} found none free in 60 s, while the master's "
                     f"health sidecar ({SIDECAR}) answers: the container is up, not down")
        sys.exit(f"apitools: {url} does not answer ({getattr(e, 'reason', e)})")
    try:
        print(json.dumps(json.loads(body or b"{}"), ensure_ascii=False, indent=1))
    except ValueError:
        print(body.decode("utf-8", "replace"))


if __name__ == "__main__":
    main(sys.argv[1:])
