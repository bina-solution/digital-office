"""calculator — one page, one file, one door: /healthz for the healthcheck and everything else is the page."""
import http.server, os, socketserver

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PORT = int(os.environ.get("CALCULATOR_PORT", "8997"))


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def do_GET(self):
        if self.path.split("?")[0] == "/healthz":
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path in ("", "/"):
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, *a):
        pass


class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    print(f"calculator on :{PORT}", flush=True)
    S(("0.0.0.0", PORT), H).serve_forever()
