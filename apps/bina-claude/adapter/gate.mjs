// apps/bina-claude/adapter/gate.mjs — the terminal's front door: only the edge and the console get in.
//
// The terminal is a root shell with the engine's socket. ttyd's own check (--auth-header) asks only that
// the identity header is PRESENT, and any container on traefik-network can send one it made up (the
// second reader of DGO-1074; the forged-header finding in ai/context/dgo-security.md). So ttyd listens on
// the container's loopback, and this door, on :7681, admits a connection only from an address that the
// office's own DNS gives to the two hops a person's browser really comes through: traefik (the edge,
// which carries the websocket) and the console (which proxies the page). A container cannot answer
// from another container's address on the bridge; a header it can write, an address it cannot.
import http from "node:http";
import net from "node:net";
import dns from "node:dns/promises";

const PORT = Number(process.env.BINA_CLAUDE_TERMINAL_PORT || 7681);
const TTYD = Number(process.env.BINA_CLAUDE_TTYD_PORT || 7682);
// …and the link proxy (`dgo-net`, whose namespace dgo-link runs in): a LINKED office's console reaches
// this office's tile through it, after the consuming office's own edge has signed the person in — the
// owner opening the HP's Claude from vps1 (DGO-1074). It strips every identity header on the way, so the
// terminal (ttyd -H) stays this office's own; the desktop stream needs none.
const PEERS = (process.env.BINA_CLAUDE_TERMINAL_PEERS ||
  `console traefik-deployment traefik-${process.env.DEPLOYMENT_NAME || "bina-deployment"} dgo-net`).split(/\s+/).filter(Boolean);

// The peers' addresses, re-asked every 10 s (a recreated console's old address is admitted at most that
// long). ONE lookup at a time, shared by every connection waiting on it, and a miss can force a fresh
// one at most every 3 s — a flood of strangers must not queue the real console behind thousands of DNS
// questions (second reader, DGO-1074). A name whose lookup fails keeps its last good answer unless DNS
// says it no longer exists.
const TTL = 10000, MISS_REFRESH = 3000;
const known = new Map();                 // name → [addresses]
let allowed = new Set(["127.0.0.1", "::1"]), resolvedAt = 0, pending = null;
function refresh() {
  if (!pending) {
    pending = (async () => {
      for (const name of PEERS) {
        try { known.set(name, (await dns.lookup(name, { all: true })).map((a) => a.address)); }
        catch (e) { if (e && e.code === "ENOTFOUND") known.delete(name); }
      }
      allowed = new Set(["127.0.0.1", "::1", ...[...known.values()].flat()]);
      resolvedAt = Date.now();
    })().finally(() => { pending = null; });
  }
  return pending;
}
const addr = (sock) => String(sock.remoteAddress || "").replace(/^::ffff:/, "");
async function admitted(sock) {
  if (Date.now() - resolvedAt > TTL) await refresh();
  if (allowed.has(addr(sock))) return true;
  if (Date.now() - resolvedAt > MISS_REFRESH) await refresh();   // a recreated console: ask once more
  return allowed.has(addr(sock));
}

// A socket reset while its admission is decided, or after the 403, must never take the door down with
// every live session behind it: Node drops its own 'error' listener from an upgraded socket.
process.on("uncaughtException", (e) => console.error(`[bina-claude] gate: ${e && e.message}`));

const server = http.createServer(async (req, res) => {
  if (!(await admitted(req.socket))) {
    res.writeHead(403, { "content-type": "text/plain" });
    return res.end("this opens through the office console only\n");
  }
  const up = http.request({ host: "127.0.0.1", port: TTYD, method: req.method, path: req.url, headers: req.headers }, (r) => {
    res.writeHead(r.statusCode, r.headers);
    r.pipe(res);
  });
  up.on("error", () => { if (!res.headersSent) res.writeHead(502); res.end(); });
  req.pipe(up);
});

server.on("upgrade", async (req, sock, head) => {
  sock.on("error", () => sock.destroy());
  if (!(await admitted(sock))) { sock.end("HTTP/1.1 403 Forbidden\r\nconnection: close\r\n\r\n"); return; }
  const up = net.connect(TTYD, "127.0.0.1", () => {
    let lines = `${req.method} ${req.url} HTTP/1.1\r\n`;
    for (let i = 0; i < req.rawHeaders.length; i += 2) lines += `${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}\r\n`;
    up.write(lines + "\r\n");
    if (head && head.length) up.write(head);
    up.pipe(sock); sock.pipe(up);
  });
  const drop = () => { up.destroy(); sock.destroy(); };
  up.on("error", drop); sock.on("error", drop);
});

server.listen(PORT, "0.0.0.0", () => console.log(`[bina-claude] gate on :${PORT} → ttyd 127.0.0.1:${TTYD} · peers: ${PEERS.join(" ")}`));
