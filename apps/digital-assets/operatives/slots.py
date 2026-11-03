#!/usr/bin/env python3
"""The digital-assets API's slots, one line each: what it is | its key | what it holds now (DGO-948).

    python3 apps/digital-assets/operatives/slots.py [content|identity|media] ['<word>'] [--via <office> <alias>]

One command, no pipe: it asks the API itself — the office's own (`http://digital-assets:8985`), or a
linked office's through `./bbox remote <office> <alias>`. Given a pipe (`curl … | slots.py`), it
reads that instead. Asked to pipe the API into this printer, gemma4:e2b ran the printer alone, read
nothing, and said there was no content (2026-10-21).

With a word, only the slots whose key or label carries it (a section holds up to 174), the word also
without the one-letter prefix Hebrew glues on («התמחור» finds «עמוד תמחור»); with several words, the
slots that carry each. Only slots that hold something are listed, and the rest are counted. An answer
that holds no slot list is printed as it came and exits 1. A slot's text is whatever was written into
it: it stays one line, its `|` made `¦`, cut at 200 characters.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SECTIONS = ("content", "identity", "media")
USAGE = "usage: slots.py [content|identity|media] ['<word>'] [--via <office> <alias>]"
HE_PREFIX = re.compile(r"^[והבלמשכ](?=[א-ת]{3,})")   # as ops.py: the one-letter prefixes Hebrew glues on

SHOWN = 600   # how much of an answer that is not a slot list is printed
MOST = 25     # slots listed; the rest are counted
TEXT = 200    # characters of one slot's text


def field(value, most=None):
    flat = " ".join(str(value if value is not None else "").split()).replace("|", "¦")
    return (flat[:most] + ("…" if len(flat) > most else "")) if most else flat


def held(slot):
    """What the slot holds now: its text, or the kind of file it has; None when empty. A media unit is
    a set, held once it has items (as the API's own overview counts it), whether or not one is active."""
    a = slot.get("active") if isinstance(slot.get("active"), dict) else {}
    if not a:
        n = slot.get("count")
        if slot.get("section") == "media" and isinstance(n, int) and n > 0:
            return f"({n} item(s))"
        return None
    text = a.get("text") if isinstance(a.get("text"), str) else a.get("value")
    if isinstance(text, str) and text.strip():
        return field(text, TEXT)
    return f"({field(a.get('kind') or slot.get('kind') or 'file')} {field(a.get('ext') or a.get('mime') or '')})".replace(" )", ")")


def lines(text, word=""):
    head = ""
    if text.startswith("HTTP "):
        head, _, text = text.partition("\n")
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    slots = data.get("slots") if isinstance(data, dict) else None
    if not isinstance(slots, list):
        said = text.strip()[:SHOWN] or "(the digital-assets API answered nothing)"
        return [x for x in (head.strip(), said) if x], 1
    w = word.strip().lower()
    forms = [{x, HE_PREFIX.sub("", x)} for x in w.split()]

    def carries(s):
        label = s.get("label") if isinstance(s.get("label"), dict) else {"": s.get("label") or ""}
        seen = " ".join([str(s.get("key", ""))] + [str(v) for v in label.values()]).lower()
        return all(any(f in seen for f in each) for each in forms)

    chosen = [s for s in slots if isinstance(s, dict) and carries(s)]
    full = [(s, held(s)) for s in chosen]
    full = [(s, h) for s, h in full if h is not None]
    out = []
    for s, h in full[:MOST]:
        label = s.get("label") if isinstance(s.get("label"), dict) else {}
        out.append(" | ".join((field(label.get("he") or label.get("en") or s.get("key"), 40), field(s.get("key")), h)))
    if len(full) > MOST:
        out.append(f"… and {len(full) - MOST} more that hold something")
    empty = len(chosen) - len(full)
    out.append(f"{len(full)} slot(s) hold something" + (f", {empty} are empty" if empty else "")
               + (f" (of those with «{word.strip()}»)" if w else ""))
    return out, 0


def placeholder(a):
    return a.startswith("<") and a.endswith(">")


def asked(args):
    """(section, word, (office, alias) or None) from the line — a placeholder left as it is
    («<word>», «<section>») counts as not given. `--via` without an office and an alias is a
    ValueError: read here instead, it would print this office's texts as the other office's."""
    via = None
    if "--via" in args:
        i = args.index("--via")
        via = tuple(args[i + 1:i + 3])
        if len(via) < 2 or any(placeholder(v) or v.startswith("-") for v in via):
            raise ValueError("--via needs an office and an alias, as `./bbox remote` names them")
        args = args[:i] + args[i + 3:]
    args = [a for a in args if not placeholder(a)]
    section = args.pop(0) if args and args[0] in SECTIONS else "content"
    return section, " ".join(args).strip(), via


def fetched(section, via):
    """What the API answered, as text — through `bbox remote` (its status line first) or straight."""
    path = f"/api/slots?section={section}"
    if via:
        run = subprocess.run(["./bbox", "remote", via[0], via[1], path], cwd=REPO, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=90, check=False)
        return run.stdout or run.stderr
    try:
        with urllib.request.urlopen("http://digital-assets:8985" + path, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}  GET http://digital-assets:8985{path}\n" + e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return f"(the digital-assets API did not answer: {e})"


def main():
    try:
        section, word, via = asked(sys.argv[1:])
    except ValueError as e:
        print(f"{e}\n{USAGE}", file=sys.stderr)
        return 2
    piped = sys.stdin.read() if not via and not sys.stdin.isatty() else ""
    printed, code = lines(piped if piped.strip() else fetched(section, via), word)
    print("\n".join(printed))
    return code


if __name__ == "__main__":
    sys.exit(main())
