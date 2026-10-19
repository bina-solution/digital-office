#!/usr/bin/env python3
"""console-dev-server.py — the console shell with no stack (dev only, stdlib + ruby for YAML).

    python3 digital-office/sim/console-dev-server.py      # → http://localhost:8765

Serves the REAL platform-base/console/static files and fakes the handful of APIs the shell reads
(/api/me, /api/modules, /api/office, /api/version), plus a same-origin mock page for every
/a/<alias>/ app, so the shell — and desktop mode (static/desktop.js) — can be driven on a machine
with no Docker and no node (this repo's Mac). The module list is the real compiled registry
(.generated/registry/console.modules.yaml) merged with console/modules.yaml, as app.py does, plus a
dev-only "player" app that publishes a bina:widget, so the window-becomes-widget step can be seen.
Like everything under digital-office/, it is a workbench tool: never shipped, never run by CI.
"""
import json, os, re, subprocess, sys, time, random, html
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC = os.path.join(REPO, "platform-base/console/static")
PORT = int(os.environ.get("PORT", "8765"))
# The office's palette, read where it is written: the stand-in app page below names its tokens, so
# it is the office's colours on the light ground and on the dark one, with no copy of them here.
with open(os.path.join(REPO, "platform-base/bina-ui/theme-tokens.css"), encoding="utf-8") as _fh:
    PALETTE = _fh.read().split("/* @bina-theme-tokens:start */", 1)[1].split("/* @bina-theme-tokens:end */", 1)[0]


def load_modules():
    rb = ('require "yaml"; require "json"; '
          'gen = YAML.load_file(ARGV[0]) || []; own = (YAML.load_file(ARGV[1]) || []).reject{|m| m["embed"]}; '
          'puts JSON.dump((gen + own).sort_by{|m| m["order"] || 999})')
    out = subprocess.check_output(["ruby", "-e", rb,
                                   os.path.join(REPO, ".generated/registry/console.modules.yaml"),
                                   os.path.join(REPO, "platform-base/console/modules.yaml")])
    mods = json.loads(out)
    # a dev-only player, so the demo's "window becomes a widget" can be shown with a real action
    mods.append({"id": "player", "name": "נגן", "icon": "activity", "group": "ראשי",
                 "embed": "/a/player/", "desc": "נגן מוזיקה (דמו מקומי)", "order": 3.5})
    return sorted(mods, key=lambda m: m.get("order", 999))


MODULES = load_modules()
BY_ALIAS = {m["embed"].strip("/").split("/")[1]: m for m in MODULES if m.get("embed")}

LOREM = [
    "הלקוח ביקש לקבל את החשבונית המתוקנת עד סוף השבוע, כולל פירוט המע\"מ לפי סעיפים.",
    "תעודת המשלוח התקבלה מהספק ונסרקה אוטומטית; שני שדות דורשים בדיקה ידנית.",
    "סיכום הפגישה: מעבר לדיווח חודשי, תזכורת אוטומטית שלושה ימים לפני המועד.",
    "המאזן הרבעוני מוכן לעיון. יש לאשר את ההתאמות בחשבון הבנק לפני השליחה לרואה החשבון.",
    "הצעת המחיר של הספק החדש זולה בשמונה אחוזים, אך זמני האספקה ארוכים יותר.",
    "נדרש לעדכן את פרטי הקשר של החברה ברשם החברות ובמערכת ההנהלה.",
]
ITEMS = ["חשבונית 10492 — חומרי בניין בע\"מ", "תעודת משלוח 5531 — הובלות הצפון", "מאזן 2026 רבעון 3",
         "הצעת מחיר — ברזל ומלט", "דוח מע\"מ ספטמבר", "חוזה שכירות — מחסן אשדוד", "קבלה 8812 — ציוד משרדי",
         "פרוטוקול ישיבת הנהלה", "אישור ניכוי מס במקור", "רשימת ספקים מעודכנת"]
SECTIONS = [("", "ראשי"), ("/list", "רשימה"), ("/report", "דוח"), ("/settings", "הגדרות")]


def app_page(alias, sub):
    m = BY_ALIAS.get(alias, {"name": alias, "id": alias})
    name = html.escape(m["name"])
    base = f"/a/{alias}"
    if alias == "player":
        return player_page()
    nav = "".join(f'<a href="{base}{p or "/"}" class="{"on" if ("/" + sub).rstrip("/") == p else ""}">{t}</a>'
                  for p, t in SECTIONS)
    rnd = random.Random(alias + sub)
    rows = "".join(f'<li><b>{html.escape(rnd.choice(ITEMS))}</b><span>{rnd.randint(1, 28)}.09.2026</span>'
                   f'<p>{html.escape(rnd.choice(LOREM))}</p></li>' for _ in range(9))
    paras = "".join(f"<p>{html.escape(rnd.choice(LOREM))} {html.escape(rnd.choice(LOREM))}</p>" for _ in range(6))
    links = "".join(f'<a class="ext" href="https://example.com/{i}">קישור לדוגמה {i}</a>' for i in range(1, 4))
    title = f"{m['name']}" + (f" · {dict(SECTIONS).get('/' + sub.split('/')[0], sub)}" if sub else "")
    return f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>
{PALETTE}
*{{box-sizing:border-box}} body{{margin:0;font:14px/1.5 system-ui,"Noto Sans Hebrew",sans-serif;background:var(--bg);color:var(--ink)}}
header{{display:flex;align-items:center;gap:12px;padding:10px 16px;background:var(--surface);border-bottom:1px solid var(--line)}}
header h1{{font-size:16px;margin:0}} nav{{display:flex;gap:4px;margin-inline-start:auto}}
nav a{{padding:5px 10px;border-radius:8px;color:var(--muted);text-decoration:none}} nav a.on{{background:var(--accent-soft);color:var(--accent-d);font-weight:600}}
main{{display:grid;grid-template-columns:1.2fr 1fr;gap:16px;padding:16px}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px}}
ul{{list-style:none;margin:0;padding:0}} li{{padding:8px 0;border-bottom:1px solid var(--line)}} li span{{float:left;color:var(--muted);font-size:12px}}
li p{{margin:4px 0 0;color:var(--muted);font-size:13px}} .ext{{display:block;color:var(--blue);margin:4px 0}}
form{{display:grid;gap:8px}} textarea{{min-height:70px;font:inherit}} button{{justify-self:start;padding:6px 14px;border-radius:8px;border:0;background:var(--accent);color:var(--accent-ink)}}
@media (max-width:620px){{ main{{grid-template-columns:1fr;padding:10px}} nav a:not(.on){{display:none}} li p{{display:none}} .wide{{display:none}} }}
@media (max-width:380px){{ header{{padding:8px 10px}} .card{{padding:8px}} li:nth-child(n+5){{display:none}} }}
</style></head><body>
<header><h1>{name}</h1><nav>{nav}</nav></header>
<main><section class="card"><h2 style="font-size:15px;margin:0 0 6px">פריטים אחרונים</h2><ul>{rows}</ul></section>
<section class="card wide"><h2 style="font-size:15px;margin:0 0 6px">פרטים</h2>{paras}{links}
<form onsubmit="event.preventDefault();this.querySelector('textarea').value='';"><textarea placeholder="הערה…"></textarea><button>שליחה</button></form></section></main>
<script>
(function(){{
  var BASE={json.dumps(base)};
  function report(){{ var p=location.pathname.slice(BASE.length)||"/"; parent.postMessage({{type:"bina:route",path:p+location.search}},location.origin); }}
  document.addEventListener("click",function(e){{
    var a=e.target.closest("nav a"); if(!a) return; e.preventDefault();
    location.href=a.getAttribute("href");
  }});
  report();
}})();
</script></body></html>"""


def player_page():
    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><title>נגן</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>*{box-sizing:border-box}body{margin:0;background:#121417;color:#e8ecef;font:14px system-ui,sans-serif;height:100vh;display:flex;flex-direction:column}
.top{display:flex;gap:16px;padding:18px;align-items:center}.art{width:120px;height:120px;border-radius:12px;background:linear-gradient(135deg,#6b4dff,#1ed760)}
h1{font-size:20px;margin:0}.sub{color:#9aa4ad}.ctrl{display:flex;gap:10px;align-items:center;margin-top:10px}
button{width:48px;height:48px;border-radius:50%;border:0;background:#1ed760;color:#000;font-size:18px;cursor:pointer}
.bars{display:flex;gap:3px;align-items:flex-end;height:40px;margin:0 18px}.bars i{width:6px;background:#1ed760;height:6px;transition:height .2s}
ol{margin:0;padding:8px 36px;color:#c9d1d9;overflow:auto;flex:1}li{padding:6px 0;border-bottom:1px solid #22262b}
@media (max-width:420px){.top{padding:10px;gap:10px}.art{width:56px;height:56px}ol{display:none}.bars{display:none}}
@media (max-width:220px){.top>div:last-child>*:not(.ctrl){display:none}.art{display:none}.top{justify-content:center}}
</style></head><body>
<div class="top"><div class="art"></div><div><h1>מוזיקה לריכוז</h1><div class="sub">רשימת השמעה · 12 שירים</div>
<div class="ctrl"><button id="pp" aria-label="נגן">▶</button><span id="st" class="sub">עצור</span></div></div></div>
<div class="bars" id="bars"></div><ol>""" + "".join(f"<li>שיר {i}</li>" for i in range(1, 13)) + """</ol>
<script>
var playing=false,b=document.getElementById('bars');for(var i=0;i<40;i++)b.appendChild(document.createElement('i'));
function tick(){ if(playing) [].forEach.call(b.children,function(x){x.style.height=(6+Math.random()*34)+'px'}); }
setInterval(tick,220);
function set(p){ playing=p; document.getElementById('pp').textContent=p?'❚❚':'▶'; document.getElementById('st').textContent=p?'מנגן':'עצור';
  parent.postMessage({type:'bina:widget',label:p?'מנגן':'עצור',action:{id:'toggle',label:p?'השהה':'נגן',icon:p?'pause':'play'}},location.origin); }
document.getElementById('pp').onclick=function(){set(!playing)};
window.addEventListener('message',function(e){ if(e.origin===location.origin&&e.data&&e.data.type==='bina:widget-action'&&e.data.id==='toggle') set(!playing); });
set(false);
parent.postMessage({type:'bina:route',path:'/'},location.origin);
</script></body></html>"""


def spans(q):
    now = int(time.time() * 1000)
    rnd = random.Random(42)
    out = []
    srcs = [("n8n", "n8n", ["קליטת מסמכים", "סנכרון מייל", "גיבוי לילי"]),
            ("indox", "incoming", ["עיבוד מסמך", "זיהוי חברה", "OCR"]),
            ("traefik", "http", ["GET /a/drive", "GET /api/office"])]
    for i in range(160):
        src, svc, labels = rnd.choice(srcs)
        s = now - rnd.randint(0, 6 * 3600 * 1000)
        d = rnd.randint(2000, 15 * 60 * 1000)
        out.append({"id": f"sp{i}", "src": src, "svc": svc, "svcid": svc, "label": rnd.choice(labels),
                    "status": rnd.choice(["success", "success", "success", "error"]), "s": s, "e": s + d, "d": d, "meta": {}})
    return {"spans": out, "now": now}


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (self.command, self.path))

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self._send(200, {"ok": True})

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/api/me":
            return self._send(200, {"name": "שלמה"})
        if p == "/api/modules":
            return self._send(200, {"modules": MODULES})
        if p == "/api/office":
            return self._send(200, {"installed": True, "office": {"name": "בינה סלושנס", "animal": "elephant", "hue": "muted"}})
        if p == "/api/version":
            return self._send(200, {"version": "dev-desktop"})
        if p.startswith("/api/"):
            return self._send(200, {})
        mm = re.match(r"^/a/([^/]+)(/.*)?$", p)
        if mm:
            alias, rest = mm.group(1), (mm.group(2) or "/")
            if alias == "any-concurrency" and rest.startswith("/api/spans"):
                return self._send(200, spans(parse_qs(u.query)))
            if rest.startswith("/api/"):
                return self._send(200, {})
            return self._send(200, app_page(alias, rest.strip("/")), "text/html; charset=utf-8")
        f = os.path.normpath(os.path.join(STATIC, p.lstrip("/") or "index.html"))
        if not f.startswith(STATIC) or not os.path.isfile(f):
            f = os.path.join(STATIC, "index.html")
        ctype = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml",
                 ".png": "image/png"}.get(os.path.splitext(f)[1], "application/octet-stream")
        with open(f, "rb") as fh:
            self._send(200, fh.read(), ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))


if __name__ == "__main__":
    print(f"console dev mock on http://localhost:{PORT} ({len(MODULES)} modules)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
