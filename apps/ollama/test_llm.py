"""test_llm.py — `./bbox ollama generate|chat|embed|show|unload` (llm.py, DGO-1254) against a faked transport.

    python3 apps/ollama/test_llm.py

What is asked: each verb makes ONE non-streamed call with the body Ollama's API names (generate and chat with think
false unless --think, --max as num_predict, --system; embed's input; show's model; unload = keep_alive 0), through
this office's front — the request script run in the front's container, the body on nc's stdin and never an argument,
its Content-Length in BYTES (Hebrew is two) — or with --office through scripts/remote.py; the answer is said in a
line (an empty answer says why); --json is Ollama's whole answer; Ollama's own error comes back from either path;
a docker exec that fails, a link that does not answer and a timeout are one sentence and exit 1, never a success;
no Ollama here and no --office is exit 3; a model that refuses `think` is asked once more without it, and the person
is told; a missing model or text — or a text expected from a terminal — is exit 2.
"""
import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm  # noqa: E402


def ok(body):
    """What the front's wget gives back for a 200: the body on stdout."""
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def wget_error(status, reason="X"):
    """What busybox wget says for an HTTP error: one line on stderr, no body, exit 1."""
    return subprocess.CompletedProcess([], 1, b"", f"wget: server returned error: HTTP/1.1 {status} {reason}\n".encode())


class Transport:
    """A fake subprocess.run: records each call and answers from a queue. Local answers are raw HTTP (bytes) or a
    CompletedProcess; remote answers are (status, Ollama answer)."""

    def __init__(self, *answers, local=False):
        self.answers, self.local, self.calls = list(answers), local, []

    def __call__(self, argv, input=None, capture_output=True, timeout=None):
        self.calls.append((argv, json.loads(input.decode("utf-8"))))
        a = self.answers.pop(0)
        if isinstance(a, subprocess.CompletedProcess):
            return a
        if self.local:
            return subprocess.CompletedProcess(argv, 0, a, b"")
        status, body = a
        text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        env = {"url": "http://ollama.x:9003/x", "method": "POST", "status": status, "body": text}
        return subprocess.CompletedProcess(argv, 0, json.dumps(env).encode(), b"")


class Stdin(io.StringIO):
    def __init__(self, text="", tty=False):
        super().__init__(text)
        self.tty = tty

    def isatty(self):
        return self.tty


def run(argv, transport, front="", stdin="", tty=False):
    out, err = io.StringIO(), io.StringIO()
    old = os.environ.get("OLLAMA_FRONT")
    os.environ["OLLAMA_FRONT"] = front
    try:
        with contextlib.redirect_stderr(err):
            rc = llm.main(argv, run=transport, out=out, err=err, stdin=Stdin(stdin, tty))
    finally:
        if old is None:
            os.environ.pop("OLLAMA_FRONT", None)
        else:
            os.environ["OLLAMA_FRONT"] = old
    return rc, out.getvalue(), err.getvalue()


class Requests(unittest.TestCase):
    def test_generate_through_the_link(self):
        t = Transport((200, {"response": "Ready.", "done": True, "done_reason": "stop"}))
        rc, out, _ = run(["generate", "Say ready", "-m", "qwen3:1.7b", "--max", "12", "--office", "dell"], t)
        self.assertEqual((rc, out), (0, "Ready.\n"))
        argv, body = t.calls[0]
        self.assertEqual(argv[2:7], ["dell", "ollama", "/api/generate", "-d", "@-"])   # the body on stdin
        self.assertEqual(body, {"model": "qwen3:1.7b", "prompt": "Say ready", "stream": False, "think": False,
                                "options": {"num_predict": 12}})

    def test_chat_with_a_system_line_and_think_on(self):
        t = Transport((200, {"message": {"role": "assistant", "content": "שלום"}, "done": True}))
        rc, out, _ = run(["chat", "היי", "-m", "m", "--system", "ענה בעברית", "--think", "--office", "dell"], t)
        self.assertEqual((rc, out), (0, "שלום\n"))
        body = t.calls[0][1]
        self.assertEqual(body["messages"], [{"role": "system", "content": "ענה בעברית"}, {"role": "user", "content": "היי"}])
        self.assertIs(body["think"], True)

    def test_embed_show_unload(self):
        t = Transport((200, {"embeddings": [[0.1, -0.2, 0.3, 0.4, 0.5]]}))
        rc, out, _ = run(["embed", "text", "-m", "m", "--office", "dell"], t)
        self.assertEqual(t.calls[0][1], {"model": "m", "input": "text"})
        self.assertIn("5 dimensions [0.1000, -0.2000, 0.3000, 0.4000, …]", out)
        t = Transport((200, {"details": {"family": "qwen3", "parameter_size": "2.0B", "quantization_level": "Q4_K_M"},
                             "model_info": {"qwen3.context_length": 40960}}))
        rc, out, _ = run(["show", "qwen3:1.7b", "--office", "dell"], t)
        self.assertEqual(out, "qwen3:1.7b: qwen3 · 2.0B · Q4_K_M · context 40960\n")
        t = Transport((200, {"model": "m", "done": True, "done_reason": "unload"}))
        rc, out, _ = run(["unload", "m", "--office", "dell"], t)
        self.assertEqual((rc, out), (0, "m: out of memory now\n"))
        self.assertEqual(t.calls[0][1], {"model": "m", "keep_alive": 0})

    def test_through_this_offices_front(self):
        t = Transport(ok({"response": "ok", "done": True}), local=True)
        rc, out, _ = run(["generate", "שלום", "-m", "m"], t, front="ollama-screen-local")
        self.assertEqual((rc, out), (0, "ok\n"))
        argv, body = t.calls[0]
        self.assertEqual(argv[:5], ["docker", "exec", "-i", "ollama-screen-local", "sh"])
        self.assertEqual(argv[-1], "/api/generate")
        self.assertNotIn("שלום", " ".join(argv))                    # the prompt travels on stdin

    def test_the_request_script_itself(self):
        """The real WGET script under sh, with a stand-in wget and timeout: the limit reaches timeout, the body reaches
        wget as a FILE (byte-exact: quotes, $(id), backticks, Hebrew, a newline) and never as an argument, and the
        file is gone afterwards."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d) / "tmp"
            tmp.mkdir()
            (pathlib.Path(d) / "timeout").write_text(f'#!/bin/sh\necho "$1" > "{d}/limit"\nshift\nexec "$@"\n')
            (pathlib.Path(d) / "wget").write_text(
                f'#!/bin/sh\nprintf "%s\\n" "$@" > "{d}/args"\n'
                'while [ $# -gt 0 ]; do [ "$1" = --post-file ] && cp "$2" "' + d + '/posted"; shift; done\n'
                'printf "{}"\n')
            for f in ("timeout", "wget"):
                (pathlib.Path(d) / f).chmod(0o755)
            body = json.dumps({"prompt": 'a "quote", $(id) `x` and עברית\nline'}, ensure_ascii=False).encode("utf-8")
            p = subprocess.run(["sh", "-c", llm.WGET, "wget", "9", "/api/generate"], input=body, capture_output=True,
                               env={**os.environ, "PATH": f"{d}:{os.environ['PATH']}", "TMPDIR": str(tmp)})
            self.assertEqual((p.returncode, p.stdout), (0, b"{}"), p.stderr)
            self.assertEqual(pathlib.Path(d, "limit").read_text().strip(), "9")
            args = pathlib.Path(d, "args").read_text()
            self.assertIn("http://127.0.0.1:11434/api/generate", args)
            self.assertNotIn("עברית", args)
            self.assertEqual(pathlib.Path(d, "posted").read_bytes(), body)
            self.assertEqual(list(tmp.iterdir()), [])               # the body's file is removed

    def test_a_prompt_from_stdin_and_json(self):
        t = Transport((200, {"response": "x", "done": True, "eval_count": 3}))
        rc, out, _ = run(["generate", "-", "-m", "m", "--json", "--office", "dell"], t, stdin="from stdin\n")
        self.assertEqual(t.calls[0][1]["prompt"], "from stdin\n")
        self.assertEqual(json.loads(out)["eval_count"], 3)


class Answers(unittest.TestCase):
    def test_an_empty_answer_says_why(self):
        t = Transport((200, {"response": "", "done": True, "done_reason": "length"}))
        rc, out, _ = run(["generate", "hi", "-m", "qwen3:1.7b", "--think", "--office", "dell"], t)
        self.assertEqual(rc, 0)
        self.assertIn("answered no text: it stopped at --max", out)

    def test_ollamas_error_through_the_link(self):
        t = Transport((404, '{"error":"model \\"nope\\" not found, try pulling it first"}'))
        rc, out, err = run(["show", "nope", "--office", "dell"], t)
        self.assertEqual((rc, out), (1, ""))
        self.assertIn('model "nope" not found', err)
        self.assertIn("HTTP 404", err)

    def test_an_http_error_through_the_front_says_its_status(self):
        rc, _, err = run(["generate", "hi", "-m", "big"], Transport(wget_error(500), local=True),
                         front="ollama-screen-local")
        self.assertEqual(rc, 1)
        self.assertIn("HTTP 500", err)
        self.assertIn("--office", err)                               # where its words can be read

    def test_a_timeout_inside_the_front(self):
        t = Transport(subprocess.CompletedProcess([], 124, b"", b""), local=True)
        rc, _, err = run(["show", "m", "--timeout", "5"], t, front="ollama-screen-local")
        self.assertEqual(rc, 1)
        self.assertIn("did not answer in 5 s", err)

    def test_a_failed_docker_exec_is_never_a_success(self):
        dead = subprocess.CompletedProcess([], 1, b"", b"Error response from daemon: container abc is not running\n")
        for verb in (["generate", "hi", "-m", "m"], ["show", "m"], ["unload", "m"], ["embed", "x", "-m", "m"]):
            rc, out, err = run(verb, Transport(dead, local=True), front="ollama-screen-local")
            self.assertEqual((rc, out), (1, ""), verb)
            self.assertIn("is not running", err)

    def test_a_link_that_does_not_answer(self):
        def dead(argv, **_k):
            return subprocess.CompletedProcess(argv, 3, b"", b"the link to dell is down\n")
        rc, _, err = run(["show", "m", "--office", "dell"], dead)
        self.assertEqual(rc, 1)
        self.assertIn("the link to dell is down", err)

    def test_no_ollama_here_and_no_office_is_exit_3(self):
        rc, _, err = run(["show", "m"], Transport())
        self.assertEqual(rc, 3)
        self.assertIn("--office", err)

    def test_a_model_that_refuses_think_is_asked_without_it_on_both_paths(self):
        refusal = {"error": '"m" does not support thinking'}
        for t, front, office in ((Transport((400, refusal), (200, {"response": "ok", "done": True})), "", ["--office", "d"]),
                                 (Transport(wget_error(400, "Bad Request"), ok({"response": "ok", "done": True}), local=True),
                                  "ollama-screen-local", [])):
            rc, out, err = run(["generate", "hi", "-m", "m", "--think", *office], t, front=front)
            self.assertEqual((rc, out), (0, "ok\n"))
            self.assertIs(t.calls[0][1]["think"], True)
            self.assertNotIn("think", t.calls[1][1])
            self.assertIn("takes no `think`", err)

    def test_a_400_with_think_off_is_not_retried(self):
        """Ollama refuses `think: true` only: a 400 for think false (an embedding model asked to generate) is the
        answer, said once, with no word about thinking."""
        t = Transport(wget_error(400, "Bad Request"), local=True)
        rc, _, err = run(["generate", "hi", "-m", "nomic-embed-text"], t, front="ollama-screen-local")
        self.assertEqual((rc, len(t.calls)), (1, 1))
        self.assertNotIn("think", err)

    def test_a_local_404_is_no_such_model(self):
        rc, _, err = run(["show", "nope"], Transport(wget_error(404, "Not Found"), local=True), front="ollama-screen-local")
        self.assertEqual(rc, 1)
        self.assertIn("no such model on this office", err)

    def test_a_not_found_naming_think_is_not_retried(self):
        t = Transport((404, {"error": 'model "deepthink" not found'}))
        rc, _, _ = run(["generate", "hi", "-m", "deepthink", "--office", "d"], t)
        self.assertEqual((rc, len(t.calls)), (1, 1))

    def test_a_timeout_is_one_sentence(self):
        def slow(argv, **_k):
            raise subprocess.TimeoutExpired(argv, 1)
        rc, _, err = run(["show", "m", "--office", "dell", "--timeout", "1"], slow)
        self.assertEqual(rc, 1)
        self.assertIn("did not answer in 1 s", err)

    def test_wgets_error_line(self):
        self.assertEqual(llm.wget_status("wget: server returned error: HTTP/1.1 404 Not Found"), 404)
        self.assertIsNone(llm.wget_status("wget: can't connect to remote host (127.0.0.1): Connection refused"))


class Usage(unittest.TestCase):
    def test_missing_model_or_text(self):
        for argv in (["generate", "hi"], ["show"], ["generate", "-m", "m"], ["bogus"]):
            with contextlib.redirect_stderr(io.StringIO()):
                rc, _, _ = run(argv, Transport(), stdin="  ")
            self.assertEqual(rc, 2, argv)

    def test_a_text_from_a_terminal_is_asked_for_not_waited_on(self):
        rc, _, err = run(["generate", "-m", "m", "--office", "d"], Transport(), tty=True)
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
