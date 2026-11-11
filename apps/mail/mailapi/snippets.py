"""The preview line of a listed message — `snippets: true` on `/search` (DGO-1507).

Gmail's list shows a line of every message under its subject; ours could not, because `/search`
fetches headers and BODYSTRUCTURE only (N11: no body fetch per message on a list). This keeps that
promise and still gives the line:

* ONE extra FETCH per page per part NUMBER, not per message: the text part of most mail is `1`
  (a plain message) or `1.1` (plain inside multipart/alternative), so a page of 100 costs one or two
  commands — `UID FETCH <uids> BODY.PEEK[1.1]<0.640>`, 640 octets each (4096 for a message that has
  only HTML, whose start is its <head>), `PEEK` so nothing is marked read. A page whose text parts sit
  at more than MAX_GROUPS numbers gets the line for the largest groups only.
* The bytes are decoded the way the part says (base64 cut to whole quanta, quoted-printable with a
  half escape dropped, the part's charset with the IANA Hebrew labels mapped as `decode_part` does),
  HTML is reduced to its text, a quoted reply and a signature are cut, and 140 characters are kept.
* A message never changes under its (mailbox, folder, UIDVALIDITY, UID), so the line is kept in a
  bounded LRU: a page seen once costs nothing the second time.
* Opt-in, and never fatal: any failure leaves the page without the lines it could not read — the
  list itself is the answer, and a missing preview is not an error.
"""
from __future__ import annotations

import base64
import binascii
import codecs
import html
import quopri
import re
import threading
from collections import OrderedDict

PEEK = 640          # octets of a text/plain part read per message
PEEK_HTML = 4096    # …and of an HTML-only one: its first 640 octets are mostly <head> and <style>
KEEP = 140          # characters of preview kept
MAX_GROUPS = 3      # part numbers fetched per page (one FETCH each)
CACHE_MAX = 8000    # previews kept (≈ 140 chars each)


class _LRU:
    def __init__(self, cap):
        self.cap, self.d, self.lock = cap, OrderedDict(), threading.Lock()

    def get(self, k):
        with self.lock:
            v = self.d.get(k)
            if v is not None:
                self.d.move_to_end(k)
            return v

    def put(self, k, v):
        with self.lock:
            self.d[k] = v
            self.d.move_to_end(k)
            while len(self.d) > self.cap:
                self.d.popitem(last=False)


CACHE = _LRU(CACHE_MAX)


def text_leaf(leaves):
    """The part a preview is read from: the first text/plain that is not an attachment, else the
    first text/html. None for a message with neither (a bare attachment, a calendar invite)."""
    body = [l for l in leaves or [] if l.get("type") == "text" and not l.get("is_att")]
    return (next((l for l in body if l.get("subtype") == "plain"), None)
            or next((l for l in body if l.get("subtype") == "html"), None))


_TAGS_DROP = re.compile(r"(?is)<(style|script|head|title)\b.*?(?:</\1\s*>|$)")
_TAG = re.compile(r"(?s)<[^>]*(?:>|$)")
# where the quoted message starts: «On … wrote:» (whatever line it wraps onto), «… כתב/ה:», Outlook's rulers
_WROTE = re.compile(r"(wrote:|כתב(?:/ה|ה)?:)$|^-{2,}\s*(original message|forwarded message|הודעה מקורית|הודעה שהועברה)\s*-{2,}$", re.I)
_QUOTE_HEAD = re.compile(r"^(on\s|ב[-־]?\d|בתאריך\s)", re.I)
_RULER = re.compile(r"^[=\-_*~#.·]{3,}$")


def decode_peek(raw: bytes, enc: str, charset: str, is_html: bool) -> str:
    """The first PEEK octets of a part (as the server sent them, still transfer-encoded) → its text."""
    enc = (enc or "").upper()
    if enc == "BASE64":
        s = re.sub(rb"[^A-Za-z0-9+/=]", b"", raw or b"")
        s = s[: len(s) - len(s) % 4]               # the cut may fall inside a 4-char quantum
        try:
            raw = base64.b64decode(s)
        except (binascii.Error, ValueError):
            return ""
    elif enc == "QUOTED-PRINTABLE":
        raw = re.sub(rb"=(?:[0-9A-Fa-f])?$", b"", raw or b"")   # …or inside an escape
        raw = quopri.decodestring(raw)
    cs = (charset or "utf-8").strip().lower()
    if cs.endswith(("-i", "-e")):
        cs = cs[:-2]
    try:
        codecs.lookup(cs)
    except (LookupError, ValueError):
        cs = "utf-8"
    text = (raw or b"").decode(cs, "replace").rstrip("�")   # a character cut in half at the end
    if is_html:
        text = _TAG.sub(" ", _TAGS_DROP.sub(" ", text))
        text = html.unescape(text)
    return clean(text)


def clean(text: str) -> str:
    """One line: no quoted reply, no signature, whitespace collapsed, KEEP characters."""
    kept = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith(">") or _RULER.match(s):   # a quote, or a heading's underline «=====»
            continue
        if s in ("--", "-- ", "—"):
            break
        if _WROTE.search(s):
            # «On Sat, Nov 7 … <d@x>» / «wrote:» — the header of a quote wraps onto two lines
            if kept and not _QUOTE_HEAD.match(s) and _QUOTE_HEAD.match(kept[-1]):
                kept.pop()
            break
        kept.append(s)
    t = re.sub(r"\s+", " ", " ".join(kept)).strip()
    t = t.replace("‏", "").replace("‎", "")
    if len(t) > KEEP:
        t = t[:KEEP].rstrip() + "…"
    return t


def _body_of(data: dict, num: str):
    """imapclient names a partial fetch's answer `BODY[1.1]<0>`; find it whatever the exact spelling."""
    want = ("BODY[%s]" % num).encode()
    for k, v in data.items():
        if isinstance(k, (bytes, bytearray)) and bytes(k).upper().startswith(want):
            return v if isinstance(v, (bytes, bytearray)) else (v.encode() if isinstance(v, str) else b"")
    return None


def fill(conn, summaries, leaves_by_uid, scope, log=None):
    """Put `snippet` on each summary (a dict with `uid`) of one page, reading what the cache does not
    hold. `conn` has the page's folder selected; `scope` is (mailbox, folder, uidvalidity) — the key a
    UID is unique under. Returns how many FETCH commands it sent."""
    sent = 0
    groups = {}
    for s in summaries:
        uid = s.get("uid")
        key = scope + (uid,)
        hit = CACHE.get(key)
        if hit is not None:
            s["snippet"] = hit
            continue
        leaf = text_leaf(leaves_by_uid.get(uid))
        if leaf is None:
            CACHE.put(key, "")
            s["snippet"] = ""
            continue
        is_html = leaf.get("subtype") == "html"
        groups.setdefault((leaf["num"], is_html), []).append((s, leaf))
    for (num, is_html), items in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:MAX_GROUPS]:
        peek = PEEK_HTML if is_html else PEEK
        try:
            resp = conn.fetch([s["uid"] for s, _ in items], [("BODY.PEEK[%s]<0.%d>" % (num, peek)).encode()])
            sent += 1
        except Exception as e:                       # a preview is never worth the page
            if log:
                log("snippets: FETCH BODY[%s] failed: %s", num, e)
            continue
        for s, leaf in items:
            raw = _body_of(resp.get(s["uid"]) or {}, num)
            if raw is None:
                continue
            try:
                text = decode_peek(raw, leaf.get("enc"), leaf.get("charset"), leaf.get("subtype") == "html")
            except Exception:
                continue
            s["snippet"] = text
            CACHE.put(scope + (s["uid"],), text)
    return sent
