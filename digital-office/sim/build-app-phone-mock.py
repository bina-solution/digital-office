#!/usr/bin/env python3
"""build-app-phone-mock — a display change to an APP, demonstrated on the owner's own phone screenshot.

AGENTS.md rule 11: a display change comes back as an interactive simulation and its screenshots, and
when he showed the problem with a screenshot the demo starts from THAT screen. The full-screen mock
(build-fullscreen-mock.py) is for a change to the console's chrome; this one is for a change INSIDE an
app, so it keeps his pixels for everything around the app (the phone's status bar, the browser's bar,
the console's bar above and its tab bar below) and puts the REAL app page in the app's place — the
page as it is in the working tree, running on a fixture of the data his screen showed. Nothing in the
app area is drawn by hand: what he drives is the code that will ship.

    python3 digital-office/sim/build-app-phone-mock.py \\
        --shot ci-artifacts/exampleu-start/owner-mail-phone-2026-11-09-0001.jpg --rows 400,2036 \\
        --app apps/mail/mailview/static --fixture ci-artifacts/mail-phone/fixture.js \\
        --before-ref HEAD --title "מייל" --out ci-artifacts/mail-phone

Writes into --out (gitignored):
  after.html   the app page from the working tree, self-contained (its scripts inlined), fixture first
  before.html  the same page at --before-ref (git show), on the same fixture — today's screen
  phone.html   his screenshot as the frame; «לפני» is his own picture, «אחרי» the page in the app's
               place, with the rows that fit counted from the page's own layout. The console's side of
               the one-search contract (bina:search-offer → bina:search-taken, «חיפוש» → bina:find) is
               played by the frame, over the console bar's search in his pixels.

The fixture is a script that replaces `window.fetch` before the app's scripts run (the shape of
digital-office/sim/mocks/<app>.js). No image library is needed: the bands are his JPEG drawn by CSS.
"""
from __future__ import annotations

import argparse
import base64
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRIPT_SRC = re.compile(r'<script src="(?P<src>[^"]+)"></script>')

# A page inside a srcdoc frame has no URL of its own: a pushState to /message/<id> there is refused,
# and the app's own navigation must not take the demo down with it.
HISTORY_GUARD = """<script>/* mock: history inside a srcdoc frame */
["pushState","replaceState"].forEach(function(k){var f=history[k].bind(history);
  history[k]=function(s,t,u){try{return f(s,t,u);}catch(e){}};});
</script>"""


def self_contained(index_html: str, read_script, fixture_js: str, theme: str) -> str:
    """The app's index.html with every local <script src> inlined and the fixture placed right
    after the first script (the base anchor), before any of the app's own code runs."""
    def inline(m: re.Match) -> str:
        body = read_script(m.group("src")).replace("</script", "<\\/script")
        return f"<script data-inlined-from=\"{m.group('src')}\">\n{body}\n</script>"
    html = SCRIPT_SRC.sub(inline, index_html)
    first = html.find("</script>")
    if first < 0:
        sys.exit("the page has no script to anchor the fixture after")
    fixture = "<script data-mock-fixture>\n" + fixture_js.replace("</script", "<\\/script") + "\n</script>"
    html = html[: first + 9] + "\n" + HISTORY_GUARD + "\n" + fixture + html[first + 9:]
    if theme:
        html = html.replace('<html lang="he" dir="rtl">', f'<html lang="he" dir="rtl" data-theme="{theme}">', 1)
    return html


def at_ref(ref: str, rel: pathlib.Path):
    def read(name: str) -> str:
        path = (rel / name).as_posix()
        return subprocess.run(["git", "-C", str(REPO), "show", f"{ref}:{path}"], check=True,
                              capture_output=True, text=True).stdout
    return read


PHONE = """<!doctype html>
<html lang="he" dir="rtl" data-theme="midnight"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title} — לפני ואחרי, על המסך שלך</title>
<style data-inlined-from="platform-base/bina-ui/theme-tokens.css">
{tokens}
</style>
<style>
:root{{--radius-pill:999px;--font:"Segoe UI",system-ui,-apple-system,"Noto Sans Hebrew",Arial,sans-serif}}
html,body{{margin:0;height:100%;background:var(--bg);color:var(--ink);font:14px/1.45 var(--font)}}
.wrap{{display:flex;flex-direction:column;align-items:center;gap:10px;padding:10px 0 24px}}
.bar{{display:flex;gap:6px;align-items:center;flex-wrap:wrap;justify-content:center}}
.bar button{{font:inherit;font-weight:700;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:var(--radius-pill);padding:6px 16px;cursor:pointer}}
.bar button[aria-pressed="true"]{{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}}
.meas{{font-size:12.5px;color:var(--muted);text-align:center;max-width:390px}}
.meas b{{color:var(--ink)}}
.phone{{position:relative;width:390px;height:{ph}px;overflow:hidden;border-radius:22px;box-shadow:0 0 0 1px var(--line),var(--shadow-lg);background:var(--bg)}}
.shot{{position:absolute;inset:0;background:url("{img}") 0 0/390px auto no-repeat}}
.band{{position:absolute;inset-inline:0;background-image:url("{img}");background-size:390px auto;background-repeat:no-repeat}}
.top{{top:0;height:{top}px;background-position:0 0}}
.bot{{bottom:0;height:{bot}px;background-position:0 -{boty}px}}
iframe{{position:absolute;top:{top}px;inset-inline:0;width:390px;height:{app}px;border:0;background:var(--bg)}}
.find{{position:absolute;top:{ftop}px;left:{fleft}px;width:{fw}px;height:{fh}px;border:0;background:transparent;cursor:pointer;border-radius:10px}}
.find:focus-visible{{outline:2px solid var(--accent)}}
.phone[data-v="before"] iframe,.phone[data-v="before"] .band,.phone[data-v="before"] .find{{display:none}}
.phone[data-v="after"] .shot{{display:none}}
</style></head><body>
<div class="wrap">
  <div class="bar" role="group" aria-label="תצוגה">
    <button type="button" data-v="before">לפני — המסך שלך</button>
    <button type="button" data-v="after">אחרי — אותו מסך</button>
  </div>
  <div class="phone" id="phone" data-v="after">
    <div class="shot" role="img" aria-label="צילום המסך ששלחת"></div>
    <div class="band top"></div>
    <iframe id="app" title="{title} — אחרי" srcdoc="{srcdoc}"></iframe>
    <button class="find" id="find" type="button" title="החיפוש של הלשכה — מחפש עכשיו ב{title}" aria-label="חיפוש"></button>
    <div class="band bot"></div>
  </div>
  <div class="meas" id="meas"></div>
  <div class="meas">נסה: החלקה על שורה לצד (ארכיון, עם ביטול) · לחיצה ארוכה (בחירה) · לחיצה על העיגול (בחירה) ·
    «לא נמסרו» (פתיחה) · «חיפוש» בשורה של הלשכה למעלה · «הכל ▾» (טווח זמן)</div>
</div>
<script>
var phone = document.getElementById("phone"), frame = document.getElementById("app");
var BEFORE = {before_rows};
function show(v) {{
  phone.dataset.v = v;
  document.querySelectorAll(".bar button").forEach(function (b) {{ b.setAttribute("aria-pressed", String(b.dataset.v === v)); }});
  try {{ history.replaceState(null, "", "#" + v); }} catch (e) {{}}
  measure();
}}
document.querySelectorAll(".bar button").forEach(function (b) {{ b.onclick = function () {{ show(b.dataset.v); }}; }});
/* the console's half of the one-search contract, played by the frame */
function taken() {{
  try {{ frame.contentWindow.postMessage({{ type: "bina:search-taken" }}, location.origin === "null" ? "*" : location.origin); }} catch (e) {{}}
  try {{ frame.contentWindow.document.documentElement.classList.add("shell-search"); }} catch (e) {{}}
}}
window.addEventListener("message", function (ev) {{
  if (ev.source === frame.contentWindow && ev.data && ev.data.type === "bina:search-offer") taken();
}});
document.getElementById("find").onclick = function () {{
  try {{ frame.contentWindow.postMessage({{ type: "bina:find" }}, location.origin === "null" ? "*" : location.origin); }} catch (e) {{}}
  try {{ frame.contentWindow.openFind(); }} catch (e) {{}}
}};
/* rows that fit: counted off the page's own layout, every time it changes */
function measure() {{
  var m = document.getElementById("meas"), d;
  try {{ d = frame.contentWindow.document; }} catch (e) {{ return; }}
  if (!d || !d.body) return;
  var h = frame.clientHeight, full = 0, part = 0;
  d.querySelectorAll(".gm-row").forEach(function (r) {{
    var b = r.getBoundingClientRect(); if (b.height === 0) return;
    if (b.top >= 0 && b.bottom <= h + 0.5) full++; else if (b.top < h && b.bottom > 0) part++;
  }});
  m.innerHTML = "הודעות שנראות במסך: לפני <b>" + BEFORE + "</b> · אחרי <b>" + full + "</b>" + (part ? " (ועוד " + part + " חלקית)" : "")
    + " · אזור האפליקציה " + h + " פיקסלים";
}}
frame.addEventListener("load", function () {{
  taken();
  var d = frame.contentWindow.document;
  new MutationObserver(measure).observe(d.body, {{ childList: true, subtree: true }});
  setTimeout(measure, 300);
}});
show((location.hash || "#after").slice(1) === "before" ? "before" : "after");
</script>
</body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", required=True, help="his screenshot (device pixels)")
    ap.add_argument("--rows", required=True, help="y0,y1: the app area in the shot's device rows")
    ap.add_argument("--find", default="", help="x0,y0,x1,y1: the console bar's search in device px")
    ap.add_argument("--app", required=True, help="the app's static dir (index.html + its scripts)")
    ap.add_argument("--fixture", required=True, help="a script that answers the app's fetches")
    ap.add_argument("--before-ref", default="HEAD")
    ap.add_argument("--before-rows", default="?", help="messages his screen showed (counted off it)")
    ap.add_argument("--theme", default="midnight", help="data-theme for the page (his phone: dark)")
    ap.add_argument("--width", type=int, default=1080, help="the shot's width in device px")
    ap.add_argument("--height", type=int, default=2340)
    ap.add_argument("--title", default="האפליקציה")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    app = (REPO / a.app).resolve() if not pathlib.Path(a.app).is_absolute() else pathlib.Path(a.app)
    rel = app.relative_to(REPO)
    fixture = pathlib.Path(a.fixture).read_text(encoding="utf-8")
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)

    after = self_contained((app / "index.html").read_text(encoding="utf-8"),
                           lambda n: (app / n).read_text(encoding="utf-8"), fixture, a.theme)
    before = self_contained(at_ref(a.before_ref, rel)("index.html"), at_ref(a.before_ref, rel), fixture, a.theme)
    (out / "after.html").write_text(after, encoding="utf-8")
    (out / "before.html").write_text(before, encoding="utf-8")

    k = 390 / a.width                                        # device px → CSS px
    y0, y1 = (int(v) for v in a.rows.split(","))
    fx = [int(v) for v in a.find.split(",")] if a.find else [333, 272, 548, 364]
    shot = pathlib.Path(a.shot)
    img = "data:image/jpeg;base64," + base64.b64encode(shot.read_bytes()).decode("ascii")
    srcdoc = after.replace("&", "&amp;").replace('"', "&quot;")
    tokens = (REPO / "platform-base/bina-ui/theme-tokens.css").read_text(encoding="utf-8")
    phone = PHONE.format(
        tokens=tokens, title=a.title, img=img, srcdoc=srcdoc, before_rows=repr(a.before_rows),
        ph=round(a.height * k, 1), top=round(y0 * k, 1), app=round((y1 - y0) * k, 1),
        bot=round((a.height - y1) * k, 1), boty=round(y1 * k, 1),
        ftop=round(fx[1] * k, 1), fleft=round(fx[0] * k, 1), fw=round((fx[2] - fx[0]) * k, 1), fh=round((fx[3] - fx[1]) * k, 1))
    (out / "phone.html").write_text(phone, encoding="utf-8")
    for n in ("after.html", "before.html", "phone.html"):
        print(f"{out / n}  ({(out / n).stat().st_size // 1024} KB)")
    print(f"app area: device rows {y0}…{y1} = {round((y1 - y0) * k, 1)} CSS px of {round(a.height * k, 1)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
