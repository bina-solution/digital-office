"""«קבצים» on a laptop, with no stack: serves apps/drive/static and answers every other path with
the app's page plus tests/ui/mock.js (the in-page stand-in for the drive API), so deep links
(/folder/<id>, /p/photos) load like they do behind the console.

    python apps/drive/tests/ui/dev_server.py [port]      # default 8971 → http://127.0.0.1:8971/
"""
import http.server
import mimetypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.normpath(os.path.join(HERE, "..", "..", "static"))
MOCK = os.path.join(HERE, "mock.js")

# «התחברות עם Google» without Google (accounts.js): the window the screen opens is this stand-in — a
# simulation that says it is one — and it comes back to the return page the way the relay does
# (connections /oauth/relay → app.py oauth_google_return), telling the opener which account it made.
CONSENT = """<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><title>חלון ההסכמה — סימולציה</title>
<body style="font:14px system-ui;margin:24px;max-width:420px"><h1 style="font-size:17px">חלון ההסכמה (סימולציה)</h1>
<p>בהדגמה אין Google. כאן בוחרים איזה חשבון מחברים — בלשכה האמיתית זה החלון של Google עצמו.</p>
<p><button id="ok" type="button">אישור · person33@example.com</button> <button id="no" type="button">ביטול</button></p>
<script>var ret=new URLSearchParams(location.search).get("ret")||"/oauth/google/return";
document.getElementById("ok").onclick=function(){location.href=ret+"?code=demo&state=r1.demo";};
document.getElementById("no").onclick=function(){location.href=ret+"?error=access_denied&state=r1.demo";};</script></body></html>"""
RETURN = """<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><title>חזרה מההתחברות</title>
<body style="font:14px system-ui;margin:24px"><b id="t">…</b><script>
var q=new URLSearchParams(location.search),ok=!!q.get("code"),made=[];
try{if(ok&&window.opener&&window.opener.__mockGoogleConnected)made=window.opener.__mockGoogleConnected("person33@example.com");}catch(e){}
document.getElementById("t").textContent=ok?"החשבון חובר":"ההתחברות בוטלה";
try{window.opener&&window.opener.postMessage({type:"dgo:oauth",ok:ok,made:made,error:ok?"":"ההתחברות בוטלה"},location.origin);}catch(e){}
if(window.opener&&ok)setTimeout(function(){window.close();},1200);</script></body></html>"""
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/javascript", ".js")


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, body, ctype, status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        surface = ""
        if path == "/rec" or path.startswith("/rec/"):      # «הקלטות»: the same page under /rec (app.py)
            path, surface = path[4:] or "/", "recorder"
        if path == "/__mock.js":
            with open(MOCK, "rb") as f:
                return self._send(f.read(), "text/javascript; charset=utf-8")
        if path == "/__mock-google":
            return self._send(CONSENT.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/oauth/google/return":
            return self._send(RETURN.encode("utf-8"), "text/html; charset=utf-8")
        local = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if local.startswith(STATIC) and os.path.isfile(local):
            with open(local, "rb") as f:
                ctype = mimetypes.guess_type(local)[0] or "application/octet-stream"
                return self._send(f.read(), ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
            page = f.read().replace("<body>", '<body>\n<script src="/__mock.js"></script>', 1)
        if surface:
            page = page.replace('<html lang="he" dir="rtl">', f'<html lang="he" dir="rtl" data-surface="{surface}">', 1)
        return self._send(page.encode("utf-8"), "text/html; charset=utf-8")

    do_HEAD = do_GET

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8971
    print(f"Files (mock) on http://127.0.0.1:{port}/", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
