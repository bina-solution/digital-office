#!/usr/bin/env python3
"""The Operative Collective (DGO-948): every operative of the office, where it can run, and the one a
request needs.

An operative is one plain-text recipe for one action — the shortest proven way to do it through the
office's CLI or API — kept by the app it belongs to, as `apps/<app>/operatives/<id>.md` (or under
platform-base/). Nothing declares them anywhere else: the directory is the declaration, as `hooks/` is.
The file is a short YAML front matter and numbered steps:

    ---
    id: tasks.comment                  # <group>.<action>, lower case
    title: Comment on a work item
    title_he: הערה על פריט עבודה
    when: ["הוסף הערה ל-DGO-123", "comment on DGO-123"]   # how people ask for it
    inputs: {ref: "the item, e.g. DGO-123", text: "the comment"}
    reaches_people: false              # true: it sends something a person receives
    check: the command prints "commented on DGO-<n>"
    ---
    1. ./bbox project-pln tasks comment <ref> "<text>"

Where an operative can run is computed, never written: here when its app is enabled in this office
(platform.state.yaml), through a linked office when that office publishes the app
(.generated/registry/remote.<office>.<alias>.json), otherwise nowhere. A request is matched to its
operative by the words of `when`, `title` and `title_he`; a small model is then handed that one recipe
instead of a list of everything the office can do.

Usage: ops.py list [<group>] | show <id> | find "<request>" [--show] | match (JSON on stdin) | check
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
import unicodedata

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
APP_ROOTS = ("apps", "platform-base")
MAX_BYTES = 3000                     # a recipe a 2B model reads in seconds, not a manual
REQUIRED = ("id", "title", "when", "check")
ID = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
SECRET = re.compile(r"(?i)(password|passwd|api[_-]?key|token|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}")


# ── reading ───────────────────────────────────────────────────────────────────────────────────────
def _scalar(text: str):
    text = text.strip()
    if text in ("true", "false"):
        return text == "true"
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return re.sub(r'\\(.)', r"\1", text[1:-1])
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    return text


# one item of a one-line YAML list or map: a double-quoted, a single-quoted or a plain value, up to its comma
_VALUE = r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^']|'')*'|[^,]*)"
_ITEM = re.compile(r"\s*" + _VALUE + r"\s*(?:,|$)")
_PAIR = re.compile(r"\s*([A-Za-z_][\w-]*)\s*:\s*" + _VALUE + r"\s*(?:,|$)")


def _flow(text: str):
    """A one-line YAML list or map, as the front matter writes them; each kind of quote is its own unit
    (an apostrophe inside "the person's language" is not a quote)."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    body = text.strip()[1:-1].strip()
    if text.strip().startswith("["):
        return [_scalar(m.group(1)) for m in _ITEM.finditer(body) if m.group(1).strip()]
    return {m.group(1): _scalar(m.group(2)) for m in _PAIR.finditer(body)}


def front_matter(text: str) -> tuple[dict, str]:
    """The YAML block between the first two `---` lines, and the steps after it. PyYAML when the
    machine has it; otherwise the small subset operatives use (scalars, one-line and dash lists, one
    level of maps), so the verb also runs in a container without PyYAML."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    head, body = m.group(1), m.group(2)
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        yaml = None
    if yaml is not None:
        try:
            meta = yaml.safe_load(head) or {}
        except yaml.YAMLError as error:            # one broken file is a problem to name, not a crash
            return {"_error": " ".join(str(error).split())}, body
        return (meta if isinstance(meta, dict) else {"_error": "the front matter is not a map"}), body
    meta: dict = {}
    key = None
    for line in head.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        line = re.sub(r"\s+#\s.*$", "", line)
        if line.startswith((" ", "\t")) and key is not None:
            s = line.strip()
            if s.startswith("- "):                   # a key left empty becomes a list at its first dash
                if not isinstance(meta.get(key), list):
                    meta[key] = []
                meta[key].append(_scalar(s[2:]))
            elif ":" in s:                           # … or a map at its first `name: value`
                if not isinstance(meta.get(key), dict):
                    meta[key] = {}
                k, _, v = s.partition(":")
                meta[key][k.strip()] = _scalar(v)
            continue
        k, _, v = line.partition(":")
        key = k.strip()
        v = v.strip()
        meta[key] = _flow(v) if v[:1] in "[{" else (_scalar(v) if v else None)
    return meta, body


def operatives() -> list[dict]:
    out = []
    for root in APP_ROOTS:
        for path in sorted(glob.glob(os.path.join(ROOT, root, "*", "operatives", "*.md"))):
            app = os.path.basename(os.path.dirname(os.path.dirname(path)))
            with open(path, encoding="utf-8") as f:
                text = f.read()
            meta, body = front_matter(text)
            out.append({**meta, "app": app, "path": os.path.relpath(path, ROOT).replace(os.sep, "/"),
                        "steps": body.strip(), "bytes": len(text.encode("utf-8"))})
    return out


def enabled_apps(path: str | None = None) -> dict[str, bool]:
    """app → enabled, from platform.state.yaml (`  <app>: { state: enabled, … }`); read, never written."""
    out: dict[str, bool] = {}
    try:
        with open(path or os.path.join(ROOT, "platform.state.yaml"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^  ([a-z][a-z0-9-]*):\s*\{[^}]*\b(?:state:\s*(\w+)|enabled:\s*(\w+))", line)
                if m:
                    out[m.group(1)] = (m.group(2) == "enabled") if m.group(2) else (m.group(3) == "true")
    except OSError:
        pass
    return out


def linked_apps() -> dict[str, list[tuple[str, str]]]:
    """app → [(office, alias)] that this office reaches over a link."""
    out: dict[str, list[tuple[str, str]]] = {}
    for path in sorted(glob.glob(os.path.join(ROOT, ".generated", "registry", "remote.*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        office = ((d.get("remote") or {}).get("office")) or ""
        if d.get("app") and office:
            out.setdefault(d["app"], []).append((office, d.get("alias") or d["app"]))
    return out


def where(op: dict, enabled: dict, linked: dict) -> str:
    app = op.get("app", "")
    if app == "operatives" or enabled.get(app):
        return "here"
    via = linked.get(app) or []
    # `link: false`: its steps work only where the app runs (`bbox b42` drives the LOCAL browser; a linked
    # office that publishes browser42 serves its live view, not its CLI)
    if via and op.get("link") is not False:
        return "via " + ", ".join(f"{office} ({alias})" for office, alias in via)
    return "not reachable from this office"


# ── checking ──────────────────────────────────────────────────────────────────────────────────────
def problems(ops: list[dict]) -> list[str]:
    out, seen = [], {}
    for op in ops:
        p = op["path"]
        if op.get("_error"):
            out.append(f"{p}: the front matter does not read: {op['_error'][:200]}")
            continue
        for key in REQUIRED:
            if not op.get(key):
                out.append(f"{p}: no `{key}`")
        oid = str(op.get("id") or "")
        if oid and not ID.match(oid):
            out.append(f"{p}: id `{oid}` is not <group>.<action> in lower case")
        if oid and os.path.splitext(os.path.basename(p))[0] != oid:
            out.append(f"{p}: the file is not named after its id ({oid}.md)")
        if oid in seen:
            out.append(f"{p}: id `{oid}` is also {seen[oid]}")
        seen[oid] = p
        if not isinstance(op.get("when"), list) or not all(isinstance(w, str) and w.strip() for w in op.get("when") or []):
            out.append(f"{p}: `when` is a list of requests as people say them")
        if not op.get("steps"):
            out.append(f"{p}: no steps after the front matter")
        if op["bytes"] > MAX_BYTES:
            out.append(f"{p}: {op['bytes']} bytes, more than {MAX_BYTES} — a recipe, not a manual")
        if SECRET.search(op.get("steps", "")):
            out.append(f"{p}: looks like it holds a secret — operatives name the vault, never a value")
        if not isinstance(op.get("reaches_people", False), bool):
            out.append(f"{p}: reaches_people is true or false")
        if not isinstance(op.get("acts", False), bool):
            out.append(f"{p}: acts is true or false")
        if not isinstance(op.get("adds", False), bool):
            out.append(f"{p}: adds is true or false")
        elif op.get("adds") and not op.get("acts"):
            out.append(f"{p}: adds is for an operative that acts (it only adds something new)")
        if not isinstance(op.get("link", True), bool):
            out.append(f"{p}: link is true or false")
        if not isinstance(op.get("inputs", {}) or {}, dict):
            out.append(f"{p}: inputs is a map of name → what to put there")
        for key in ("title", "title_he", "check"):
            if op.get(key) is not None and not isinstance(op.get(key), str):
                out.append(f"{p}: {key} is one line of text")
    return out


def usable(ops: list[dict]) -> list[dict]:
    """The operatives that pass `check`: a malformed one is named by `check`, never served (and never
    breaks `find` or `list` for all the others)."""
    return [op for op in ops if not problems([op])]


# ── matching ──────────────────────────────────────────────────────────────────────────────────────
HE_PREFIX = re.compile(r"^[והבלמשכ](?=[א-ת]{3,})")   # the one-letter prefixes Hebrew glues on
STOP = {"the", "a", "an", "to", "of", "and", "on", "in", "for", "me", "my", "please", "את", "של", "על",
        "לי", "אני", "זה", "גם", "עם", "בבקשה", "היי", "תעשה", "אפשר"}


def words(text: str) -> list[frozenset]:
    """Each distinct word of `text`, as the forms it may be met in: itself and, in Hebrew, without the
    one-letter prefix glued on («המייל» is also «מייל»). A word is ONE word however many forms it has:
    counted by its forms, «הלשכה» alone shared two words with «מה מצב הלשכה», and a status note about
    DGO-56 drew the recipe that closes an item."""
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))       # niqqud and accents
    out, seen = [], set()                  # a set beside the list: a 300 KB paste stays well under a second
    for w in re.findall(r"[a-z0-9]+|[א-ת]+", text):
        if w in STOP or w.isdigit():
            continue
        forms = frozenset({w, HE_PREFIX.sub("", w)})
        if forms not in seen:
            seen.add(forms)
            out.append(forms)
    return out


# A long request — a report above all — says what to do in its first words, and the rest of its words
# only dilute the measure: the owner's own «תדווח באג מה זה …» (2026-10-21, 14 words) scored 0.38 against
# «תדווח על באג». So a request is also measured by its first HEAD_WORDS words, against a `when` phrase that
# is there WHOLE and that the request OPENS with — and only for an operative that reads or only adds
# (`lenient`): a status note opening «DGO-56: הפריט לא בוצע» is no order to close an item.
HEAD_WORDS = 6


def lenient(op: dict) -> bool:
    """An operative whose misreading costs little: it reads, or it only ADDS something new (a report: an
    unwanted one is one more item, never a closed item, a sent mail, a posted comment)."""
    return not op.get("acts") or bool(op.get("adds"))


def cosine(part: list, have: list) -> tuple:
    """(the phrase's words the request carries, their cosine)."""
    met = frozenset().union(*part)
    shared = sum(1 for w in have if w & met)
    return shared, (shared / (len(part) * len(have)) ** 0.5 if part and have else 0.0)


def score(request: str, op: dict, asked: list = None, head: list = None) -> float:
    """`asked` and `head` are the request's words, read once by `rank` for every operative."""
    asked = words(request) if asked is None else asked
    if not asked:
        return 0.0
    head = words(" ".join(str(request).split()[:HEAD_WORDS])) if head is None else head
    when = [words(p) for p in op.get("when") or []]
    titles = [words(str(op.get(k) or "")) for k in ("title", "title_he")]
    best = 0.0
    for have in when + titles:
        shared, value = cosine(asked, have)
        # one shared word is chance ("שלח לי את זה" is not a mail): a phrase counts from two
        if shared >= 2:
            best = max(best, value)
    # The head counts when the request opens with the phrase's own first word: its first MEANINGFUL word
    # for an operative that reads or adds, its very first word for one that acts — «תשלח מייל ל-…» is an
    # order, «To send an email to customers, n8n uses …» is not, though both carry «send an email».
    opener = words(str(request).split()[0]) if str(request).split() else []
    lead = head[:1] if lenient(op) else opener[:1]
    if lead:
        for have in when:
            shared, value = cosine(head, have)
            if shared >= 2 and shared == len(have) and lead[0] & have[0]:
                best = max(best, value)
    return round(best, 3)


# Below this a request is not an errand an operative covers ("1000 words on love" shares one word with
# mail.find and scored 0.32; the weakest right match of the owner's real errands scored 0.55).
MIN_SCORE = 0.45


# A request that FORBIDS something, or asks whether it was done, is no order to do it: matched by words
# alone, «אל תסגור את DGO-950» got the recipe that closes it and «did you send the email?» the one that
# sends. Three tiers, from the request's own words:
#   1. it forbids (`holds_back`) — «אל …», «אסור», «don't», «do not», a «never» or «stop» that opens a
#      clause, «לא / בלי / not to» before a verb's infinitive — or it ends with «?», or opens with a
#      question word and carries one: only operatives that read;
#   2. any other negation or «?» (`wary` — «הפריט DGO-950 לא בוצע», «סגרת את הפריט?!», «תדאג שלא תשלח
#      מייל»): operatives that read or only add — a report says what does NOT work, but «not done» is no
#      order to close and «you sent it?!» none to send;
#   3. otherwise: every operative.
# Tier 1 must not take the «לא» a report is made of («הקונסול לא נטען», «זה לא לגמרי עובד, תפתח באג»), so
# «לא ל…» counts only before an infinitive, never before «לגמרי» or a present tense like «לוחץ».
INFINITIVES = ("לשלוח", "לסגור", "לפתוח", "לדווח", "למחוק", "לעשות", "לגעת", "להריץ", "לשנות", "ליצור",
               "לכתוב", "להוסיף", "לצלם", "להתחיל", "לבצע", "לסמן", "לענות", "לפרסם", "להעביר", "לשתף",
               "לעדכן", "להעלות", "להפעיל", "לעצור", "לבטל")
PROHIBITION = re.compile(
    r"(?:^|[\s,.!?])[ו]?(?:אל|אסור|don['’]?t|do not|(?:לא|בלי)\s+(?:" + "|".join(INFINITIVES) + r")|not\s+to)"
    r"(?=[\s,.!?]|$)|(?:^|[,.!?;:]\s*)(?:never|stop)\b", re.I)
WARY = re.compile(r"(?:^|[\s,.!?])[וש]?(?:אל|לא|אסור|בלי|אין|don['’]?t|do not|never|not|no need|stop)(?=[\s,.!?]|$)",
                  re.I)
# The «??» of exasperation in the middle of a report is no question (the owner's «… שהוא לא יכול ?? הוא
# יכול!!», 2026-10-21); a request that ENDS with «?» is.
QUESTION_WORDS = {"האם", "מה", "למה", "מדוע", "איך", "מתי", "איפה", "כמה", "מי", "אילו", "did", "do", "does",
                  "have", "has", "is", "are", "was", "were", "can", "could", "will", "would", "should", "why",
                  "what", "how", "when", "where", "who", "which"}


# An English question needs no «?»: «did you send an email to dana» drew the recipe that sends.
ASKED = re.compile(r"^(?:did|do|does|have|has|is|are|was|were)\s+(?:you|it|we|they|i|he|she|that|this)\b", re.I)
# A Hebrew sentence that opens with what YOU did («סגרת את הפריט», «שלחת את המייל») tells or asks; it orders
# nothing — an order opens with «ת…» («תסגור», «תשלח») or the imperative («סגור», «שלח»).
DID = re.compile(r"^ו?[א-ש][א-ת]+(?:ת|תם|תן)$")


def holds_back(request: str) -> bool:
    text = str(request).strip()
    first = text.split()[0].strip("?!.,:;").lower() if text else ""
    asks = text.endswith("?") or ("?" in text and first in QUESTION_WORDS) or bool(ASKED.match(text))
    return asks or bool(PROHIBITION.search(text))


def wary(request: str) -> bool:
    text = str(request).strip()
    first = text.split()[0].strip("?!.,:;") if text else ""
    return "?" in text or bool(WARY.search(text)) or bool(DID.match(first))


def ordered(request: str, ops: list[dict], asked: list) -> list[dict]:
    """The operatives that only add whose `when` phrase the request carries WHOLE — an order to report in
    the request's own words («תפתח באג», "report a bug"). It is that order whatever else the request says:
    «יש הרצות תקועות ב-n8n, תפתח באג» carries n8n.runs' own question too and drew the read, and «מה מצב
    הצ׳אט? הוא לא נטען, תפתח באג» asks before it orders (DGO-1039)."""
    met = frozenset().union(*asked) if asked else frozenset()
    return [op for op in ops if op.get("adds") and any(
        len(have) >= 2 and all(w & met for w in have) for have in (words(p) for p in op.get("when") or []))]


def rank(request: str, ops: list[dict], top: int = 3) -> list[tuple[float, dict]]:
    asked, head = words(request), words(" ".join(str(request).split()[:HEAD_WORDS]))
    orders = ordered(request, ops, asked)
    text = str(request).strip()
    # still no order: «אל תפתח באג», "did you report a bug?", a request that ENDS asking. (Not DID: it
    # takes a plural noun, «הרשתות …», for "what you did"; a misread here costs one item too many.)
    if orders and not (PROHIBITION.search(text) or ASKED.match(text) or text.endswith("?")):
        ops = orders
    elif holds_back(request):
        ops = [op for op in ops if not op.get("acts")]
    elif wary(request):
        ops = [op for op in ops if lenient(op)]
    ranked = sorted(((score(request, op, asked, head), op) for op in ops), key=lambda r: -r[0])
    return [r for r in ranked[:top] if r[0] >= MIN_SCORE]


def find(request: str, ops: list[dict], top: int = 3) -> list[tuple[float, dict]]:
    """The operatives a request needs, best first — none when two tie at the top: "open DGO-950" fits
    four task operatives equally, and taking the first in file order could pick one that writes."""
    hits = rank(request, ops, top)
    if len(hits) > 1 and hits[0][0] == hits[1][0]:
        return []
    return hits


# ── the verbs ─────────────────────────────────────────────────────────────────────────────────────
VARIANT = re.compile(r"^(\s*(?:(?:[-*+]|\d+\.)\s+)?)(here|linked):\s*", re.I)


def steps_for(op: dict, enabled: dict, linked: dict) -> str:
    """The steps as they run from THIS office. A step line marked `here:` or `linked:` is one way of
    doing it; only the way that works here is kept, unmarked, and `<office>`/`<alias>` are filled in.
    Handed both, a small model took the `here` command for mail on an office whose mail is on vps1, got
    nothing back, and reported "no new mail" (2026-10-21 14:50 UTC)."""
    app = op.get("app", "")
    local = app == "operatives" or bool(enabled.get(app))
    via = (linked.get(app) or [("", "")])[0]
    out = []
    for line in str(op.get("steps") or "").splitlines():
        m = VARIANT.match(line)
        if m:
            if (m.group(2).lower() == "here") != local:
                continue
            line = m.group(1) + line[m.end():]
        if not local and via[0]:
            line = line.replace("<office>", via[0]).replace("<alias>", via[1])
        out.append(line)
    return "\n".join(out)


def show_text(op: dict, enabled: dict, linked: dict, ids: bool = True) -> str:
    """The recipe as a person reads it (`show`, `find --show`), or, with `ids=False`, as the relay
    hands it to the model: without the operative's id. A small model takes an id for a name it can use:
    gemma4:e2b ran `cat assets.show`, and called a tool named `browser.read` (2026-10-22)."""
    place = where(op, enabled, linked)
    name = f"{op.get('id')} — {op.get('title')}" if ids else str(op.get("title"))
    lines = ["# " + name + (f" · {op['title_he']}" if op.get("title_he") else ""), f"where: {place}"]
    if place.startswith("not reachable"):
        # its app is neither here nor in a linked office: steps with `<office>` left in them would only
        # be a broken command (bash reads `<office` as a redirect)
        return "\n".join(lines + ["", "This does not run from this office: say so, and which app it needs."])
    if op.get("inputs"):
        lines.append("inputs: " + "; ".join(f"{k} = {v}" for k, v in dict(op["inputs"]).items()))
    if op.get("reaches_people"):
        lines.append("reaches people: yes — when the request does not name the recipient, ask first")
    lines += ["", steps_for(op, enabled, linked), "", f"done when: {op.get('check')}"]
    return "\n".join(lines)


def match_many(texts: list, ops: list[dict], enabled: dict, linked: dict) -> list[str]:
    """Each text's recipe as `find --show` prints it, "" for none — many in one call (the relay asks for
    every message of a conversation at once instead of starting a process per message)."""
    out = []
    for text in texts:
        hits = find(str(text or ""), ops)
        out.append(show_text(hits[0][1], enabled, linked, ids=False) if hits else "")
    return out


def main(argv: list[str]) -> int:
    verb = argv[1] if len(argv) > 1 else "list"
    every = operatives()
    ops = usable(every)
    enabled, linked = enabled_apps(), linked_apps()
    if verb == "list":
        group = argv[2] if len(argv) > 2 else ""
        rows = [op for op in ops if not group or str(op.get("id", "")).startswith(group + ".")]
        for op in sorted(rows, key=lambda o: str(o.get("id"))):
            print(f"{str(op.get('id') or '?'):24} {str(op.get('title') or ''):42} {where(op, enabled, linked)}")
        print(f"{len(rows)} operative(s)" + (f" ({len(every) - len(ops)} malformed — `bbox ops check`)" if len(every) > len(ops) else ""))
        return 0
    if verb == "show" and len(argv) > 2:
        hit = [op for op in ops if op.get("id") == argv[2]]
        if not hit:
            print(f"no operative {argv[2]} — `bbox ops list` names them", file=sys.stderr)
            return 1
        print(show_text(hit[0], enabled, linked))
        return 0
    if verb == "find" and len(argv) > 2:
        request = " ".join(a for a in argv[2:] if a != "--show")
        hits = find(request, ops)
        if not hits:
            tied = rank(request, ops)
            if len(tied) > 1:
                names = " or ".join(str(op.get("id")) for s, op in tied if s == tied[0][0])
                print(f"the request fits {names} equally — ask which is meant", file=sys.stderr)
            else:
                print("no operative matches — do it the ordinary way, or say what is missing", file=sys.stderr)
            return 1
        if "--show" in argv:
            print(show_text(hits[0][1], enabled, linked))
            return 0
        for s, op in hits:
            print(f"{s:5.2f}  {str(op.get('id') or '?'):24} {str(op.get('title') or ''):42} {where(op, enabled, linked)}")
        return 0
    if verb == "match":                      # stdin: a JSON list of texts → stdout: a JSON list of recipes
        try:
            texts = json.loads(sys.stdin.read() or "[]")
        except ValueError:
            print("match reads a JSON list of texts on stdin", file=sys.stderr)
            return 2
        if not isinstance(texts, list):
            print("match reads a JSON list of texts on stdin", file=sys.stderr)
            return 2
        print(json.dumps(match_many(texts, ops, enabled, linked), ensure_ascii=False))
        return 0
    if verb == "check":
        ops = every
        bad = problems(ops)
        for b in bad:
            print(b)
        print(f"{len(ops)} operative(s), {len(bad)} problem(s)")
        return 1 if bad else 0
    print(__doc__.strip().splitlines()[-1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
