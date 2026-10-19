#!/usr/bin/env python3
"""screen-words-lint — gate G77: a screen says it in words, in the page.

    python3 scripts/refactor/screen-words-lint.py            # exit 1 on a finding
    python3 scripts/refactor/screen-words-lint.py --self-test

Four things a screen of this office did, each found by looking at it (three on 2026-10-07, the
fourth on 2026-10-10), each of them another voice where the office's own was owed:

1. A STATUS CODE AS THE REASON. Eight request helpers ended in `body.error || "HTTP " + r.status`,
   so the one moment a service cannot send a sentence — when it is down — was the moment the owner
   read "HTTP 502", in red; five more said an answer "is not JSON". 25 places in 11 files. A screen
   names a failed request with the shared block `binaSaid(status)` (platform-base/bina-ui/bina-said.js).
   The same number with a Hebrew word in front of it is the same thing: the drive and the mail said
   «שגיאה (502)» as the whole reason (seen 2026-10-10, each tile brought up over a silent service) —
   and so is the number behind two words: the drive's upload said «שגיאה בהעלאה (502)». A SENTENCE
   that carries the status as its detail — «שירות החיבורים החזיר שגיאה (502)» — is not this.
   And an EXCEPTION'S NAME in a sentence is G76's rule on a screen: «השירות אינו מגיב (TypeError)».

2. THE BROWSER'S OWN DIALOGS. `confirm(` / `alert(` / `prompt(` put "console.localhost says…" with
   English buttons, left to right, over a Hebrew screen — 28 places in eight screens — and a
   `confirm` has one line of text, so it cannot show what is about to be removed. A screen asks and
   reports with `binaAsk` / `binaTell` (platform-base/bina-ui/bina-ask.js).

3. AN EMOJI WHERE AN ICON BELONGS. The install preview marked "also installs" with a package emoji
   and a refusal with a no-entry sign; an empty library showed a television. An emoji is another
   vendor's drawing in another vendor's colours, different on every machine. Icons are line glyphs
   from the office's own sets. (Typographic marks — arrows, a check mark, a star — are not emoji and
   are not this gate's business.)

4. NO ANSWER, UNDER A NAME OF A SCREEN'S OWN. A request that could not be sent at all has ONE name
   in this office — `binaSaid(0)`, «אין תשובה מהשירות» — and three screens kept another, each its
   own: the drive «שגיאת רשת — נסה שוב», my-docs «שגיאת רשת — נסו שוב», the mail «שגיאת רשת — לא
   התקבלה תשובה מהשרת». One event, read four ways on four screens of one office (seen 2026-10-10,
   each tile brought up over a silent service). What a screen ADDS to the name — what was being
   done, what is safe to do next — is its own to say, after it.

SCOPE. A screen's own files: tracked `.js` / `.html` under a `static/` directory of an app or a
plane, and `ui.html`; vendored files and the shared blocks' sources are not read (the blocks are
kept by G27). Comments are not read — the comment that documents a fix quotes what it removed. A
method called `confirm` on an object, and a function a screen defines under that name, are not the
browser's. A scan that finds no screen at all fails: green and blind look the same from outside.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]

#: a status code handed to a person: "HTTP " + r.status · 'HTTP ' + … · `HTTP ${r.status}` · "שגיאה (" + r.status
#: · "שגיאה בהעלאה (" + xhr.status — a word or two between «שגיאה» and the number change nothing
RAW_STATUS = re.compile(r"""["'`]HTTP\s*["']\s*\+|HTTP\s*\$\{|שאינה JSON|["'`]שגיאה[^"'`\n(]{0,24}\((?:["']\s*\+|\$\{)""")
#: an exception's type put into a sentence: '… (' + e.name + ')' · `… (${err.name})`
RAW_NAME = re.compile(r"""\(\s*(?:["']\s*\+\s*|\$\{)(?:e|err|error|ex)\.name\b""")
#: a request that could not be sent, named by the screen itself: a string that begins «שגיאת רשת»
NO_ANSWER = re.compile(r"""["'`]שגיאת רשת""")
#: the browser's own dialog, called bare or off `window` — not a method, not a declaration
NATIVE_DIALOG = re.compile(r"(?<![.\w$])(?:window\.)?(confirm|alert|prompt)\s*\(")
#: characters every system draws as a colour picture: the emoji planes, the BMP characters whose
#: default presentation is emoji, and the selector that forces it on the rest
EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF⌚⌛⏩-⏬⏰⏳◽◾☔☕♈-♓♿⚓"
    "⚡⚪⚫⚽⚾⛄⛅⛎⛔⛪⛲⛳⛵⛺⛽✅✊✋"
    "✨❌❎❓-❕❗➕-➗➰➿⬛⬜⭐⭕️]")
_COMMENT = re.compile(r"/\*.*?\*/|<!--.*?-->|(?<![:\"'`\\])//[^\n]*", re.S)

SAYS = {
    "status": "names a failed request by its status code — `binaSaid(status)` (bina-ui/bina-said.js) says it in words",
    "name": "puts an exception's type into a sentence a person reads — say what failed; the type is the log's",
    "silent": "names a request that could not be sent in words of its own — `binaSaid(0)` (bina-ui/bina-said.js) is the office's name for it",
    "dialog": "asks through the browser's own dialog — `binaAsk` / `binaTell` (bina-ui/bina-ask.js) ask and report in the page",
    "emoji": "draws an emoji where an icon belongs — use a line glyph from the office's sets",
}


def findings(source: str) -> list[tuple[int, str, str]]:
    """(line, kind, what) for everything a screen's code may not hold; comments are not read."""
    code = _COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), source)      # keep the line numbers
    line = lambda pos: code.count("\n", 0, pos) + 1
    out = [(line(m.start()), "status", m.group(0).strip()) for m in RAW_STATUS.finditer(code)]
    out += [(line(m.start()), "name", m.group(0).strip()) for m in RAW_NAME.finditer(code)]
    out += [(line(m.start()), "silent", m.group(0).strip() + "…") for m in NO_ANSWER.finditer(code)]
    own = set(re.findall(r"function\s+(confirm|alert|prompt)\s*\(", code))       # the screen's own function
    out += [(line(m.start()), "dialog", m.group(1) + "()") for m in NATIVE_DIALOG.finditer(code)
            if m.group(1) not in own]
    out += [(line(m.start()), "emoji", "U+%04X" % ord(m.group(0))) for m in EMOJI.finditer(code)]
    return sorted(out)


def screens(repo: pathlib.Path) -> list[pathlib.Path]:
    names = subprocess.run(["git", "-C", str(repo), "ls-files", "--", "apps", "platform-base"],
                           capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
    return [repo / n for n in names
            if (("/static/" in n and n.endswith((".js", ".html"))) or n.endswith("/ui.html"))
            and "/vendor/" not in n and "/bina-ui/" not in n]


def check(repo: pathlib.Path) -> int:
    files = screens(repo)
    if not files:
        print("screen-words-lint — G77 FAIL: no screen file was found under apps/ or platform-base/ — "
              "the scan is blind, not green")
        return 1
    bad = 0
    for f in files:
        for line, kind, what in findings(f.read_text(encoding="utf-8", errors="replace")):
            bad += 1
            print(f"  FAIL  {f.relative_to(repo).as_posix()}:{line}  {what}  {SAYS[kind]}")
    print(f"screen-words-lint — G77: {len(files)} screen files · "
          + (f"{bad} place(s) where the wire or the browser speaks instead of the screen" if bad
             else "no bare status code, no name of its own for «no answer», no browser dialog, no emoji"))
    return 1 if bad else 0


def self_test() -> int:
    """Every shape of the four is caught; a comment, a method, the screen's own function, the shared
    blocks and a typographic mark are not."""
    cases = {
        "status, concatenated": ('throw new Error(body.error || ("HTTP " + r.status));\n', 1),
        "status, single quotes": ("out.textContent = r.body.error || ('HTTP ' + r.status);\n", 1),
        "status, template": ("sub = `הלשכה לא ענתה (HTTP ${r.status})`;\n", 1),
        "not json": ("try { b = await r.json(); } catch (e) { b = { error: 'תשובה שאינה JSON' }; }\n", 1),
        "status, in Hebrew": ('tellBad((d && d.error) || "שגיאה (" + r.status + ")");\n', 1),
        "status, in Hebrew, template": ("return `שגיאה (${status})`;\n", 1),
        "status, in Hebrew, named": ('tellBad(result.error || "שגיאה בהעלאה (" + xhr.status + ")");\n', 1),
        "an exception's name": ("return { ok: false, error: 'השירות אינו מגיב (' + e.name + ')' };\n", 1),
        "no answer, a name of its own": ('catch (e) { tellBad("שגיאת רשת — נסה שוב"); throw e; }\n', 1),
        "no answer, the office's name": ("catch (e) { tellBad('ההעלאה נכשלה — ' + binaSaid(0)); throw e; }\n", 0),
        "a sentence with its status": ("err = d.message || `שירות החיבורים החזיר שגיאה (${r.status})`;\n", 0),
        "a person's name": ("h.textContent = 'שלום (' + user.name + ')'; t = `קוד ${status}`;\n", 0),
        "confirm": ("if (!confirm('למחוק?')) return;\n", 1),
        "alert off window": ('window.alert("נכשל");\n', 1),
        "prompt": ('const v = prompt("ערך:"); if (!v) return;\n', 1),
        "dialog in markup": ('<button onclick="alert(1)">x</button>\n', 1),
        "emoji": ('li.innerHTML = `<span class="g">\U0001F4E6</span>`;\n', 1),
        "emoji, basic plane": ('<div class="prov bad"><div>⛔</div></div>\n', 1),
        "emoji, forced": ("const mark = '✈️';\n", 1),
        "comments": ('// it said "HTTP " + r.status and confirm() \U0001F4E6\n/* `HTTP ${r.status}` alert(1) */\n'
                     "<!-- prompt('x') ⛔ -->\nx = binaSaid(r.status);\n", 0),
        "a url": ('const u = "http://host/x"; // HTTP ${r.status}\nfetch(u);\n', 0),
        "a method": ("await sheet.confirm({ title }); this.alert('x'); $prompt('y');\n", 0),
        "the screen's own function": ("async function confirm(side) { return post(side); }\nb.onclick = () => confirm(side);\n", 0),
        "a key": ("post(p, { confirm: true, alert: 'x' });\n", 0),
        "the shared blocks": ("if (!await binaAsk({ title: 'למחוק?' })) return; binaTell(binaSaid(r.status), 'bad');\n", 0),
        "typographic marks": ("a.textContent = 'פתח ↗'; b.textContent = '✓ → ★ 7.8';\n", 0),
    }
    got = {name: len(findings(src)) for name, (src, _n) in cases.items()}
    ok = all(got[name] == want for name, (_src, want) in cases.items())
    # …and the gate as a whole: one finding is not green, a vendored file is not read, no screen is a failure
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        subprocess.run(["git", "init", "-q", str(tmp)], check=True)
        ok = ok and check(tmp) == 1                                           # nothing to scan
        static = tmp / "apps" / "x" / "static"
        (static / "vendor").mkdir(parents=True)
        (static / "app.js").write_text(cases["the shared blocks"][0], encoding="utf-8")
        (static / "vendor" / "lib.js").write_text(cases["confirm"][0], encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp), "add", "-A"], check=True)
        ok = ok and check(tmp) == 0
        (static / "app.js").write_text(cases["confirm"][0], encoding="utf-8")
        ok = ok and check(tmp) == 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nscreen-words-lint self-test: "
          + ("16 shapes caught (7 of a status, an exception's name, a name of its own for «no answer», 4 of a "
             "dialog, 3 of an emoji); comments, a URL, the office's own name for no answer, a sentence that "
             "carries its status, a person's name, a method, the screen's own function, a key, the shared blocks "
             "and typographic marks are not; an empty scan fails"
             if ok else "FAILED — got " + str(got)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else check(REPO))
