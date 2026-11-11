#!/usr/bin/env bash
# test_attach.sh — `tasks attach` with several files, against a stand-in for Plane and its store.
#
# What is proved here, with the REAL tasks.py (no Docker, no Plane, no HP), each against the defect it closes
# (issues/tasks-attach-stops-at-the-first-file-plane-refuses-…yaml, found on DGO-1628: the sheets after a
# refused .html were never sent, and the one line said an API path, not a file):
#   1. a file Plane refuses never drops the others: each is tried, each has its own line, the refused one
#      named with Plane's reason, and the exit code says that not all of them landed;
#   2. the same for a file the STORE does not take;
#   3. all of them landing exits 0, one line each;
#   4. a file already on the item (its name and size) is not put there twice — what a replay of a kept
#      attach, or a person running it again after a refusal, would otherwise do;
#   5. --json says the same: what landed, what did not and why.
#
#   bash apps/project-pln/test_attach.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; PID=""
stop() { [ -z "${PID}" ] || { kill "${PID}" 2>/dev/null; wait "${PID}" 2>/dev/null; }; PID=""; }   # quietly: no «Terminated»
trap 'stop; rm -rf "${T}"' EXIT
LOG="${T}/plane.log"; : > "${LOG}"
# ── the stand-in: Plane's API (one project, one item) and the store its signed forms point at ───────────
cat > "${T}/plane.py" <<'EOF'
import http.server, json, os, sys
LOG, HAVE = sys.argv[1], json.loads(os.environ.get("STUB_HAVE") or "[]")
W = "/api/v1/workspaces/bina"
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def answer(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def note(self, what):
        with open(LOG, "a") as f: f.write(what + "\n")
    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""
    def do_GET(self):
        p = self.path.split("?")[0]
        page = lambda rows: {"results": rows, "next_page_results": False}
        if p == f"{W}/projects/": return self.answer(200, page([{"id": "p1", "identifier": "DGO", "name": "DGO"}]))
        if p.endswith("/states/"): return self.answer(200, page([{"id": "s1", "group": "unstarted", "name": "Todo"}]))
        if p.endswith(("/labels/", "/modules/")): return self.answer(200, page([]))
        if p == f"{W}/work-items/DGO-1/":
            return self.answer(200, {"id": "i1", "sequence_id": 1, "name": "t", "state": {"name": "Todo", "group": "unstarted"}})
        if p.endswith("/issue-attachments/"):
            return self.answer(200, [{"id": f"old{i}", "attributes": {"name": n, "size": s}} for i, (n, s) in enumerate(HAVE)])
        self.answer(404, {"error": "no such route in the stand-in: " + p})
    def do_POST(self):
        p, raw = self.path.split("?")[0], self.body()
        if p == "/uploads":                                     # the store, through Plane's signed form
            name = raw.split(b'name="key"\r\n\r\n', 1)[-1].split(b"\r\n", 1)[0].decode()
            self.note(f"STORE {name}")
            # store-no: refused for good (too large, say); store-busy: the store is restarting
            if name.startswith("store-gone"):                  # the link door between routes: 404, no body
                self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
            return self.answer(400 if name.startswith("store-no") else 503 if name.startswith("store-busy") else 204, {})
        if p.endswith("/issue-attachments/"):
            b = json.loads(raw or b"{}")
            self.note(f"POST {b.get('name')}")
            if b.get("name", "").startswith("die"):             # Plane goes away mid-run: no answer at all
                os._exit(0)
            if b.get("name", "").startswith("busy"):            # Plane restarting behind its door
                return self.answer(502, {"error": "bad gateway"})
            if b.get("name", "").endswith(".html"):
                return self.answer(400, {"error": "Invalid file type.", "status": False})
            port = self.server.server_address[1]
            return self.answer(200, {"asset_id": "a-" + b["name"],
                                     "upload_data": {"url": f"http://127.0.0.1:{port}/uploads", "fields": {"key": b["name"]}}})
        self.answer(404, {"error": "no such route in the stand-in: " + p})
    def do_PATCH(self):
        self.body()
        self.note("CONFIRM " + self.path.rstrip("/").rsplit("/", 1)[-1])
        self.answer(200, {})
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
print(srv.server_address[1], flush=True)
srv.serve_forever()
EOF
FAILS=0
start() {   # start [the files already on the item, as JSON [[name, size], …]]
  stop
  : > "${LOG}"; rm -f "${T}/port"
  STUB_HAVE="${1:-[]}" python3 "${T}/plane.py" "${LOG}" > "${T}/port" 2>"${T}/plane.err" & PID=$!
  for _ in $(seq 1 50); do [ -s "${T}/port" ] && break; sleep 0.1; done
  PORT="$(head -1 "${T}/port")"
}
attach() {  # attach <args…> → $out, $rc
  out="$(cd "${T}" && env -u PLANE_AS -u LINK_BASE -u CONSOLE_URL PLANE_API_URL="http://127.0.0.1:${PORT}" \
         PLANE_LOCAL_API_TOKEN=CHANGE_ME PLANE_WORKSPACE=bina TASKS_CACHE="${T}/cache.json" \
         python3 "${HERE}/tasks.py" attach DGO-1 "$@" 2>&1)"; rc=$?
  rm -f "${T}/cache.json"
}
check() {   # check <name> <condition…>
  local name="$1"; shift
  if "$@"; then echo "PASS  ${name}"; else echo "FAIL  ${name}"; printf '%s\n' "${out}" | sed 's/^/      /'; FAILS=$((FAILS + 1)); fi
}
has() { printf '%s' "${out}" | grep -qF -- "$1"; }
logged() { grep -qxF -- "$1" "${LOG}"; }
printf 'png-a\n' > "${T}/sheet-a.png"; printf 'png-b\n' > "${T}/sheet-b.png"
printf '<!doctype html>\n' > "${T}/mock.html"; printf 'png-c\n' > "${T}/store-no.png"

# ── 1. Plane refuses the FIRST file: the two after it still land, each said, and the exit says not all did.
start
attach "${T}/mock.html" "${T}/sheet-a.png" "${T}/sheet-b.png"
check "a refused file does not drop the files after it" \
  bash -c 'grep -qxF "CONFIRM a-sheet-a.png" "$1" && grep -qxF "CONFIRM a-sheet-b.png" "$1"' _ "${LOG}"
check "the refused file is named, with Plane's reason" has "mock.html: NOT attached — Plane refused it (HTTP 400: Invalid file type.)"
check "each file that landed has its own line" bash -c 'has() { printf "%s" "$1" | grep -qF -- "$2"; }; has "$1" "sheet-a.png (6 bytes) is on DGO-1" && has "$1" "sheet-b.png (6 bytes) is on DGO-1"' _ "${out}"
check "the exit code says not all of them landed — 4, Plane answered (rc=${rc})" test "${rc}" -eq 4
check "the last line counts both" has "DGO-1  2 of 3 file(s) attached — not: mock.html"

# ── 2. the STORE does not take the middle file: the last one still lands.
start
attach "${T}/sheet-a.png" "${T}/store-no.png" "${T}/sheet-b.png"
check "a file the store refuses does not drop the next" logged "CONFIRM a-sheet-b.png"
check "it is never confirmed on the item" bash -c '! grep -qxF "CONFIRM a-store-no.png" "$1"' _ "${LOG}"
check "it is named, with the store's answer" has "store-no.png: NOT attached — the store did not take it (HTTP 400)"
check "and the exit code is 4 (rc=${rc})" test "${rc}" -eq 4

# ── 3. all of them land: exit 0, a line for each, the summary as it always was.
start
attach "${T}/sheet-a.png" "${T}/sheet-b.png"
check "all landed: exit 0 (rc=${rc})" test "${rc}" -eq 0
check "all landed: the summary line" has "DGO-1  2 file(s) attached"

# ── 4. a file already on the item, by name and size, is not put there a second time.
start '[["sheet-a.png", 6]]'
attach "${T}/sheet-a.png" "${T}/sheet-b.png"
check "a file already on the item is not sent again" bash -c '! grep -qxF "POST sheet-a.png" "$1" && grep -qxF "CONFIRM a-sheet-b.png" "$1"' _ "${LOG}"
check "it says so" has "sheet-a.png (6 bytes) is on DGO-1 already"
check "and that is success (rc=${rc})" test "${rc}" -eq 0

# ── 5. --json: what landed, what did not, and why.
start
attach "${T}/mock.html" "${T}/sheet-a.png" --json
js="$(printf '%s\n' "${out}" | grep '^{' | tail -1)"
check "--json: ok is false, one attached, the refused one with its reason" python3 -c '
import json, sys
d = json.loads(sys.argv[1])
assert d["ok"] is False and d["attached"] == 1 and d["files"] == ["sheet-a.png"], d
assert [r["name"] for r in d["refused"]] == ["mock.html"] and "Invalid file type" in d["refused"][0]["why"], d' "${js:-{\}}"

# ── 6. Plane does not ANSWER (gone mid-run): the run stops there, in the words hooks/tasks keeps a write by, and
#       nothing after it is tried — the hook queues the whole attach, and its replay skips what landed (check 4).
start
printf 'png-d\n' > "${T}/die.png"
attach "${T}/sheet-a.png" "${T}/die.png" "${T}/sheet-b.png"
check "no answer: the run stops, not 0 and not 4 (rc=${rc})" test "${rc}" -eq 1
check "no answer: in the words the hook queues by" bash -c 'printf "%s" "$1" | grep -qiE "urlerror|gave up|connection refused|timed out|name or service not known"' _ "${out}"
check "no answer: the file after it is not tried" bash -c '! grep -qxF "POST sheet-b.png" "$1"' _ "${LOG}"
check "no answer: the file before it landed" logged "CONFIRM a-sheet-a.png"

# ── 7. a refusal that may PASS (Plane restarting: 502; the store busy: 503) is not final: the others still go, the
#       line says it may go another time, and the exit is 1 — a replay keeps the write instead of letting it go
#       (exit 4 is only for a refusal sending again cannot change: the second reader of DGO-1628).
start
printf 'png-e\n' > "${T}/busy.png"; printf 'png-f\n' > "${T}/store-busy.png"
attach "${T}/busy.png" "${T}/store-busy.png" "${T}/sheet-b.png"
check "may pass: the file after them still lands" logged "CONFIRM a-sheet-b.png"
check "may pass: Plane's 502 is said, as one to send again" has "busy.png: NOT attached — Plane refused it (HTTP 502: bad gateway) — send it again later"
check "may pass: the store's 503 too" has "store-busy.png: NOT attached — the store did not take it (HTTP 503) — send it again later"
check "may pass: the exit is 1, not 4 (rc=${rc})" test "${rc}" -eq 1
start
printf 'png-g\n' > "${T}/store-gone.png"
attach "${T}/store-gone.png"
check "may pass: the door's empty 404 on the store is not final (rc=${rc})" test "${rc}" -eq 1
start
attach "${T}/mock.html" "${T}/busy.png"
check "one final and one that may pass: still 1 — the write is kept (rc=${rc})" test "${rc}" -eq 1

echo
[ "${FAILS}" = 0 ] && echo "test_attach: all passed" || echo "test_attach: ${FAILS} failed"
exit $((FAILS > 0))
