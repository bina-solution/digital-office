"""dgo-cloud.router — the LLM router: one key, every provider's models, paid from the buyer's wallet (DGO-1893).

The owner: «we have our llm router … 24 shekels of tokens … they can use on any model». A client office reaches it
with the key its server was born with (its .env names the router as DeepSeek's, OpenAI's and Anthropic's address), so
the office's agents use any model and the buyer's wallet pays.

DOORS (both answer on the router's host, and under /llm on the front's):
  POST /v1/chat/completions   OpenAI's format, for every model. DeepSeek and OpenAI models go through as they are;
  POST /chat/completions      a Claude model is TRANSLATED to Anthropic's Messages API and back (text, images, tools,
                              streaming) — DeepSeek's own base URL has no /v1, so both paths answer
  POST /v1/messages           Anthropic's format: Claude models pass through (and DeepSeek's models through DeepSeek's
                              Anthropic-compatible door)
  GET  /v1/models             what is priced, in OpenAI's list format
METERING. The provider's own `usage` of each answer (the last SSE event of a stream) is the count; prices.json turns it
into agorot. A model with no price is refused, never served. Every call is metered, whatever happens: a client that
hangs up mid-stream does not stop the upstream read (the final usage still arrives), and an upstream that dies
mid-answer is charged what was counted, or an estimate from the request's size.
THE WALLET. The key is checked from the headers BEFORE the body is read. A call's most it can cost (its input by size,
its max_tokens of output) is HELD against the account while it runs, so parallel calls cannot spend past zero; a call
that could cost more than is left is refused (402) before anything is sent upstream.
WHAT IS PRICED IS WHAT PASSES. prices.json prices tokens: anything the provider bills on top is not forwarded —
`anthropic-beta` headers, server-side tools (web search…), `service_tier`, `speed`, `inference_geo`.
The prompt and the answer are never stored — only who, which model, how many tokens, what it cost.
"""
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request

from accounts import sha
from store import now

HERE = os.path.dirname(os.path.abspath(__file__))
#: each provider's address and key are read from the environment at CALL time, never once at import: a value fixed at
#: import is the one some earlier importer saw (a test's dummy key once went to the real DeepSeek that way)
UPSTREAM = {
    "deepseek": {"url": ("ROUTER_DEEPSEEK_URL", "https://api.deepseek.com"), "key": "ROUTER_DEEPSEEK_KEY"},
    "openai": {"url": ("ROUTER_OPENAI_URL", "https://api.openai.com"), "key": "ROUTER_OPENAI_KEY"},
    "anthropic": {"url": ("ROUTER_ANTHROPIC_URL", "https://api.anthropic.com"), "key": "ROUTER_ANTHROPIC_KEY"},
}
MAX_BODY = 16 * 1048576
TIMEOUT = 600
PER_KEY = int(os.environ.get("ROUTER_PER_KEY_CONCURRENCY", "8"))
DEFAULT_MAX_OUT = 4096          # what a request that names no max_tokens is held for
UNPRICED = ("service_tier", "speed", "inference_geo")


def upstream_url(provider):
    env, default = UPSTREAM[provider]["url"]
    return (os.environ.get(env) or default).rstrip("/")


class RouterError(Exception):
    def __init__(self, status, message, kind="invalid_request_error"):
        super().__init__(message)
        self.status, self.kind = status, kind


def load_prices(store=None):
    with open(os.environ.get("DGOCLOUD_PRICES", os.path.join(HERE, "prices.json")), encoding="utf-8") as f:
        p = json.load(f)
    if store is not None:
        p["usd_ils"] = float(store.setting("usd_ils", p["usd_ils"]))
        p["margin"] = float(store.setting("margin", p["margin"]))
    return p


def cost_agorot(price, usd_ils, margin, inp=0, cached=0, write=0, out=0):
    """→ (agorot, usd_micros). Input counted ONCE: `inp` is the uncached input."""
    usd = (inp * price.get("in", 0) + cached * price.get("cached", price.get("in", 0)) +
           write * price.get("write", price.get("in", 0)) + out * price.get("out", 0)) / 1e6
    return int(math.ceil(usd * usd_ils * (1 + margin) * 100 - 1e-9)), int(round(usd * 1e6))


def max_out(req):
    for k in ("max_completion_tokens", "max_tokens"):
        try:
            if req.get(k):
                return max(1, int(req[k]))
        except (TypeError, ValueError):
            pass
    return DEFAULT_MAX_OUT


#: tools the CLIENT runs (its own functions, Anthropic's client-side bash/editor/computer/memory): priced as tokens
CLIENT_TOOLS = ("custom", "function", "bash_", "text_editor_", "computer_", "memory_")


def unpriced_tools(req):
    """Server-side tools (web search, web fetch, code execution, MCP…) are billed by the provider per use, outside the
    token price: refused, not forwarded."""
    bad = []
    for t in req.get("tools") or []:
        if not isinstance(t, dict):
            continue
        typ = t.get("type")
        if typ is None or any(typ == p or str(typ).startswith(p) for p in CLIENT_TOOLS):
            continue
        bad.append(str(typ))
    return bad


class Router:
    def __init__(self, store, billing, log=print):
        self.s = store
        self.b = billing
        self.log = log
        self._busy = {}
        self._held = {}
        self._lock = threading.Lock()

    def upstream_key(self, provider):
        return os.environ.get(UPSTREAM[provider]["key"], "")

    def providers(self):
        return {p: bool(self.upstream_key(p)) for p in UPSTREAM}

    # ── who is calling ───────────────────────────────────────────────────────────────────────────────
    def authorize(self, headers):
        tok = (headers.get("Authorization") or "").removeprefix("Bearer ").strip() or \
              (headers.get("x-api-key") or "").strip()
        if not tok.startswith("dk_"):
            raise RouterError(401, "missing or invalid API key (a DGO cloud key starts with dk_)", "authentication_error")
        k = self.s.one("SELECT k.*, a.status AS account_status FROM keys k LEFT JOIN accounts a ON a.id=k.account_id "
                       "WHERE k.hash=?", sha(tok))
        if not k or k["revoked_at"]:
            raise RouterError(401, "this API key is not valid", "authentication_error")
        if not k["account_id"]:
            raise RouterError(402, "this server is not yet assigned to an account", "insufficient_quota")
        if k["account_status"] != "active":
            raise RouterError(403, "the account of this key is disabled", "permission_error")
        if not self.b.entitled(k["account_id"]):
            raise RouterError(402, "the DGO cloud subscription of this key is not active", "insufficient_quota")
        if self.s.balance(k["account_id"])["total"] <= 0:
            raise RouterError(402, "the AI credit of this account is used up — top up at the DGO cloud site",
                              "insufficient_quota")
        return k

    def models(self):
        p = load_prices(self.s)
        return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": v["provider"], "created": 0}
                                           for m, v in p["models"].items() if self.upstream_key(v["provider"])]}

    def _price(self, model):
        p = load_prices(self.s)
        m = p["models"].get(model)
        if not m:
            raise RouterError(404, f"model {model!r} is not offered — GET /v1/models lists what is", "not_found_error")
        if not self.upstream_key(m["provider"]):
            raise RouterError(503, f"model {model!r} is not available right now", "api_error")
        return m, p

    # ── the doors ────────────────────────────────────────────────────────────────────────────────────
    def handle(self, path, headers, read_body, out):
        """`read_body()` reads the request body — called only once the key is good. `out` is the handler's writer:
        out.start(status, headers), out.write(bytes) (never raises: a client gone only stops the writing),
        out.done(). → nothing (it answered)."""
        t0 = time.time()
        k = self.authorize(headers)
        body = read_body()
        try:
            req = json.loads(body or b"{}")
        except ValueError:
            raise RouterError(400, "the body is not JSON")
        if not isinstance(req, dict):
            raise RouterError(400, "the body is not a JSON object")
        model = str(req.get("model") or "")
        price, table = self._price(model)
        prov = price["provider"]
        bad = unpriced_tools(req)
        if bad:
            raise RouterError(400, f"server-side tools are not offered here: {', '.join(bad)}")
        for f in UNPRICED:
            req.pop(f, None)
        aid = k["account_id"]
        hold, _ = cost_agorot(price, table["usd_ils"], table["margin"], inp=len(body) // 3, out=max_out(req))
        with self._lock:
            if self._busy.get(k["id"], 0) >= PER_KEY:
                raise RouterError(429, "too many requests at once on this key", "rate_limit_error")
            left = self.s.balance(aid)["total"] - self._held.get(aid, 0)
            if hold > left:
                raise RouterError(402, f"this request may cost up to ₪{hold / 100:.2f} and ₪{max(left, 0) / 100:.2f} "
                                       f"is left — lower max_tokens, or top up", "insufficient_quota")
            self._busy[k["id"]] = self._busy.get(k["id"], 0) + 1
            self._held[aid] = self._held.get(aid, 0) + hold
        usage, st = {}, {"status": 0, "bytes": 0}
        try:
            if path.endswith("/messages"):
                if prov == "openai":
                    raise RouterError(400, "an OpenAI model answers on /v1/chat/completions")
                self._anthropic_native(prov, req, headers, out, usage, st)
            elif prov == "anthropic":
                self._claude_via_openai(req, out, usage, st)
            else:
                self._openai_native(prov, req, out, usage, st)
        finally:
            with self._lock:
                self._busy[k["id"]] -= 1
                self._held[aid] = self._held.get(aid, 0) - hold
            if st["status"] == 200 and not usage:
                # the upstream died before its usage: charge what the request's size and the bytes sent say
                usage = {"in": len(body) // 4, "out": st["bytes"] // 4}
            if st["status"]:
                self._meter(k, model, prov, price, table, usage, st["status"], int((time.time() - t0) * 1000))
            self.s.run("UPDATE keys SET last_used=? WHERE id=?", now(), k["id"])

    def _meter(self, k, model, prov, price, table, u, status, ms):
        inp, cached, write, outt = (int(u.get(x) or 0) for x in ("in", "cached", "write", "out"))
        agorot, micros = cost_agorot(price, table["usd_ils"], table["margin"], inp, cached, write, outt)
        uid = self.s.run("INSERT INTO usage(key_id,account_id,model,provider,in_tokens,out_tokens,cached_tokens,"
                         "usd_micros,cost,status,ms,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         k["id"], k["account_id"], model, prov, inp + cached + write, outt, cached, micros, agorot,
                         status, ms, now())
        if agorot:
            self.s.debit(k["account_id"], agorot, f"u:{uid}", model)

    # ── upstream ─────────────────────────────────────────────────────────────────────────────────────
    def _open(self, prov, path, payload, extra=None):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        key = self.upstream_key(prov)
        if prov == "anthropic" or path.startswith("/anthropic"):
            # anthropic-beta is NOT forwarded: a beta may be billed outside the price table (WHAT IS PRICED…)
            h.update({"x-api-key": key, "anthropic-version": (extra or {}).get("anthropic-version") or "2023-06-01"})
        else:
            h["Authorization"] = "Bearer " + key
        req = urllib.request.Request(upstream_url(prov) + path, data=json.dumps(payload).encode(), method="POST",
                                     headers=h)
        try:
            return urllib.request.urlopen(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            return e          # an upstream refusal is relayed as it is: the client reads the provider's own error

    @staticmethod
    def _send(out, st, b):
        st["bytes"] += len(b)
        out.write(b)

    def _relay_whole(self, r, out, st):
        raw = r.read()
        out.start(st["status"], {"Content-Type": r.headers.get("Content-Type", "application/json")})
        self._send(out, st, raw)
        out.done()
        return raw

    def _openai_native(self, prov, req, out, usage, st):
        stream = bool(req.get("stream"))
        if stream:
            req.setdefault("stream_options", {})["include_usage"] = True
        path = "/chat/completions" if prov == "deepseek" else "/v1/chat/completions"
        r = self._open(prov, path, req)
        st["status"] = getattr(r, "status", None) or r.code
        if not stream or st["status"] != 200:
            raw = self._relay_whole(r, out, st)
            if st["status"] == 200:
                usage.update(_openai_usage((json.loads(raw) or {}).get("usage") or {}))
            return
        out.start(200, {"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        for line in r:
            self._send(out, st, line)
            if line.startswith(b"data: {"):
                try:
                    u = json.loads(line[6:]).get("usage")
                except ValueError:
                    u = None
                if u:
                    usage.clear()
                    usage.update(_openai_usage(u))
        out.done()

    def _anthropic_native(self, prov, req, headers, out, usage, st):
        path = "/anthropic/v1/messages" if prov == "deepseek" else "/v1/messages"
        r = self._open(prov, path, req, {"anthropic-version": headers.get("anthropic-version")})
        st["status"] = getattr(r, "status", None) or r.code
        if not req.get("stream") or st["status"] != 200:
            raw = self._relay_whole(r, out, st)
            if st["status"] == 200:
                usage.update(_anthropic_usage((json.loads(raw) or {}).get("usage") or {}))
            return
        out.start(200, {"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        for line in r:
            self._send(out, st, line)
            if line.startswith(b"data: {"):
                try:
                    ev = json.loads(line[6:])
                except ValueError:
                    continue
                if ev.get("type") == "message_start":
                    usage.update(_anthropic_usage((ev.get("message") or {}).get("usage") or {}))
                elif ev.get("type") == "message_delta" and ev.get("usage"):
                    usage["out"] = ev["usage"].get("output_tokens", usage.get("out", 0))
        out.done()

    def _claude_via_openai(self, req, out, usage, st):
        stream = bool(req.get("stream"))
        payload = openai_to_anthropic(req)
        r = self._open("anthropic", "/v1/messages", payload)
        st["status"] = getattr(r, "status", None) or r.code
        model = req.get("model")
        if st["status"] != 200:
            raw = r.read()
            try:
                msg = (json.loads(raw).get("error") or {}).get("message") or raw.decode()[:300]
            except ValueError:
                msg = raw.decode("utf-8", "replace")[:300]
            out.start(st["status"], {"Content-Type": "application/json"})
            self._send(out, st, json.dumps({"error": {"message": msg, "type": "upstream_error"}}).encode())
            out.done()
            return
        if not stream:
            d = json.loads(r.read())
            usage.update(_anthropic_usage(d.get("usage") or {}))
            out.start(200, {"Content-Type": "application/json"})
            self._send(out, st, json.dumps(anthropic_to_openai(d, model)).encode())
            out.done()
            return
        out.start(200, {"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        c = {"id": "chatcmpl-dgo", "tools": {}, "model": model}
        include_usage = bool((req.get("stream_options") or {}).get("include_usage"))
        for line in r:
            if not line.startswith(b"data: {"):
                continue
            try:
                ev = json.loads(line[6:])
            except ValueError:
                continue
            t = ev.get("type")
            if t == "message_start":
                c["id"] = "chatcmpl-" + (ev.get("message") or {}).get("id", "dgo")
                usage.update(_anthropic_usage((ev.get("message") or {}).get("usage") or {}))
                self._send(out, st, _chunk(c, {"role": "assistant", "content": ""}))
            elif t == "content_block_start":
                cb = ev.get("content_block") or {}
                if cb.get("type") == "tool_use":
                    i = len(c["tools"])
                    c["tools"][ev.get("index")] = i
                    self._send(out, st, _chunk(c, {"tool_calls": [{"index": i, "id": cb.get("id"), "type": "function",
                                                                   "function": {"name": cb.get("name"),
                                                                                "arguments": ""}}]}))
            elif t == "content_block_delta":
                dl = ev.get("delta") or {}
                if dl.get("type") == "text_delta":
                    self._send(out, st, _chunk(c, {"content": dl.get("text", "")}))
                elif dl.get("type") == "input_json_delta" and ev.get("index") in c["tools"]:
                    self._send(out, st, _chunk(c, {"tool_calls": [{"index": c["tools"][ev["index"]],
                                                                   "function": {"arguments": dl.get("partial_json", "")}}]}))
            elif t == "message_delta":
                if ev.get("usage"):
                    usage["out"] = ev["usage"].get("output_tokens", 0)
                self._send(out, st, _chunk(c, {}, FINISH.get((ev.get("delta") or {}).get("stop_reason"), "stop")))
            elif t == "message_stop":
                break
        if include_usage:
            self._send(out, st, b"data: " + json.dumps({"id": c["id"], "object": "chat.completion.chunk",
                                                        "model": model, "choices": [],
                                                        "usage": _openai_shape(usage)}).encode() + b"\n\n")
        self._send(out, st, b"data: [DONE]\n\n")
        out.done()


# ── shapes ───────────────────────────────────────────────────────────────────────────────────────────────
FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls",
          "refusal": "content_filter", "pause_turn": "stop"}


def _openai_usage(u):
    cached = int(u.get("prompt_cache_hit_tokens") or (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    return {"in": max(int(u.get("prompt_tokens") or 0) - cached, 0), "cached": cached,
            "out": int(u.get("completion_tokens") or 0)}


def _anthropic_usage(u):
    return {"in": int(u.get("input_tokens") or 0), "cached": int(u.get("cache_read_input_tokens") or 0),
            "write": int(u.get("cache_creation_input_tokens") or 0), "out": int(u.get("output_tokens") or 0)}


def _openai_shape(u):
    p = int(u.get("in", 0)) + int(u.get("cached", 0)) + int(u.get("write", 0))
    return {"prompt_tokens": p, "completion_tokens": int(u.get("out", 0)), "total_tokens": p + int(u.get("out", 0)),
            "prompt_tokens_details": {"cached_tokens": int(u.get("cached", 0))}}


def _chunk(c, delta, finish=None):
    return b"data: " + json.dumps({"id": c["id"], "object": "chat.completion.chunk", "model": c["model"],
                                   "created": int(time.time()),
                                   "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}).encode() + b"\n\n"


def _image_block(url):
    if url.startswith("data:") and ";base64," in url:
        head, data = url.split(",", 1)
        return {"type": "image", "source": {"type": "base64", "media_type": head[5:].split(";")[0], "data": data}}
    return {"type": "image", "source": {"type": "url", "url": url}}


def _parts(content):
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    blocks = []
    for p in content or []:
        if p.get("type") == "text":
            blocks.append({"type": "text", "text": p.get("text", "")})
        elif p.get("type") == "image_url":
            blocks.append(_image_block((p.get("image_url") or {}).get("url", "")))
    return blocks


def openai_to_anthropic(req):
    """OpenAI chat → Anthropic Messages: system messages become `system`, tool calls `tool_use`, tool answers
    `tool_result` in a user turn; consecutive same-role turns are merged (Anthropic alternates strictly).
    temperature/top_p are not sent: the Messages API refuses them on every model since 2026-10-21."""
    system, msgs = [], []

    def push(role, blocks):
        if not blocks:
            return
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"].extend(blocks)
        else:
            msgs.append({"role": role, "content": blocks})

    for m in req.get("messages") or []:
        role = m.get("role")
        if role in ("system", "developer"):
            system += [b["text"] for b in _parts(m.get("content")) if b["type"] == "text"]
        elif role == "user":
            push("user", _parts(m.get("content")))
        elif role == "assistant":
            blocks = _parts(m.get("content"))
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                blocks.append({"type": "tool_use", "id": tc.get("id"), "name": fn.get("name"), "input": args})
            push("assistant", blocks)
        elif role == "tool":
            c = m.get("content")
            push("user", [{"type": "tool_result", "tool_use_id": m.get("tool_call_id"),
                           "content": c if isinstance(c, str) else _parts(c)}])
    out = {"model": req["model"], "messages": msgs, "max_tokens": max_out(req) if (
        req.get("max_completion_tokens") or req.get("max_tokens")) else 8192}
    if system:
        out["system"] = "\n\n".join(system)
    if req.get("stream"):
        out["stream"] = True
    stop = req.get("stop")
    if stop:
        out["stop_sequences"] = [stop] if isinstance(stop, str) else list(stop)[:4]
    if req.get("tools"):
        out["tools"] = [{"name": (t.get("function") or {}).get("name"),
                         "description": (t.get("function") or {}).get("description", ""),
                         "input_schema": (t.get("function") or {}).get("parameters") or {"type": "object"}}
                        for t in req["tools"] if t.get("type") == "function"]
        tc = req.get("tool_choice")
        if tc == "none":
            out["tool_choice"] = {"type": "none"}
        else:
            out["tool_choice"] = {"type": "auto"}      # forced choice is a 400 on the current models
    return out


def anthropic_to_openai(d, model):
    text = "".join(b.get("text", "") for b in d.get("content") or [] if b.get("type") == "text")
    calls = [{"id": b.get("id"), "type": "function",
              "function": {"name": b.get("name"), "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}}
             for b in d.get("content") or [] if b.get("type") == "tool_use"]
    msg = {"role": "assistant", "content": text or None}
    if calls:
        msg["tool_calls"] = calls
    return {"id": "chatcmpl-" + str(d.get("id", "")), "object": "chat.completion", "created": int(time.time()),
            "model": model, "choices": [{"index": 0, "message": msg,
                                         "finish_reason": FINISH.get(d.get("stop_reason"), "stop")}],
            "usage": _openai_shape(_anthropic_usage(d.get("usage") or {}))}
