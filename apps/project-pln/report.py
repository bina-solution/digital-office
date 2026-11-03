#!/usr/bin/env python3
"""A report (a bug, a request) made through the office's agent, as a DGO work item declared in a plan
file of the office's own (DGO-948).

    python3 report.py add --office <name> "<title>" [--body @<file> | --body "<text>"] [--priority …]
                      [--plan <file>]

A work item here is DATA in the repo first (plans/*.yaml) and Plane its rendering — `plan` applies a
file, and `--only <key>` applies one item of it in seconds (DGO-559). A report gets a file per office,
plans/reports-<office>.yaml, made on first use: office.yaml is where other writers keep uncommitted
hunks, and two offices appending to one file would meet in every merge of their branches.

The key names the office and the second it was made: rep-<office>-<yymmdd>-<HHMMSS>. `plan` upserts by
key, so a key used twice would rewrite the first report in Plane — and a counter read from this file
would repeat after the file is lost (it is untracked until someone commits it) or on two offices with
one name (`local` on a fresh clone). A second within the same second gets `-2`.

`add` checks the whole file with the item in it before writing, then APPENDS the item (what is in the
file is never rewritten, so a full disk can cost only the new item), and prints `KEY=<key>` and
`FILE=<path>` for hooks/report, which applies it.
"""
import argparse
import datetime
import json
import os
import re
import sys

import yaml
import yaml.reader

try:
    import fcntl          # every office runs bbox on Linux or macOS (Windows through WSL)
except ImportError:       # a test run on Windows itself: one writer, no lock
    fcntl = None

HERE = os.path.dirname(os.path.abspath(__file__))
PRIORITIES = ("urgent", "high", "medium", "low", "none")
LABEL = "דיווח"
TITLE_MAX = 200

HEADER = """\
# apps/project-pln/plans/reports-{office}.yaml — the reports made through the {office} office's agent.
# `./bbox project-pln report --said` (or `report '<words>'`) adds one here and applies it at once
# (hooks/report, report.py). One file per office, so two offices' reports never meet in a merge; each key
# names its office and its second, so none is ever used twice. Like every plan: data in the repo,
# rendered into Plane, never deleted.
project: {{ identifier: DGO }}

labels:
  - {{ name: {label} }}

modules:
- key: r-{office}
  name: דיווחים · {office}
  status: backlog
  description: 'מה שדווח דרך הסוכן של הלשכה {office}: כל דיווח הוא פריט עבודה.'
  items:
"""


def office_name(raw: str) -> str:
    """The office's DEPLOYMENT_NAME as a key part: a hand-set `HP_Office` is `hp-office`, not a refusal
    of every report that office will ever make."""
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-") or "office"


def plan_path(office: str) -> str:
    return os.path.join(HERE, "plans", f"reports-{office_name(office)}.yaml")


def printable(text: str) -> str:
    """What YAML cannot carry — a terminal's colour codes, NUL, DEL, C1 controls — as U+FFFD, by the
    parser's own rule; a report is never refused for a character pasted along with it."""
    return yaml.reader.Reader.NON_PRINTABLE.sub("�", text)


def body_of(arg: str) -> str:
    """`@<file>` is that file's text (an agent writes it with its file tool, so nothing the person said
    meets a shell); anything else is the text itself."""
    if arg.startswith("@"):
        with open(arg[1:], encoding="utf-8", errors="replace") as f:
            return f.read()
    return arg


def unwrapped(text: str) -> str:
    """A recipe's placeholder bracket a small model kept: `'<title>'` came back as «<tasks show …» (twice
    in four calls, 2026-10-21). A `<` with no `>` anywhere (or the reverse) is the placeholder's, not the
    person's."""
    text = text.strip()
    if text.startswith("<") and ">" not in text:
        text = text[1:]
    if text.endswith(">") and "<" not in text:
        text = text[:-1]
    return text


# Given only the person's words (the one argument a small model fills best — asked for a title AND a
# text, gemma4:e2b stopped to say it had neither, 2026-10-21), the title is their first sentence, without
# the order that opened it («תדווח באג:», «report a bug:»), cut at a word.
# (the «ש» of «that» only before the words a clause opens with: «שהקונסול», «שלא» — never «שרת»)
ORDER = re.compile(r"^(?:ו?(?:תדווח|דווח|תפתח|פתח|תיצור|צור|יצור)\s+(?:את\s+)?(?:על\s+)?(?:זה\s+)?"
                   r"(?:כ?באג|פריט(?:\s+עבודה)?|ה?משימ[הת](?:\s+חדשה)?)"
                   r"|(?:please\s+)?(?:report|open|file)\s+(?:a\s+)?(?:bug|ticket|issue))(?![א-תa-z])"
                   r"\s*(?:על\s+|ש(?=ה|לא|אין|את|הוא|היא|זה|יש|אני|אתה)|about\s+|that\s+)?[:,—-]*\s*", re.I)
# The words of an order to report, which say nothing of what is wrong: a message made only of them
# («Wtf ??? Report bug», «תדווח על זה כבאג») is about the message before it.
ORDER_WORDS = {"report", "bug", "ticket", "issue", "open", "file", "please", "wtf", "this", "it", "as", "a",
               "תדווח", "ותדווח", "דווח", "באג", "כבאג", "תפתח", "פריט", "עבודה", "משימה", "משימת", "המשימה",
               "חדשה", "על", "זה", "את", "בבקשה", "תיצור", "צור", "יצור"}
# («תפתח את המשימה DGO-950» opens one to look at — no report; «תיצור משימה» makes one)
REPORTISH = re.compile(r"באג|דווח|bug|report|ticket|issue|תפתח\s+(?:פריט|משימה)|(?:תיצור|צור|יצור)\s+(?:את\s+)?ה?משימ",
                       re.I)
TITLE_CUT = 120


def title_of(text: str) -> str:
    said = " ".join(text.split())
    line = " ".join((text.strip().splitlines() or [""])[0].split())
    first = re.split(r"(?<=[.!?])\s", line, maxsplit=1)[0]
    first = ORDER.sub("", first).strip(" :,—-") or ORDER.sub("", said).strip(" :,—-") or said
    if len(first) > TITLE_CUT:
        first = first[:TITLE_CUT].rsplit(" ", 1)[0] + "…"
    return first


def item_text(key: str, title: str, body: str, priority: str, office: str, when: str) -> str:
    lines = [f"  - key: {key}",
             f"    name: {json.dumps(title, ensure_ascii=False)}",
             f"    priority: {priority}",
             "    labels:",
             f"    - {LABEL}",
             "    description: |"]
    said = [l.rstrip() for l in (body.strip() or title).splitlines()]
    lines += ["      " + ("מה דווח: " if i == 0 else "") + l if l else "" for i, l in enumerate(said)]
    lines.append(f"      מקור: דיווח דרך הסוכן של הלשכה {office}, {when}")
    return "\n".join(lines) + "\n"


def keys_in(text: str) -> list:
    doc = yaml.safe_load(text) or {}
    return [str(it.get("key", "")) for mod in doc.get("modules") or [] for it in mod.get("items") or []]


def new_key(taken: list, office: str, now: datetime.datetime) -> str:
    base = f"rep-{office}-{now:%y%m%d-%H%M%S}"
    key, n = base, 1
    while key in taken:
        n += 1
        key = f"{base}-{n}"
    return key


def add(office: str, title: str, body: str, priority: str, path: str, now=None) -> tuple:
    """Append one report to `path` (made from HEADER when missing); answers (key, path)."""
    office = office_name(office)
    title, body = unwrapped(printable(title)), unwrapped(printable(body))
    if not body.strip():
        title, body = title_of(title), title          # the person's words, whole: the title is made of them
    title = " ".join(title.split())
    if not title:
        raise ValueError("a report needs a title: one line, in the person's own words")
    if len(title) > TITLE_MAX:
        raise ValueError(f"the title is {len(title)} characters; at most {TITLE_MAX} (the rest goes in --body)")
    if priority not in PRIORITIES:
        raise ValueError(f"priority is one of {', '.join(PRIORITIES)}")
    now = now or datetime.datetime.now(datetime.timezone.utc)
    when = now.strftime("%Y-%m-%d %H:%M UTC")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existed = os.path.exists(path)
    try:
        with open(path, "a+", encoding="utf-8") as f:
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            old = f.read()
            head = "" if old else HEADER.format(office=office, label=LABEL)
            sep = "\n" if old and not old.endswith("\n") else ""
            try:
                key = new_key(keys_in(old or head), office, now)
                new = head + sep + item_text(key, title, body, priority, office, when)
                landed = keys_in(old + new).count(key)
            except (yaml.YAMLError, AttributeError, TypeError) as e:
                raise ValueError(f"{os.path.basename(path)} does not read as a plan ({type(e).__name__}); "
                                 f"left as it was") from None
            if landed != 1:
                raise ValueError(f"{os.path.basename(path)}: the new item would not land in a module; left as it was")
            append(f.fileno(), new.encode("utf-8"), path)
    except (ValueError, OSError):
        if not existed and os.path.exists(path) and os.path.getsize(path) == 0:
            os.remove(path)
        raise
    # The item is in the file from here on: what follows may only warn, or the hook would call the
    # report refused, and the retry would declare it twice.
    if not existed:
        own_like_its_folder(path)
    return key, path


def append(fd: int, data: bytes, path: str) -> None:
    """Append `data` whole or not at all: a half-written item (a full disk) would make every later read
    of the file fail, so on an error the file is cut back to its size before. The file is opened for
    appending, so each write lands at its end."""
    size = os.fstat(fd).st_size
    view = memoryview(data)
    try:
        while view:
            view = view[os.write(fd, view):]
    except OSError as e:
        os.ftruncate(fd, size)
        raise OSError(f"{os.path.basename(path)}: the report could not be written ({e.strerror}); "
                      f"the file is as it was") from None
    try:
        os.fsync(fd)
    except OSError as e:          # some mounts refuse it; the bytes are written all the same
        print(f"[project-pln] report: fsync of {os.path.basename(path)}: {e.strerror}", file=sys.stderr)


def own_like_its_folder(path: str) -> None:
    """A file made by root (the agent runs bbox in its container) is handed to whoever owns plans/, with
    the mode of the plans beside it: a root-only file would refuse the office user's next report. A
    mount that refuses it (virtiofs, /mnt/c without metadata) is said, never a failure."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    try:
        folder = os.stat(os.path.dirname(path))
        sibling = os.path.join(os.path.dirname(path), "office.yaml")
        os.chown(path, folder.st_uid, folder.st_gid)
        os.chmod(path, (os.stat(sibling).st_mode & 0o777) if os.path.exists(sibling) else 0o644)
    except OSError as e:
        print(f"[project-pln] report: {os.path.basename(path)} stays as root made it ({e.strerror}): "
              f"the office user may not be able to add the next report", file=sys.stderr)


def said_in_session(sid: str = "", home: str = "", port: str = "") -> str:
    """The person's last message in the agent session this runs in — `--said`. A small model fills no
    text it might mangle: in five tries at quoting the owner's words into a command (2026-10-21),
    gemma4:e2b recited the steps, escaped a quote the shell's wrong way, kept a placeholder's bracket,
    left a quote unescaped, and wrote the call as text. The harness tells every tool process its session
    (DSH_SESSION_ID); its page is read through the harness's own API, with the office's own token, and
    the message is the one the person wrote — what the relay adds is never stored in the session."""
    import urllib.request
    import uuid
    sid = sid or os.environ.get("DSH_SESSION_ID", "")
    if not sid:
        raise ValueError("--said works inside an agent's session (no DSH_SESSION_ID here): give the words instead")
    home = home or os.environ.get("DSH_HOME", "/data/dsh")
    with open(os.path.join(home, "api-token"), encoding="utf-8") as f:
        token = f.read().strip()
    url = f"http://127.0.0.1:{port or os.environ.get('DSH_PORT', '3080')}/api/session/page"

    def page(through: int) -> dict:
        body = json.dumps({"type": "client-request", "rpcId": str(uuid.uuid4()), "method": "session/page",
                           "payload": {"args": {"request": {"address": {"kind": "session", "sessionId": sid},
                                                            "throughSeq": through}}}}).encode()
        req = urllib.request.Request(url, body, {"authorization": f"Bearer {token}",
                                                 "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return (json.loads(r.read().decode("utf-8")) or {}).get("result") or {}

    got = page(10 ** 9)
    past = re.search(r"past cursor (\d+)", json.dumps(got.get("error") or {}))
    if not got.get("ok", True) and past:
        got = page(int(past.group(1)))
    if not got.get("ok", True):
        # An answer that is NOT this session's page ("a subagent session needs its durable parent",
        # an unknown session, a refused token) is not an empty session — read as one, it would say
        # "the person said nothing" about a page that was never served. Say the real reason instead.
        err = got.get("error") or {}
        why = err.get("message") or err.get("code") or "no answer"
        raise ValueError("--said works inside an agent's session (the harness did not serve this "
                         f"session's page: {why}): give the words instead")
    said = []
    for rec in (got.get("value") or {}).get("records") or []:
        e = rec.get("event") or {}
        d = e.get("data") or {}
        if e.get("type") != "user/message" or (d.get("source") or {}).get("kind") != "user":
            continue
        text = "\n".join(p.get("text", "") for p in d.get("content") or [] if isinstance(p, dict)).strip()
        if text and not text.startswith("Current runtime context"):
            said.append(text)
    if not said:
        raise ValueError(f"no message of the person's in session {sid}: give the words instead")
    return the_report(said)


def the_report(said: list) -> str:
    """Of the person's messages, oldest first: the newest that asks for a report (two sent while the agent
    was busy — «תדווח באג: הקונסול לא נטען», then «ותבדוק את המייל» — report the first), and with it the
    one before when it is only the order («Wtf ??? Report bug» is about what came before)."""
    i = max((n for n, text in enumerate(said) if REPORTISH.search(text)), default=len(said) - 1)
    content = [w for w in re.findall(r"[a-zA-Zא-ת]{2,}", said[i]) if w.lower() not in ORDER_WORDS]
    if len(content) <= 1 and i > 0:
        return said[i - 1] + "\n\n" + said[i]
    return said[i]


KEPT = "\x00"                                   # marks a word that argparse would take for an option
OPTIONS = {"--office", "--said", "--body", "--priority", "--plan", "-h", "--help"}
VALUED = {"--office", "--body", "--priority", "--plan"}


def words_kept(argv: list) -> list:
    out, value = [], False
    for a in argv:
        flag = a.split("=", 1)[0]
        if value or flag in OPTIONS or a == "-" or not a.startswith("-"):
            out.append(a)
            value = not value and flag in VALUED and "=" not in a
        else:
            out.append(KEPT + a)
    return out


def main(argv=None, stdin=None) -> int:
    ap = argparse.ArgumentParser(prog="report.py")
    sub = ap.add_subparsers(dest="verb", required=True)
    a = sub.add_parser("add")
    a.add_argument("--office", required=True)
    # `-` reads the words from stdin — the recipe's heredoc, where no quote in them needs escaping. More
    # than one word is joined: a quote the model left unescaped splits its text into several arguments
    # (gemma4:e2b, 2026-10-21: «… במודול 'דיווחים · hp', וגם …» came as three).
    a.add_argument("title", nargs="*")
    a.add_argument("--said", action="store_true", help="the person's last message in this agent session")
    a.add_argument("--body", default="")
    a.add_argument("--priority", default="high")
    a.add_argument("--plan", default="")
    # A word of a split text that starts with «-» («-בטלפון») is no option: it stays a word, in its place.
    args = ap.parse_args(words_kept(sys.argv[1:] if argv is None else argv))
    title = " ".join(w[1:] if w.startswith(KEPT) else w for w in args.title)
    if title == "-":
        title = (stdin or sys.stdin).read()
    try:
        if args.said:
            title = said_in_session()
        key, path = add(args.office, title, body_of(args.body), args.priority,
                        args.plan or plan_path(args.office))
    except (OSError, ValueError) as e:
        print(f"[project-pln] report: {e}", file=sys.stderr)
        return 2
    print(f"KEY={key}")
    print(f"FILE={path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
