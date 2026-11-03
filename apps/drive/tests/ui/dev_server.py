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
