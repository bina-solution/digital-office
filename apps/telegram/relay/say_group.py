#!/usr/bin/env python3
#: say-group — post ONE message in the office's Telegram group as the BOT, and print its message_id
#:   ./bbox telegram say-group "<text>"            (or: … | ./bbox telegram say-group -   — text on stdin)
#:   ./bbox telegram say-group --chat "…" --chat-id -100… "<text>"
#:   ./bbox telegram say-group --attach <file> "<caption>"   — the file itself (.mp4 as a video, else a document)
#:   ./bbox telegram say-group --for <msg> "<text>"   — an ANSWER: a reply to his message number <msg>, recorded on
#:                                                       that request by the relay (apps/telegram/relay/desk.py)
#
# WHY IT EXISTS (DGO-1339). The group's answerer writes there AS THE BOT, never as the owner's account — and a
# bot token must never be typed, printed, put in a file or left on a command line. So the token is taken from
# the office's own vault into memory (`telegram_bot` instance, the one labelled «בוט טלגרם ראשי») and used in one
# HTTPS request. What comes back is the message number, which is the proof a person's reply landed.
#
# Environment: CONNECTIONS_URL (http://connections:8990) · TELEGRAM_URL (http://telegram:8984)
#              TELEGRAM_BOT_LABEL («בוט טלגרם ראשי»)
# Exit: 0 posted · 2 bad usage · 3 the vault or Telegram refused (its own words) · 4 no such chat in the office.
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN = ""          # module-level only so an error cannot be formatted with it; never printed

#: THE GROUP NEVER GETS AN INTERNAL ADDRESS. Measured 2026-11-04 (the Mac king's correction of #134, which carried
#: `http://console.localhost:8080/#/m/project-pln/…`): a `.localhost` name is meaningless to the owner's phone and
#: a private address is the office's own plumbing. What a person may be given is the console he can actually open —
#: https://console.staging.digital-office.co.il/#/m/plane.hp-laptop/bina/projects/<proj>/issues/<uuid> — or, plainly,
#: the item number (DGO-1339). Refused here rather than remembered, because "#134 was fine" is how it happened.
INTERNAL = (
    #: one label or several (`forge.console.localhost`), and at the end of a sentence too
    (re.compile(r"(?<![\w.-])[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.localhost(?![\w-])"), "a .localhost name"),
    (re.compile(r"(?<![\w.-])localhost(?::\d{1,5})?(?![\w-])", re.I), "the loopback"),
    (re.compile(r"https?://[A-Za-z0-9_-]+:\d+"), "an address with a bare service name"),
    #: an address never ends inside a number, but it may end a sentence — «… 10.9.8.7.» is refused too
    (re.compile(r"(?<![\d.])(?:127\.\d{1,3}\.\d{1,3}\.\d{1,3}|0\.0\.0\.0)(?!\.?\d)"), "the loopback"),
    (re.compile(r"(?<![\d.])10\.\d{1,3}\.\d{1,3}\.\d{1,3}(?!\.?\d)"), "a private address"),
    (re.compile(r"(?<![\d.])192\.168\.\d{1,3}\.\d{1,3}(?!\.?\d)"), "a private address"),
    (re.compile(r"(?<![\d.])172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}(?!\.?\d)"), "a private address"),
    (re.compile(r"(?<![\d.])100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}(?!\.?\d)"), "a private address"),
    (re.compile(r"(?<![\d.])169\.254\.\d{1,3}\.\d{1,3}(?!\.?\d)"), "a link-local address"),
    #: IPv6: the loopback, unique-local (fc00::/7) and link-local (fe80::/10)
    (re.compile(r"(?<![\w:])(?:::1|f[cd][0-9a-f]{2}:[0-9a-f:]*|fe[89ab][0-9a-f]:[0-9a-f:]*)(?![\w:])", re.I),
     "a private address"),
    #: a bot's token is never said — internal() names it without showing it, so the refusal cannot leak it either
    (re.compile(r"(?<![\w:-])\d{8,10}:[A-Za-z0-9_-]{35}(?![\w-])"), "a bot token"),
    #: an office's own name as a host part AND a port (the git door, a linked office's service):
    #: `git-accounts.macbook:9004`. No port, no match — the console link the owner may be sent carries
    #: `plane.hp-laptop` in its own path and is not an address.
    (re.compile(r"(?<![\w.-])[A-Za-z0-9_][\w-]*\.(?:macbook|hp-laptop|portable-ubuntu|vps1|dell)(?=:\d{2,5})"),
     "an office's own hostname"),
)


def internal(text: str) -> str:
    """The first internal address in a would-be reply, as one sentence — "" when the text is clean."""
    for pattern, what in INTERNAL:
        hit = pattern.search(text or "")
        if hit:
            if what.endswith("token"):
                return "the text holds %s (not shown)" % what
            return "«%s» is %s" % (hit.group(0), what)
    return ""



def api(url: str, data=None, timeout: float = 40):
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"content-type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def bot_token(label: str) -> str:
    """One bot's token out of the vault, by the label the owner gave it. In memory, for one request."""
    vault = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
    try:
        rows = (api(vault + "/api/instances") or {}).get("instances") or []
    except (urllib.error.URLError, OSError, ValueError) as e:
        sys.exit("say-group: the vault did not answer (%s)" % e)
    cands = [r for r in rows if r.get("protocol") == "telegram_bot"]
    pick = next((r for r in cands if (r.get("label") or "").strip() == label), None)
    if pick is None and len(cands) == 1:
        pick = cands[0]
    if pick is None:
        sys.exit("say-group: no bot token labelled «%s» in the vault (have: %s)"
                 % (label, ", ".join((r.get("label") or r.get("id")) for r in cands) or "none"))
    try:
        secret = (api(vault + "/api/instances/%s/secret" % pick["id"]) or {}).get("secret") or {}
    except (urllib.error.URLError, OSError, ValueError) as e:
        sys.exit("say-group: the vault refused the token of «%s» (%s)" % (label, e))
    tok = (secret.get("token") or "").strip()
    if len(tok) < 20:
        sys.exit("say-group: the vault's «%s» holds no token" % label)
    return tok


def chat_id_of(title: str, explicit: str) -> str:
    if explicit:
        return explicit
    url = os.environ.get("TELEGRAM_URL", "http://telegram:8984").rstrip("/") + "/api/status"
    try:
        status = api(url)
    except (urllib.error.URLError, OSError, ValueError) as e:
        sys.exit("say-group: the telegram app did not answer (%s); pass --chat-id" % e)
    watched = [w for w in (status.get("watched") or []) if (w.get("title") or "") == title]
    if not watched:
        sys.exit("say-group: the office watches no chat called «%s»" % title)
    # A group that became a supergroup keeps BOTH ids watched for their history; the live one is the supergroup.
    # The supergroup's id is the NEGATIVE of the old one with -100 in front (`-4303648995` -> `-1004303648995`),
    # so a numeric max picks the DEAD id and Telegram answers «group chat was upgraded» (measured 2026-11-06).
    # The prefix is the signal, not the magnitude.
    supers = [w for w in watched if str(w.get("id", "")).startswith("-100")]
    chosen = (supers or watched)[-1]
    return str(chosen["id"])


#: Telegram's own limit for a bot upload: 50 MB, and nothing here may pretend otherwise — a bigger file is
#: refused with the number instead of failing halfway through the upload.
BOT_UPLOAD_LIMIT = 50 * 1024 * 1024
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}


def reply_to(message_id: str) -> dict:
    """An answer is a REPLY to the message it answers (DGO-1352): in the group he sees which message of his it
    answers, and the relay, seeing the bot's reply on the stream, records it on that request. Sent even if the
    message is gone, so an answer is never lost to a deleted question."""
    return {"message_id": int(message_id), "allow_sending_without_reply": True}


def post_file(tok: str, chat: str, path: str, caption: str, for_msg: str = "") -> dict:
    """ONE upload as the bot: `sendVideo` for a video, `sendDocument` for anything else.

    Why it is here (DGO-1338): the owner was promised the office's tutorial videos and the only way to hand
    him one was this file sitting in drive — the bot could write text, and the app's own `/api/send` writes
    as HIS account, which is not what the group's answerer does. One request, the token in memory only.
    """
    size = os.path.getsize(path)
    if size > BOT_UPLOAD_LIMIT:
        sys.exit("say-group: %s is %.1f MB — a bot uploads up to 50 MB (put it in drive and send the link)"
                 % (os.path.basename(path), size / 1048576.0))
    name = os.path.basename(path)
    kind = "video" if os.path.splitext(name)[1].lower() in VIDEO_EXT else "document"
    edge = "dgo" + os.urandom(12).hex()
    with open(path, "rb") as f:
        blob = f.read()
    parts = [(f'--{edge}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat}\r\n').encode("utf-8")]
    if caption:
        parts.append((f'--{edge}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n'
                      f"{caption[:1024]}\r\n").encode("utf-8"))
    if for_msg:
        parts.append((f'--{edge}\r\nContent-Disposition: form-data; name="reply_parameters"\r\n\r\n'
                      f"{json.dumps(reply_to(for_msg))}\r\n").encode("utf-8"))
    parts.append((f'--{edge}\r\nContent-Disposition: form-data; name="{kind}"; filename="{name}"\r\n'
                  f"Content-Type: application/octet-stream\r\n\r\n").encode("utf-8"))
    parts.append(blob)
    parts.append(f"\r\n--{edge}--\r\n".encode("utf-8"))
    method = "sendVideo" if kind == "video" else "sendDocument"
    url = "https://api.telegram.org/bot%s/%s" % (tok, method)
    req = urllib.request.Request(url, data=b"".join(parts), method="POST",
                                 headers={"Content-Type": "multipart/form-data; boundary=%s" % edge})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            answer = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {}
        why = payload.get("description") or ""
        # same migration as the text path: a supergroup's live id arrives in the refusal, and the multipart
        # body carries the chat id, so it is rebuilt — never re-sent to the dead chat (2026-11-06).
        migrate = (payload.get("parameters") or {}).get("migrate_to_chat_id")
        if migrate:
            moved = b"".join(parts).replace(
                ('name="chat_id"\r\n\r\n%s\r\n' % chat).encode("utf-8"),
                ('name="chat_id"\r\n\r\n%s\r\n' % migrate).encode("utf-8"))
            try:
                with urllib.request.urlopen(urllib.request.Request(
                        url, data=moved, method="POST",
                        headers={"Content-Type": "multipart/form-data; boundary=%s" % edge}), timeout=300) as resp:
                    answer = json.loads(resp.read().decode("utf-8", "replace"))
                chat = str(migrate)
            except (urllib.error.URLError, OSError, ValueError) as again:
                sys.exit("say-group: Telegram moved this chat to %s and would not take the file there (%s)"
                         % (migrate, str(again).replace(tok, "***")))
        else:
            sys.exit("say-group: Telegram refused (%s) %s" % (e.code, why.replace(tok, "***")))
    except (urllib.error.URLError, OSError) as e:
        sys.exit("say-group: Telegram did not answer (%s)" % str(e).replace(tok, "***"))
    if not answer.get("ok"):
        sys.exit("say-group: Telegram refused (%s)" % (answer.get("description") or "").replace(tok, "***"))
    return answer.get("result") or {}


def main(argv) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("text", nargs="*", help="the message; `-` reads it from stdin")
    ap.add_argument("--chat", default="Bina Solutions Main")
    ap.add_argument("--chat-id", default="")
    ap.add_argument("--bot", default=os.environ.get("TELEGRAM_BOT_LABEL", "בוט טלגרם ראשי"))
    ap.add_argument("--attach", default="", help="a file to send: .mp4 as a video, anything else as a document")
    ap.add_argument("--for", dest="for_msg", default="",
                    help="the owner's message this answers (its number, «msg N» in the TG: line): the answer is "
                         "sent as a reply to it, and the relay records it as that request's answer (desk.py)")
    ap.add_argument("--quiet", action="store_true", help="print nothing but the message id")
    args = ap.parse_args(argv[1:])
    if args.for_msg and not args.for_msg.isdigit():
        sys.exit("say-group: --for takes the message's number (msg N in the TG: line)")

    text = sys.stdin.read() if args.text[:1] == ["-"] else " ".join(args.text)
    text = (text or "").strip()
    if args.attach and not os.path.isfile(args.attach):
        sys.exit("say-group: --attach %s is not a file here" % args.attach)
    if not text and not args.attach:
        sys.exit("say-group: nothing to say")
    bad = internal(text)
    if bad:
        sys.exit("say-group: not sent — the group never gets an internal address: %s.\n"
                 "  Use the item number (DGO-1234), or the console the owner can open:\n"
                 "  https://console.staging.digital-office.co.il/#/m/plane.hp-laptop/bina/projects/<proj>/issues/<uuid>"
                 % bad)
    if args.attach:
        tok = bot_token(args.bot)
        chat = chat_id_of(args.chat, args.chat_id)
        res = post_file(tok, chat, args.attach, text, args.for_msg)
        if args.quiet:
            print(res.get("message_id"))
        else:
            print("posted %s to %s as @%s — message_id %s"
                  % (os.path.basename(args.attach), chat,
                     (res.get("chat") or {}).get("username")
                     or os.environ.get("TELEGRAM_BOT_USERNAME", "the bot"), res.get("message_id")))
        return 0
    if len(text) > 4000:
        sys.exit("say-group: %d chars — Telegram's limit is 4000" % len(text))

    tok = bot_token(args.bot)
    chat = chat_id_of(args.chat, args.chat_id)
    url = "https://api.telegram.org/bot%s/sendMessage" % tok
    msg = {"chat_id": chat, "text": text, "link_preview_options": {"is_disabled": True}}
    if args.for_msg:
        msg["reply_parameters"] = reply_to(args.for_msg)
    body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request(
                url, data=body, method="POST",
                headers={"content-type": "application/json; charset=utf-8"}), timeout=40) as resp:
            answer = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {}
        why = payload.get("description") or ""
        # A group that became a supergroup answers 400 and NAMES the live chat in its parameters. Following
        # it is the difference between a message that lands and one that is refused forever (2026-11-06: the
        # watched list carried both ids and the title resolved to the dead one).
        migrate = (payload.get("parameters") or {}).get("migrate_to_chat_id")
        if migrate:
            try:
                moved = json.loads(body.decode("utf-8"))
                moved["chat_id"] = str(migrate)                      # the id travels in the BODY, not the URL
                with urllib.request.urlopen(urllib.request.Request(
                        url, data=json.dumps(moved).encode("utf-8"), method="POST",
                        headers={"content-type": "application/json; charset=utf-8"}), timeout=40) as resp:
                    answer = json.loads(resp.read().decode("utf-8", "replace"))
                chat = str(migrate)
            except (urllib.error.URLError, OSError, ValueError) as again:
                sys.exit("say-group: Telegram moved this chat to %s and would not take it there (%s)"
                         % (migrate, str(again).replace(tok, "***")))
        # Telegram's own words, with the token stripped: it is in the URL, and an error is a place it could leak.
        else:
            sys.exit("say-group: Telegram refused (%s) %s" % (e.code, why.replace(tok, "***")))
    except (urllib.error.URLError, OSError) as e:
        sys.exit("say-group: Telegram did not answer (%s)" % str(e).replace(tok, "***"))

    if not answer.get("ok"):
        sys.exit("say-group: Telegram refused (%s)" % (answer.get("description") or "").replace(tok, "***"))
    mid = (answer.get("result") or {}).get("message_id")
    if args.quiet:
        print(mid)
    else:
        print("posted to %s as @%s — message_id %s (%d chars)"
              % (chat, (answer.get("result") or {}).get("chat", {}).get("username")
                 or os.environ.get("TELEGRAM_BOT_USERNAME", "the bot"), mid, len(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
