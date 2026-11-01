"""The organizer options plane — THE store of label rules (RELEASE-DECISIONS N1 + N2).

ONE document, ``/data/organizer-defaults.json`` on the ``gmail_imap_data`` volume::

    {"mail": {"organizer": {"mode": "default", "rules": [ROW, ...]}},
     "saved_at": "<iso>",
     "previous": {"mail": {...}, "saved_at": "<iso>"}}      # one level, for POST /organizer/rollback

Every mailbox in the registry evaluates the same rules. The per-connection override plane that
used to sit beside this (``/data/options/<instance_id>.json``, ``mode: "override"``,
``/connections/<cid>/options``, ``/organizer/effective/<cid>``) had zero callers anywhere in the
tree and is gone; ``mode`` survives as a key the editor round-trips, and the only value it may
carry is ``"default"`` — accepting ``"override"`` would be a knob that does nothing.

ROW is the shape the label engine consumes (``mailLabelEngine01.workflow.ts``)::

    {"KEY": "DOC_TO_SYNC",            # uppercase snake, unique — the identifier callers speak
     "LABEL": "לטיפול-אוטומציה-...",   # the Gmail label NAME, or "-NAME" to REMOVE it
     "RULE": "attachments.length > 0 && ...",   # a JS expression the engine evaluates
     "TYPE": "ON_CREATE_EVENT",        # the only load-bearing switch, OR the system sentinel form
     "EVENT": "ON_CREATE",             # informational
     "enabled": true,                  # N2: a per-rule flag the engine honours (default true)
     "row_number": 12,                 # priority: evaluated in this order, renumbered 1..n on write
     "label_id": "Label_11", "id": 11} # pass-through

A SYSTEM row (a state mark the sync pipeline stamps, never a rule the engine should fire) is
written as ``TYPE == KEY`` with a RULE that can never match — byte-compatible with
``fixtures/tag_rules.json`` and with every live document seeded from it.

VALIDATION happens HERE, before any write (``put_defaults``), so the seed, the editor and curl are
held to the same rules — see ``validate``. A refused document answers with a list of
``{row, field, message}`` problems the editor can pin to cells. ``check_rule_syntax`` is a
CONSERVATIVE static check of the RULE expression: balanced brackets, terminated strings, and only
the identifiers the engine's evaluator actually binds (``new Function("email", "thread",
"attachments", <18 helpers>, ...)`` — ``mailLabelEngine01.workflow.ts:786-854`` and ``:1033-1041``)
plus JS literals, operators, property access and arrow-function parameters. It rejects anything it
does not understand rather than guessing — a rule that passes here can still be wrong, but a rule
that fails here would have thrown (and silently evaluated to ``false``) inside the engine.

Writes are atomic (write-then-``os.replace``), guarded by one lock — gunicorn runs threaded.
"""
import datetime
import json
import os
import re
import threading

DEFAULTS_PATH = os.environ.get("ORGANIZER_DEFAULTS_PATH", "/data/organizer-defaults.json")

_lock = threading.Lock()

# ── the vocabulary the engine binds (mailLabelEngine01.workflow.ts) ───────────────────────────
RULE_TYPE_EVENT = "ON_CREATE_EVENT"
NEVER_MATCH = "__NEVER_MATCH_SYNC_STATE__"
PROCESSED_KEY = "PROCESSED"

HELPERS = (
    # string utilities (:786-819)
    "contains", "containsAny", "containsAll", "startsWith", "endsWith", "matches",
    "isEmpty", "isNotEmpty", "hasHebrew", "hasNonHebrewChars", "noHebrew",
    # array utilities (:822-831)
    "includes", "includesAny", "includesAll", "len",
    # email utilities (:836-854)
    "isDomain", "isAnyDomain", "inList",
)
DATA_OBJECTS = ("email", "thread", "attachments")
LITERAL_WORDS = ("true", "false", "null", "undefined")
ALLOWED_IDENTIFIERS = frozenset(HELPERS + DATA_OBJECTS + LITERAL_WORDS)

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
MAX_RULE_CHARS = 50_000

# The organizer-level keys this service understands. Anything else at that level is a knob nobody
# reads (`enabled`/`schedule_min`/`batch_limit` were seeded for two months and read by nothing),
# so it is DROPPED on write and named in the response rather than stored as if it did something.
_ORGANIZER_KEYS = ("mode", "rules")
_ROW_NUMBER_INF = float("inf")


class ValidationError(ValueError):
    """The document was refused. `problems` is the list the editor pins to cells."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("organizer rules refused: %d problem(s) — see `problems`" % len(self.problems))


class ProcessedGuard(Exception):
    """A PUT would delete or rename the PROCESSED row without saying so (409)."""


class NothingToRollBack(Exception):
    """POST /organizer/rollback with no `previous` snapshot on disk (409)."""


# ── storage ───────────────────────────────────────────────────────────────────────────────────
def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, doc):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def get_defaults():
    """The stored document, verbatim (including `previous`). Readers that only want the rules go
    through `rules_of`; the HTTP layer uses `public_view` to keep the snapshot off the wire."""
    with _lock:
        return _load(DEFAULTS_PATH)


def rules_of(doc):
    """Extract the tag-rule rows from a document."""
    org = ((doc.get("mail") or {}).get("organizer")) or {}
    rules = org.get("rules")
    return rules if isinstance(rules, list) else []


def enabled_of(row):
    """N2: every row carries `enabled`; a legacy row without it is enabled."""
    v = row.get("enabled", True)
    return v if isinstance(v, bool) else True


def processed_row(doc):
    for r in rules_of(doc):
        if isinstance(r, dict) and r.get("KEY") == PROCESSED_KEY:
            return r
    return None


def public_view(doc):
    """(document without `previous`, rollback info) — what GET/PUT answer with."""
    doc = dict(doc or {})
    prev = doc.pop("previous", None)
    info = {"available": bool(prev),
            "saved_at": (prev or {}).get("saved_at"),
            "rules": len(rules_of(prev)) if prev else 0}
    return doc, info


# ── the RULE expression check ─────────────────────────────────────────────────────────────────
_TOKEN_RE = re.compile(r"""
      (?P<ws>\s+)
    | (?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
    | (?P<num>\d+(?:\.\d+)?)
    | (?P<ident>[A-Za-z_$][A-Za-z0-9_$]*)
    | (?P<op>=>|===|!==|==|!=|<=|>=|&&|\|\||\?\?|\?\.|[!<>+\-*/%?:,.()\[\]])
    | (?P<bad>[=;{}`])
    | (?P<other>.)
""", re.X | re.S)
_OPEN = {"(": ")", "[": "]"}
_CLOSE = {")": "(", "]": "["}
_BAD_MESSAGE = {
    "=": "assignment '=' is not allowed (use === to compare)",
    ";": "';' is not allowed — a rule is one expression",
    "{": "'{' is not allowed — object literals and block bodies are not part of the rule grammar",
    "}": "'}' is not allowed — object literals and block bodies are not part of the rule grammar",
    "`": "template literals are not allowed — use \"...\" strings",
}


def _tokens(rule):
    """(kind, text, pos) for every token; kind 'bad'/'other' are reported by the caller."""
    out = []
    for m in _TOKEN_RE.finditer(rule):
        kind = m.lastgroup
        if kind == "ws":
            continue
        out.append((kind, m.group(kind), m.start()))
    return out


def _arrow_params(toks):
    """Identifiers bound by arrow functions in the rule: `a => ...` and `(a, b) => ...`."""
    params = set()
    for i, (kind, text, _pos) in enumerate(toks):
        if not (kind == "op" and text == "=>"):
            continue
        if i >= 1 and toks[i - 1][0] == "ident":
            params.add(toks[i - 1][1])
            continue
        if i >= 1 and toks[i - 1] [1] == ")":
            j = i - 2
            while j >= 0 and toks[j][1] != "(":
                if toks[j][0] == "ident":
                    params.add(toks[j][1])
                elif toks[j][1] != ",":
                    break
                j -= 1
    return params


def check_rule_syntax(rule):
    """Messages describing why `rule` is refused; an empty list means it passed."""
    problems = []
    if not isinstance(rule, str) or not rule.strip():
        return ["RULE must be a non-empty expression"]
    if len(rule) > MAX_RULE_CHARS:
        return ["RULE is longer than %d characters" % MAX_RULE_CHARS]
    toks = _tokens(rule)
    # Unterminated strings surface as a lone quote character that the `str` branch could not match.
    for kind, text, pos in toks:
        if kind == "other":
            if text in ("\"", "'"):
                problems.append("unterminated string starting at character %d" % (pos + 1))
            else:
                problems.append("unexpected character %r at %d" % (text, pos + 1))
        elif kind == "bad":
            problems.append(_BAD_MESSAGE[text])
    if problems:
        return problems
    stack = []
    for kind, text, pos in toks:
        if kind != "op":
            continue
        if text in _OPEN:
            stack.append((text, pos))
        elif text in _CLOSE:
            if not stack or stack[-1][0] != _CLOSE[text]:
                problems.append("unbalanced %r at character %d" % (text, pos + 1))
                return problems
            stack.pop()
    if stack:
        problems.append("unclosed %r opened at character %d" % (stack[-1][0], stack[-1][1] + 1))
        return problems
    bound = _arrow_params(toks)
    prev = None
    for kind, text, pos in toks:
        if kind == "ident" and not (prev is not None and prev[0] == "op" and prev[1] in (".", "?.")):
            if text not in ALLOWED_IDENTIFIERS and text not in bound:
                problems.append(
                    "unknown identifier %r at character %d — a rule may use email/thread/attachments, "
                    "the helpers (%s), true/false/null and arrow parameters"
                    % (text, pos + 1, ", ".join(HELPERS)))
        prev = (kind, text)
    last = toks[-1]
    if last[0] == "op" and last[1] not in (")", "]"):
        problems.append("RULE ends with an operator (%r)" % last[1])
    return problems


# ── document validation ───────────────────────────────────────────────────────────────────────
def validate(doc):
    """Return ``(normalized_document, ignored_keys)`` or raise ValidationError.

    Normalisation: `enabled` defaults to true, rows are ordered by `row_number` (list order breaks
    ties, rows without one go last) and renumbered 1..n, organizer-level keys this service does
    not understand are dropped and named in `ignored_keys`. Nothing else is rewritten — a LABEL
    keeps its spelling, trailing space included: the fixture spells what production spells.
    """
    problems = []
    if not isinstance(doc, dict):
        raise ValidationError([{"row": None, "field": "", "message": "body must be a JSON object"}])
    mail = doc.get("mail")
    org = mail.get("organizer") if isinstance(mail, dict) else None
    if not isinstance(org, dict):
        raise ValidationError([{"row": None, "field": "mail.organizer",
                                "message": "body must carry {mail: {organizer: {rules: [...]}}}"}])
    rules = org.get("rules")
    if not isinstance(rules, list):
        raise ValidationError([{"row": None, "field": "mail.organizer.rules",
                                "message": "rules must be a list"}])
    mode = org.get("mode", "default")
    if mode not in (None, "default"):
        problems.append({"row": None, "field": "mail.organizer.mode",
                         "message": "mode may only be \"default\": every mailbox evaluates the one "
                                    "rule set, there is no per-connection override any more"})
    ignored = sorted(k for k in org if k not in _ORGANIZER_KEYS)

    seen = {}
    rows = []
    for i, r in enumerate(rules):
        if not isinstance(r, dict):
            problems.append({"row": i, "field": "", "message": "each rule must be an object"})
            continue
        key = r.get("KEY")
        if not isinstance(key, str) or not key.strip():
            problems.append({"row": i, "field": "KEY", "message": "KEY is required"})
        elif not _KEY_RE.match(key):
            problems.append({"row": i, "field": "KEY",
                             "message": "KEY must be UPPER_SNAKE_CASE (A-Z, 0-9, _; starts with a letter)"})
        elif key in seen:
            problems.append({"row": i, "field": "KEY",
                             "message": "duplicate KEY %r (also row %d)" % (key, seen[key])})
        else:
            seen[key] = i
        label = r.get("LABEL")
        if not isinstance(label, str) or not label.strip():
            problems.append({"row": i, "field": "LABEL", "message": "LABEL is required"})
        elif label.strip() == "-":
            problems.append({"row": i, "field": "LABEL", "message": "\"-\" names nothing to remove"})
        rule = r.get("RULE")
        rule_problems = check_rule_syntax(rule)
        for msg in rule_problems:
            problems.append({"row": i, "field": "RULE", "message": msg})
        typ = r.get("TYPE")
        if typ == RULE_TYPE_EVENT:
            pass
        elif isinstance(typ, str) and typ and typ == key:
            if not (isinstance(rule, str) and NEVER_MATCH in rule):
                problems.append({"row": i, "field": "TYPE",
                                 "message": "TYPE == KEY marks a SYSTEM row, whose RULE must be the "
                                            "never-match sentinel contains(email.text, \"%s\")" % NEVER_MATCH})
        else:
            problems.append({"row": i, "field": "TYPE",
                             "message": "TYPE must be %s, or equal to KEY for a system mark" % RULE_TYPE_EVENT})
        ev = r.get("EVENT")
        if ev is not None and not isinstance(ev, str):
            problems.append({"row": i, "field": "EVENT", "message": "EVENT must be a string"})
        en = r.get("enabled", True)
        if not isinstance(en, bool):
            problems.append({"row": i, "field": "enabled", "message": "enabled must be true or false"})
        rn = r.get("row_number")
        if rn is not None and (isinstance(rn, bool) or not isinstance(rn, int)):
            problems.append({"row": i, "field": "row_number", "message": "row_number must be an integer"})
        lid = r.get("label_id")
        if lid is not None and not isinstance(lid, str):
            problems.append({"row": i, "field": "label_id", "message": "label_id must be a string or null"})
        row = dict(r)
        row["enabled"] = en if isinstance(en, bool) else True
        rows.append((rn if isinstance(rn, int) and not isinstance(rn, bool) else _ROW_NUMBER_INF, i, row))
    if problems:
        raise ValidationError(problems)

    rows.sort(key=lambda t: (t[0], t[1]))
    ordered = []
    for n, (_rn, _i, row) in enumerate(rows, 1):
        row["row_number"] = n
        ordered.append(row)
    out = {"mail": {"organizer": {"mode": "default", "rules": ordered}}}
    return out, ignored


def _guard_processed(current, new, confirm):
    """Deleting or renaming PROCESSED silently would make the engine re-process the whole mailbox
    every tick (it is the engine's only state — RELEASE-DECISIONS §2.3). Refuse unless confirmed."""
    if confirm:
        return
    old = processed_row(current)
    now = processed_row(new)
    if now is None:
        raise ProcessedGuard(
            "no %s row: the label engine stamps it on every message it finishes and uses it as its "
            "only cursor, so without it every tick re-processes the whole mailbox. Add the row back, "
            "or send {\"confirm_processed\": true} with the document to remove it anyway." % PROCESSED_KEY)
    if old is not None and (old.get("LABEL") or "").strip() != (now.get("LABEL") or "").strip():
        raise ProcessedGuard(
            "renaming %s from %r to %r orphans every message already stamped with the old name — "
            "the engine would treat all of them as unprocessed. Send {\"confirm_processed\": true} "
            "with the document to rename it anyway." % (PROCESSED_KEY, (old.get("LABEL") or "").strip(),
                                                        (now.get("LABEL") or "").strip()))


def put_defaults(doc, confirm_processed=False):
    """Validate, guard, snapshot the current document into `previous`, write. Returns
    ``(stored_document, ignored_keys)``."""
    new, ignored = validate(doc)
    with _lock:
        current = _load(DEFAULTS_PATH)
        _guard_processed(current, new, confirm_processed)
        if current:
            new["previous"] = {k: v for k, v in current.items() if k != "previous"}
        new["saved_at"] = _now()
        _save(DEFAULTS_PATH, new)
        return new, ignored


def rollback():
    """Swap the document with its `previous` snapshot (so a rollback can itself be rolled back).
    The snapshot is restored as it was written — it passed validation then, or predates it and is
    what the engine was running on."""
    with _lock:
        current = _load(DEFAULTS_PATH)
        prev = current.get("previous")
        if not isinstance(prev, dict) or not prev:
            raise NothingToRollBack("nothing to roll back to — no previous document is stored")
        restored = dict(prev)
        restored["previous"] = {k: v for k, v in current.items() if k != "previous"}
        restored["restored_at"] = _now()
        restored["saved_at"] = restored["restored_at"]
        _save(DEFAULTS_PATH, restored)
        return restored
