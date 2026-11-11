#!/usr/bin/env python3
"""build-security-v2-mock — the owner's own screenshot of «אבטחה», with the proposed overview in place (DGO-1646).

WHY THIS SHAPE (AGENTS.md, owner rule 11). A display change comes back as an interactive simulation that
starts from THE screen he sent: his pixels around the app, and the change drawn over the app's own area
with the app's REAL stylesheet (the <style> of platform-base/security/static/index.html, tokens included).
Nothing here names a colour; every colour is a token of that stylesheet.

WHAT IS MEASURED, NOT DRAWN
  * The app's area in his screenshot (2000×1251 px): x 283→1414, y 349→1038. Measured off the pixels with
    a headless browser: 1414/1415 is where the content's ground (242,244,245) meets the side panel's
    (248,250,251); 349 is the bottom of the window's title bar; 1038 is the top of the console's dock.
  * The scale, 1.3889 image px per CSS px: the shot is a 1440×900 display saved at 2000×1251. The left
    gap to the first card, 35 px, is 25 CSS px, which is the page padding (.pg).
  * Every number is Exampleu's security database read at the moment the screen said 22,298
    (2026-11-09 15:24:39 UTC). The split, the kinds and the sign-ins are the read-only queries of DGO-1645
    and DGO-1646. The provider's commands, the knocks on closed ports and the certificate timing were
    measured on the server the same evening.

    python3 digital-office/sim/build-security-v2-mock.py [--shot PATH] [--out DIR]

Output (git-ignored): ci-artifacts/security-v2-mock/index.html, a single file. #before, #after, #phone,
#phone-dark and #after-dark open it in that state.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
APP = REPO / "platform-base" / "security" / "static" / "index.html"
SHOT = REPO / "ci-artifacts" / "security-noise" / "owner-screenshot-2026-11-09-1825.webp"
OUT = REPO / "ci-artifacts" / "security-v2-mock"

#: the app's area in the screenshot, in image px, and the screenshot's px per CSS px (measured: module doc)
BOX = {"x": 283, "y": 349, "w": 1131, "h": 689}
IMG = {"w": 2000, "h": 1251}
SCALE = 2000 / 1440

# ── the measurements (Exampleu, 2026-11-09 15:24:39 UTC, the moment of the owner's screenshot) ───────────
D = {
    "total": "22,298", "addrs": "791", "countries": "62",
    "you": "9,085", "office": "640", "net": "12,573", "net_addrs": "785",
    "n8n": ("5,857", "74"), "secrets": ("3,381", "45"), "signin": ("2,352", "582"),
    "meet": ("675", "53"), "bare": ("308", "129"), "ssh": ("27", "14"),
    "machines_ssh": "4,049", "people_ok": "5", "people_typo": "1",
    "would_bans": "16", "provider_cmds": "67", "knocks": "3,127",
}

MOCK_CSS = """
.v-verdict{display:grid;grid-template-columns:auto 1fr;gap:14px;align-items:start;margin-bottom:14px}
.v-mark{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;background:var(--accent-soft);color:var(--accent-d)}
.v-mark svg{width:24px;height:24px}
.v-say{margin:0;font-size:19px;line-height:27px;font-weight:800;color:var(--ink)}
.v-proof{margin:4px 0 0;color:var(--muted);font-size:13px;line-height:20px}
.v-proof b{color:var(--ink)}
.v-learn{margin-top:10px;display:flex;gap:8px;align-items:flex-start;color:var(--muted);font-size:12.5px;line-height:19px}
.v-who{--pg-kpi-cols:3;margin-bottom:14px}
.v-who .pg-kpi-v small{font-size:12.5px}
.v-sub{display:block;margin-top:6px;color:var(--muted);font-size:12px;line-height:17px}
.v-sub b{color:var(--ink);font-weight:700}
.pg-card{margin-bottom:14px}
.v-rows{list-style:none;margin:0;padding:0}
.v-rows li{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center;padding:9px 2px;border-top:1px solid var(--line);cursor:pointer}
.v-rows li:first-child{border-top:0}
.v-rows li:hover .v-what{color:var(--accent-d)}
.v-what{font-weight:700;color:var(--ink);font-size:13px;line-height:19px}
.v-what small{display:block;font-weight:400;color:var(--muted);font-size:12px;line-height:17px}
.v-n{font-variant-numeric:tabular-nums;font-weight:800;color:var(--ink);font-size:14px;text-align:end;unicode-bidi:plaintext}
.v-n small{display:block;font-weight:400;color:var(--muted);font-size:11px}
.v-how{margin:12px 0 0;padding:10px 12px;border-radius:10px;background:var(--surface-2);color:var(--muted);font-size:12.5px;line-height:19px}
.v-how b{color:var(--ink)}
.v-split{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.v-split>div{padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:var(--surface-2)}
.v-split .v-n{text-align:start;font-size:20px;line-height:26px}
.v-ltr{direction:ltr;unicode-bidi:isolate}
.v-act{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.v-drawer{position:fixed;inset:auto 0 0 0;max-height:70%;overflow:auto;background:var(--surface);border-top:1px solid var(--line);
  box-shadow:var(--shadow);padding:16px 18px 22px;z-index:9}
.v-drawer h3{margin:0 0 8px;font-size:15px}
.v-drawer dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 14px;margin:0}
.v-drawer dt{color:var(--muted);font-weight:700}
.v-drawer dd{margin:0;color:var(--ink)}
.v-x{float:left;border:0;background:transparent;color:var(--muted);font-size:20px;cursor:pointer}
.v-details summary{cursor:pointer;color:var(--muted);font-weight:700;padding:6px 2px}
@media (max-width:700px){.v-who{--pg-kpi-cols:1}.v-split{grid-template-columns:1fr}.v-rows li{grid-template-columns:1fr auto}
  .v-rows li .pill{grid-column:1/-1;justify-self:start}.v-say{font-size:17px;line-height:24px}}
"""

ROWS = [
    # (what, small, count, addrs, pill-kind, pill, who, why, got, did, you)
    ("טענו את דף הכניסה של n8n", "סורקים שמציירים את הדף — כ-190 קבצים בכל ביקור", D["n8n"], "ok", "נסגר היום 14:06",
     "סורקים בענן (AWS, M247) ובחיבורים ביתיים שכורים בעולם", "n8n היה פתוח לאינטרנט עם הכניסה שלו בלבד, 14 שעות",
     "את דף הכניסה של n8n ואת מספר הגרסה. שום תהליך, שום חשבון", "הוכנס מאחורי הכניסה של הלשכה (DGO-1594)", "לא"),
    ("חיפשו קבצי סודות", "‎/.env, /.git/config, xmlrpc.php‎ ועוד", D["secrets"], "ok", "קיבלו רק את דף הכניסה",
     "ציידי סודות, רובם מ-Tencent Cloud", "מחפשים שרתים ששכחו קובץ הגדרות פתוח",
     "את דף הכניסה, או את דף הבית של הפגישות. אף קובץ", "16 כתובות היו נחסמות; במצב צפייה נרשמו בלבד", "ההחלטה על אכיפה היא שלך"),
    ("ביקרו באפליקציות ונשלחו לכניסה", "Plane, הקונסול, הדרייב ועוד — כל כתובת שהתפרסמה", D["signin"], "ok", "נעצרו בכניסה",
     "סורקי אינטרנט ויומני תעודות", "כל כתובת חדשה נבדקת בדקות", "הפניה לדף הכניסה. 0 תשובות מאפליקציה פרטית", "כלום — זה התפקיד של הכניסה", "לא"),
    ("פתחו את דף הפגישות", "ציבורי בכוונה: כך אורחים מצטרפים", D["meet"], "info", "ציבורי",
     "סורקים", "הדף ציבורי", "את דף הפגישות. פגישה נפתחת רק עם כניסה", "כלום", "לא"),
    ("פנו לכתובת בלי אפליקציה", "סריקה של הכתובת עצמה, בלי שם", D["bare"], "muted", "‏404",
     "סורקי כתובות", "סורקים את כל האינטרנט", "‏404", "כלום", "לא"),
    ("ניסו להיכנס ב-SSH", "השרת מקבל רק מפתחות", D["ssh"], "ok", "נדחו",
     "רובוטים שמנחשים סיסמאות", "פורט 22 פתוח בכל שרת", "כלום — אין כניסה בסיסמה", "נדחו", "לא"),
]

DOORS = [
    ("אתר ואפליקציות", "443", "ok", "מאחורי הכניסה", "כל אפליקציה פרטית עונה רק למי שנכנס"),
    ("SSH", "22", "ok", "3 מפתחות, כולם עם שם", "המחשב שלך, Computers של הלשכה, המשרד שלך"),
    ("פגישות: וידאו ו-TURN", "UDP 10000 · 443", "ok", "רק אל גשר הווידאו", "ה-TURN מסרב לכל כתובת אחרת"),
    ("IPv6", "", "ok", "אותה חומה", "רק 22, 80, 443 ו-UDP 10000 פתוחים, כמו ב-IPv4"),
    ("פורטים סגורים", "", "ok", f"{D['knocks']} דפיקות נחסמו", "מאז ההפעלה האחרונה, 02:45"),
    ("Docker בתוך הלשכה", "", "ok", "תוקן היום", "אפליקציה כבר לא קוראת סודות או קבצים של אחרת (DGO-1647)"),
    ("הסוכן של ספק השרת", "Hostinger", "warn", f"{D['provider_cmds']} פקודות כ-root מאתמול",
     "טלמטריה כל שעה: כותב סקריפט, מריץ כ-root ומוחק. לא עובר ברשת, ולכן לא נראה ביומן"),
    ("המסוף של הספק", "VNC · serial", "info", "סיסמת root בלבד", "אין כניסה אוטומטית; 0 כניסות מאז ההתקנה"),
    ("עדכונים", "", "ok", "עדכוני אבטחה אוטומטיים", "Debian, כל יום"),
]

MARK = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 3v5c0 4.6-3 8.4-7 10-4-1.6-7-5.4-7-10V6z"/>'
        '<path d="M9 12l2 2 4-4"/></svg>')


def overview(theme: str) -> str:
    e = html.escape
    rows = "".join(
        f'<li data-i="{i}"><span class="v-what">{e(w)}<small>{e(s)}</small></span>'
        f'<span class="v-n">{c[0]}<small>{c[1]} כתובות</small></span><span class="pill {k}">{e(p)}</span></li>'
        for i, (w, s, c, k, p, *_rest) in enumerate(ROWS))
    doors = "".join(
        f'<li class="v-door"><span class="v-what">{e(n)}{f" <span class=v-ltr>{e(port)}</span>" if port else ""}'
        f'<small>{e(why)}</small></span><span></span><span class="pill {k}">{e(st)}</span></li>'
        for n, port, k, st, why in DOORS)
    detail = [{"t": r[0], "who": r[5], "why": r[6], "got": r[7], "did": r[8], "you": r[9]} for r in ROWS]
    return f"""<!doctype html><html lang="he" dir="rtl" data-theme="{theme}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>אבטחה — הצעה</title>
<style>{APP_CSS}</style><style>{MOCK_CSS}</style></head><body>
<main class="pg">
  <header class="pg-head"><h1>אבטחה</h1><div class="pg-actions">
    <div class="seg" role="group" aria-label="טווח"><button type="button" aria-pressed="false">שעה</button><button type="button" aria-pressed="true">יום</button><button type="button" aria-pressed="false">שבוע</button><button type="button" aria-pressed="false">חודש</button></div>
    <span class="pg-live"><span class="beat"></span>עדכון עכשיו</span></div></header>

  <section class="pg-card"><div class="v-verdict"><span class="v-mark">{MARK}</span><div>
    <p class="v-say">אף אחד מבחוץ לא נכנס.</p>
    <p class="v-proof">באפליקציות הפרטיות: <b>0 תשובות</b> לכתובת מבחוץ, מתוך <b>{D['net']}</b> בקשות של האינטרנט ביממה האחרונה. כולן נעצרו בכניסה או קיבלו דף ציבורי.</p>
    <div class="v-learn"><span class="pill info">לשכה חדשה · יום 1</span><span>בשבועיים הראשונים האינטרנט מגלה כתובות חדשות ביומן הציבורי של התעודות וסורק אותן. זה צפוי, ונרגע.</span></div>
  </div></div></section>

  <section class="pg-kpis v-who" aria-label="מי">
    <div class="pg-kpi" data-state="done"><span class="pg-kpi-k">שלך</span><span class="pg-kpi-v">{D['you']}<small>בקשות</small></span>
      <span class="v-sub">מ-3 חיבורים שלך: הבית, הטלפון והמחשב הנייד. נכנסת <b>{D['people_ok']}</b> פעמים.</span></div>
    <div class="pg-kpi" data-state="running"><span class="pg-kpi-k">של הלשכה עצמה</span><span class="pg-kpi-v">{D['office']}<small>בקשות</small></span>
      <span class="v-sub">ועוד <b>{D['machines_ssh']}</b> בדיקות SSH של המחשבים שלנו. אלה לא כניסות של אנשים.</span></div>
    <div class="pg-kpi" data-state="todo"><span class="pg-kpi-k">מהאינטרנט</span><span class="pg-kpi-v">{D['net']}<small>בקשות</small></span>
      <span class="v-sub">{D['net_addrs']} כתובות מ-{D['countries']} מדינות. <b>0</b> קיבלו משהו פרטי.</span></div>
  </section>

  <section class="pg-card"><div class="pg-cardhead"><h2>מה האינטרנט ניסה</h2><span class="pg-hint">ביממה האחרונה · לחיצה על שורה מסבירה אותה</span></div>
    <ul class="v-rows">{rows}</ul>
    <p class="v-how"><b>איך מצאו לשכה חדשה בתוך דקות:</b> כל אפליקציה מקבלת תעודת אבטחה, וכל תעודה מתפרסמת ביומן ציבורי. סורק אחד (<span class="v-ltr">rtpdetector-*.forestengine.net</span>) הגיע לכל אחת מ-22 הכתובות כדקה וחצי אחרי שהתעודה שלה הונפקה. כך זה בכל שרת חדש בעולם.</p>
  </section>

  <section class="pg-card"><div class="pg-cardhead"><h2>כניסות</h2><span class="pg-hint">אנשים, מכונות וזרים בנפרד</span></div>
    <div class="v-split">
      <div><span class="pg-kpi-k">אנשים</span><span class="v-n">{D['people_ok']}</span><span class="v-sub">כולן שלך · טעות סיסמה אחת</span></div>
      <div><span class="pg-kpi-k">המחשבים שלנו</span><span class="v-n">{D['machines_ssh']}</span><span class="v-sub">בדיקות SSH במפתחות עם שם</span></div>
      <div><span class="pg-kpi-k">זרים</span><span class="v-n">{D['ssh'][0]}</span><span class="v-sub">ניסיונות SSH, כולם נדחו</span></div>
    </div></section>

  <section class="pg-card"><div class="pg-cardhead"><h2>הדלתות לשרת</h2><span class="pg-hint">כל דרך שבה אפשר לדבר עם המכונה</span></div>
    <ul class="v-rows">{doors}</ul></section>

  <section class="pg-card"><div class="pg-cardhead"><h2>צריך אותך</h2></div>
    <ul class="v-rows">
      <li><span class="v-what">מעבר לאכיפה<small>{D['would_bans']} כתובות היו נחסמות מאתמול, כולן ציידי סודות. היום נרשמות בלבד.</small></span><span></span>
        <span class="v-act"><button class="btn" type="button">לאכיפה</button></span></li>
      <li><span class="v-what">הסוכן של Hostinger מריץ פקודות כ-root<small>להשאיר כמו שהוא, או להגביל לגיבויים ולכיבוי בלבד</small></span><span></span>
        <span class="v-act"><button class="btn ghost" type="button">להגביל</button><button class="btn ghost" type="button">להשאיר</button></span></li>
    </ul></section>

  <details class="pg-card v-details"><summary>המספרים הגולמיים (מה שמוצג היום)</summary>
    <p class="pg-note">{D['total']} בקשות נכנסות · {D['addrs']} כתובות · {D['countries']} מדינות. המפה מראה רק מאיפה <b>נכנסו</b>: ישראל, אתה.</p></details>
</main>
<div class="v-drawer" id="drawer" hidden><button class="v-x" type="button" aria-label="סגירה" id="x">×</button><h3 id="dt"></h3><dl id="dl"></dl></div>
<script>
var D = {json.dumps(detail, ensure_ascii=False)};
var L = [["who","מי זה"],["why","למה הגיע"],["got","מה קיבל"],["did","מה עשינו"],["you","צריך אותך?"]];
document.querySelectorAll("li[data-i]").forEach(function (li) {{
  li.addEventListener("click", function () {{
    var d = D[+li.getAttribute("data-i")];
    document.getElementById("dt").textContent = d.t;
    document.getElementById("dl").innerHTML = L.map(function (p) {{ return "<dt>" + p[1] + "</dt><dd>" + d[p[0]].replace(/</g, "&lt;") + "</dd>"; }}).join("");
    document.getElementById("drawer").hidden = false;
  }});
}});
document.getElementById("x").addEventListener("click", function () {{ document.getElementById("drawer").hidden = true; }});
</script></body></html>"""


def page(shot_b64: str) -> str:
    e = html.escape
    light, dark = e(overview("light"), quote=True), e(overview("dark"), quote=True)
    inner_w, inner_h = BOX["w"] / SCALE, BOX["h"] / SCALE
    return f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>אבטחה — לפני ואחרי</title>
<style>{APP_CSS}
body{{margin:0;padding:16px}}
.bar{{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}}
.bar h1{{font-size:16px;margin:0 0 0 8px}}
.stagewrap{{width:100%;max-width:1400px;margin:auto;overflow:hidden;border-radius:12px;border:1px solid var(--line);direction:ltr}}
.stage{{position:relative;direction:ltr;width:{IMG['w']}px;height:{IMG['h']}px;transform-origin:0 0;
  background:url(data:image/webp;base64,{shot_b64}) 0 0/{IMG['w']}px {IMG['h']}px no-repeat}}
.box{{position:absolute;left:{BOX['x']}px;top:{BOX['y']}px;width:{BOX['w']}px;height:{BOX['h']}px;overflow:hidden;background:var(--bg)}}
.box iframe{{border:0;width:{inner_w:.1f}px;height:{inner_h:.1f}px;transform:scale({SCALE:.4f});transform-origin:0 0}}
.phone{{display:none;margin:auto;width:390px;height:844px;border:10px solid var(--ink);border-radius:36px;overflow:hidden;background:var(--bg)}}
.phone iframe{{border:0;width:390px;height:844px}}
body[data-v="before"] .box{{display:none}}
body[data-v="phone"] .stagewrap{{display:none}} body[data-v="phone"] .phone{{display:block}}
.note{{color:var(--muted);font-size:12.5px;margin:8px auto 0;max-width:1400px}}
</style></head><body data-v="after">
<div class="bar"><h1>אבטחה — לפני ואחרי</h1>
  <div class="seg" role="group" aria-label="מה מוצג"><button type="button" data-v="before">לפני</button><button type="button" data-v="after">אחרי</button><button type="button" data-v="phone">טלפון</button></div>
  <div class="seg" role="group" aria-label="ערכת צבע"><button type="button" data-t="light">בהיר</button><button type="button" data-t="dark">כהה</button></div></div>
<div class="stagewrap" id="wrap"><div class="stage" id="stage"><div class="box"><iframe id="fd" title="המסך המוצע" srcdoc="{light}"></iframe></div></div></div>
<div class="phone"><iframe id="fp" title="המסך המוצע בטלפון" srcdoc="{light}"></iframe></div>
<p class="note">«לפני» הוא צילום המסך שלך מ-18:25. «אחרי» מצייר את אותו אזור באפליקציה, באותו גיליון סגנונות, עם המספרים של אותו רגע (Exampleu, ‏22,298 בקשות).</p>
<script>
var L = {{light: {json.dumps(light)}, dark: {json.dumps(dark)}}};
function fit() {{ var w = document.getElementById("wrap").clientWidth, s = w / {IMG['w']};
  document.getElementById("stage").style.transform = "scale(" + s + ")"; document.getElementById("wrap").style.height = ({IMG['h']} * s) + "px"; }}
function set(v, t) {{
  if (v) document.body.setAttribute("data-v", v);
  if (t) {{ var src = document.createElement("textarea"); src.innerHTML = L[t];
    document.getElementById("fd").srcdoc = src.value; document.getElementById("fp").srcdoc = src.value;
    document.documentElement.setAttribute("data-theme", t); }}
  document.querySelectorAll("[data-v]").forEach(function (b) {{ if (b.tagName === "BUTTON") b.setAttribute("aria-pressed", b.getAttribute("data-v") === document.body.getAttribute("data-v")); }});
  document.querySelectorAll("[data-t]").forEach(function (b) {{ b.setAttribute("aria-pressed", b.getAttribute("data-t") === (t || document.documentElement.getAttribute("data-theme") || "light")); }});
  fit();
}}
document.querySelectorAll("button[data-v]").forEach(function (b) {{ b.onclick = function () {{ set(b.getAttribute("data-v")); }}; }});
document.querySelectorAll("button[data-t]").forEach(function (b) {{ b.onclick = function () {{ set(null, b.getAttribute("data-t")); }}; }});
window.addEventListener("resize", fit);
var h = location.hash.replace("#", "");
set(h.indexOf("before") === 0 ? "before" : h.indexOf("phone") === 0 ? "phone" : "after", h.indexOf("dark") > 0 ? "dark" : "light");
</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", default=str(SHOT))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    global APP_CSS
    src = APP.read_text(encoding="utf-8")
    m = re.search(r"<style>(.*?)</style>", src, re.S)
    APP_CSS = m.group(1)
    shot = base64.b64encode(pathlib.Path(a.shot).read_bytes()).decode()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page(shot), encoding="utf-8")
    (out / "overview.html").write_text(overview("light"), encoding="utf-8")
    (out / "overview-dark.html").write_text(overview("dark"), encoding="utf-8")
    print(f"wrote {out / 'index.html'} ({(out / 'index.html').stat().st_size // 1024} KB)")
    return 0


APP_CSS = ""
if __name__ == "__main__":
    raise SystemExit(main())
