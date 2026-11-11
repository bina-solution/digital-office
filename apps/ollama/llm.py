#!/usr/bin/env python3
"""llm.py — use this office's Ollama, or a linked office's, from the shell (DGO-1254): `./bbox ollama <verb>`.

    generate "<prompt>" -m <model> [--system "…"] [--max N] [--think]   one answer to one prompt (POST /api/generate)
    chat     "<message>" -m <model> [--system "…"] [--max N] [--think]  one turn of a chat           (POST /api/chat)
    embed    "<text>" -m <model>                                       the text's vector             (POST /api/embed)
    show     <model>                                                   what the model is             (POST /api/show)
    unload   <model>                                                   out of memory now             (keep_alive 0)
    every verb: [--office <office>] [--json] [--timeout SEC]; a text of "-" is read from stdin

Where it asks: this office's Ollama through its front (`ollama`, the Caddy that owns ollama:11434; the hook hands the
container in OLLAMA_FRONT) — busybox wget there, the body on stdin and then a file in the container (`--post-file`:
never an argument, so no size limit and nothing in `ps`); an HTTP error through the front says its status only (busybox
wget passes no body); with --office, a linked office's, through `bbox remote <office> ollama <path>`
(scripts/remote.py: the link's own door and token, the body on stdin), where Ollama's own words come back. Each inner
step holds the time limit itself (busybox `timeout` in the front, remote.py --timeout), so it ends on its own; this
process waits a little longer and never kills a group (a kill of `engine.sh exec`'s group can take the office's host
daemons with it, DGO-1783).
A pull or a removal is not here: the models an office keeps are its OLLAMA_PULL list, changed with the owner's
go-ahead (apps/ollama/AGENT.md), and `./bbox ollama models` / `loaded` read what it holds.

Exit 0 / 1 Ollama answered with an error, or did not answer / 2 usage / 3 no Ollama here (and no --office) / 130 ^C.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
VERBS = ("generate", "chat", "embed", "show", "unload")
DEFAULT_TIMEOUT = 300.0
#: the request, made by the front's busybox wget: $1 the time limit, $2 the path. The body arrives on stdin and goes to a
#: file in the container (`--post-file`: never an argument, so no size limit and nothing in `ps`), removed after;
#: busybox `timeout` holds the whole call to $1 inside the container. On an HTTP error busybox wget prints only
#: «server returned error: HTTP/1.1 NNN …», never the body — that line is what comes back here.
WGET = ('f="$(mktemp)" && cat > "$f" && timeout "$1" wget -q -O - --header "Content-Type: application/json" '
        '--post-file "$f" "http://127.0.0.1:11434$2"; rc=$?; rm -f "$f"; exit $rc')


class Failed(Exception):
    """Ollama did not answer, or answered with an error: one sentence for the person, exit 1. `status` is the HTTP
    status Ollama answered with, when it answered."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def parse(argv, stdin=None):
    stdin = sys.stdin if stdin is None else stdin
    ap = argparse.ArgumentParser(prog="bbox ollama", add_help=True)
    ap.add_argument("verb", choices=VERBS)
    ap.add_argument("text", nargs="?", default=None, help="the prompt / message / text, or the model for show|unload")
    ap.add_argument("-m", "--model")
    ap.add_argument("--system")
    ap.add_argument("--max", type=int, metavar="N", help="at most N tokens of answer (num_predict)")
    ap.add_argument("--think", action="store_true",
                    help="let a thinking model think first (off: its tokens go to the answer)")
    ap.add_argument("--office")
    ap.add_argument("--json", action="store_true", help="Ollama's whole answer, as it gave it")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, metavar="SEC")
    a = ap.parse_args(argv)
    if a.verb in ("show", "unload"):
        a.model = a.model or a.text
        if not a.model:
            ap.error(f"{a.verb} needs a model: bbox ollama {a.verb} <model> (bbox ollama models lists them)")
        return a
    if not a.model:
        ap.error(f"{a.verb} needs -m <model> (bbox ollama models lists them)")
    if a.text is None and stdin.isatty():
        ap.error(f'{a.verb} needs a text: bbox ollama {a.verb} "<text>" -m <model> (or "-" to read it from stdin)')
    if a.text in (None, "-"):
        a.text = stdin.read()
    if not a.text.strip():
        ap.error(f"{a.verb}: nothing to send")
    return a


def request(a):
    """(path, body) of the one call a verb makes — non-streaming, so the answer is one JSON document."""
    opts = {"num_predict": a.max} if getattr(a, "max", None) else {}
    # `think`: a thinking model (qwen3) otherwise spends the budget on its reasoning and answers nothing — measured
    # on the Dell, 24 tokens of qwen3:1.7b gave an empty response; with think false, «Ready.» in 1.9 s
    if a.verb == "generate":
        body = {"model": a.model, "prompt": a.text, "stream": False, "think": bool(a.think)}
        if a.system:
            body["system"] = a.system
    elif a.verb == "chat":
        msgs = ([{"role": "system", "content": a.system}] if a.system else []) + [{"role": "user", "content": a.text}]
        body = {"model": a.model, "messages": msgs, "stream": False, "think": bool(a.think)}
    elif a.verb == "embed":
        return "/api/embed", {"model": a.model, "input": a.text}
    elif a.verb == "show":
        return "/api/show", {"model": a.model}
    else:                                       # unload: a generate with no prompt and keep_alive 0
        return "/api/generate", {"model": a.model, "keep_alive": 0}
    if opts:
        body["options"] = opts
    return ("/api/generate" if a.verb == "generate" else "/api/chat"), body


def wget_status(said):
    """The HTTP status in busybox wget's «server returned error: HTTP/1.1 NNN …», or None."""
    import re
    m = re.search(r"HTTP/\d(?:\.\d)?\s+(\d{3})", said)
    return int(m.group(1)) if m else None


def call(path, body, office, timeout, run=subprocess.run):
    """Ollama's answer to POST <path> as a dict — here through the front, or through the link to <office>."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if office:
        argv = [sys.executable, str(REPO / "scripts" / "remote.py"), office, "ollama", path, "-d", "@-",
                "--json", "--timeout", str(timeout)]
        p = run(argv, input=data, capture_output=True, timeout=timeout + 60)
        out, err = p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
        try:
            env = json.loads(out)
        except ValueError:
            said = (err or out or "").strip().splitlines()
            raise Failed(f"the ollama of {office} was not reached: {said[-1] if said else 'no answer'}")
        status, text = env.get("status"), env.get("body") or ""
    else:
        front = os.environ.get("OLLAMA_FRONT", "")
        if not front:
            raise Failed("no ollama on this office — `./bbox apps enable ollama && ./bbox run`, or --office <office>")
        p = run(["docker", "exec", "-i", front, "sh", "-c", WGET, "wget", str(max(1, int(timeout))), path],
                input=data, capture_output=True, timeout=timeout + 30)
        text = (p.stdout or b"").decode("utf-8", "replace")
        if p.returncode != 0 or not text.strip():
            said = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            line = said[-1] if said else ""
            status = wget_status(line)
            if status == 404:                # on these endpoints Ollama's 404 is a model it does not hold
                raise Failed("no such model on this office (`./bbox ollama models` lists them) — HTTP 404", status)
            if status is not None:
                raise Failed(f"ollama answered HTTP {status} (busybox wget passes no more of its answer; asked "
                             f"with --office from another office, Ollama's own words come back)", status)
            if p.returncode in (124, 143):
                raise Failed(f"ollama did not answer in {int(timeout)} s")
            raise Failed(f"ollama on this office did not answer: {line or 'no answer'}"
                         + (f" (exit {p.returncode})" if p.returncode else ""))
        status = 200
    try:
        answer = json.loads(text) if text.strip() else {}
    except ValueError:
        answer = {"error": text.strip()[:300]}
    if not isinstance(answer, dict):
        answer = {"error": text.strip()[:300]}
    if status != 200 or "error" in answer:
        raise Failed(f"ollama: {answer.get('error') or text.strip()[:300] or 'no answer'}"
                     + (f" (HTTP {status})" if status not in (200, None) else ""),
                     status if isinstance(status, int) else None)
    return answer


def refuses_think(message):
    """Ollama's words for a model (or a server) that takes no `think`."""
    m = message.lower()
    return "think" in m and ("support" in m or "unknown" in m or "invalid" in m)


def say(verb, model, answer):
    """The lines a person reads for one answer."""
    if verb in ("generate", "chat"):
        text = str(answer.get("response", "") if verb == "generate"
                   else (answer.get("message") or {}).get("content", "")).strip()
        if text:
            return [text]
        why = "it stopped at --max" if answer.get("done_reason") == "length" else "the model said nothing"
        return [f"({model} answered no text: {why}; a larger --max, or without --think)"]
    if verb == "embed":
        vecs = answer.get("embeddings") or []
        v = vecs[0] if vecs else []
        head = ", ".join(f"{x:.4f}" for x in v[:4])
        return [f"{model}: {len(v)} dimensions [{head}{', …' if len(v) > 4 else ''}]"]
    if verb == "show":
        d, info = answer.get("details") or {}, answer.get("model_info") or {}
        ctx = next((v for k, v in info.items() if k.endswith(".context_length")), None)
        return [f"{model}: {d.get('family') or '?'} · {d.get('parameter_size') or '?'} · "
                f"{d.get('quantization_level') or '?'}" + (f" · context {ctx}" if ctx else "")]
    if answer.get("done") or answer.get("done_reason") == "unload":
        return [f"{model}: out of memory now"]
    return [f"{model}: {json.dumps(answer, ensure_ascii=False)[:300]}"]


def main(argv, run=subprocess.run, out=sys.stdout, err=sys.stderr, stdin=None):
    try:
        a = parse(argv, stdin)
    except SystemExit as e:
        return 2 if e.code not in (0, None) else 0
    except KeyboardInterrupt:                  # ^C while the text was being read from stdin
        print("stopped", file=err)
        return 130
    path, body = request(a)
    try:
        try:
            answer = call(path, body, a.office, a.timeout, run=run)
        except Failed as e:
            # Ollama's words (through the link), or — through the front, whose wget passes no words — its 400
            # — and only when think was asked for: Ollama refuses `think: true`, never `think: false`
            local_400 = not a.office and e.status == 400
            if body.get("think") is not True or not (refuses_think(str(e)) or local_400):
                raise
            print(f"({a.model} takes no `think`: asked again without it)", file=err)
            body.pop("think")
            answer = call(path, body, a.office, a.timeout, run=run)
    except Failed as e:
        print(str(e), file=err)
        return 3 if (not a.office and not os.environ.get("OLLAMA_FRONT")) else 1
    except subprocess.TimeoutExpired:
        print(f"ollama did not answer in {int(a.timeout)} s", file=err)
        return 1
    except OSError as e:
        print(f"ollama could not be asked: {e.strerror or e}", file=err)
        return 1
    except KeyboardInterrupt:
        print("stopped", file=err)
        return 130
    if a.json:
        print(json.dumps(answer, ensure_ascii=False), file=out)
    else:
        for line in say(a.verb, a.model, answer):
            print(line, file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
