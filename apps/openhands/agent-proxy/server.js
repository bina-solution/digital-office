/**
 * OpenHands Agent Proxy - WebSocket/HTTP bridge for agent-server sandboxes.
 * Routes /agent/{port}/* -> host.docker.internal:{port}/*
 *
 * Uses Node's native HTTP upgrade mechanism for proper WebSocket proxying.
 */
import { createServer } from 'node:http';
import http from 'node:http';

const PORT = parseInt(process.env.PROXY_PORT || '8802', 10);
const HOST = process.env.AGENT_HOST || 'host.docker.internal';

function parseUrl(url) {
  var m = url.match(/^\/agent\/(\d+)(\/.*)?$/);
  return m ? { port: parseInt(m[1], 10), path: m[2] || '/' } : null;
}

var server = createServer(function(req, res) {
  if (req.url === '/healthz') {
    res.writeHead(200, { 'content-type': 'application/json' });
    return res.end(JSON.stringify({ ok: true }));
  }
  var t = parseUrl(req.url);
  if (!t || t.port < 1024 || t.port > 65535) {
    res.writeHead(400);
    return res.end('Expected /agent/{port}/...');
  }
  var isWs = (req.headers['upgrade'] || '').toLowerCase() === 'websocket';

  if (!isWs) {
    // HTTP proxy
    var opts = { hostname: HOST, port: t.port, path: t.path, method: req.method, headers: req.headers, timeout: 30000 };
    var pr = http.request(opts, function(pres) {
      res.writeHead(pres.statusCode, pres.headers);
      pres.pipe(res);
    });
    pr.on('error', function() { try { res.writeHead(502); res.end(); } catch(e) {} });
    req.pipe(pr);
    return;
  }

  // WebSocket proxy using HTTP upgrade
  console.log('[ws] ' + t.port + t.path);
  var wsOpts = { hostname: HOST, port: t.port, path: t.path, method: 'GET', headers: req.headers };
  var wsReq = http.request(wsOpts);
  wsReq.end();

  wsReq.on('upgrade', function(proxyRes, backendSocket, head) {
    // Send 101 Switching Protocols to client
    var headLines = [];
    headLines.push('HTTP/1.1 101 Switching Protocols');
    for (var k in proxyRes.headers) {
      headLines.push(k + ': ' + proxyRes.headers[k]);
    }
    headLines.push('', '');
    req.socket.write(headLines.join('\r\n'));

    // Remove HTTP parser from client socket so we can do raw WebSocket
    req.socket.removeAllListeners('data');

    // Bidirectional forwarding
    var clientSocket = req.socket;
    clientSocket.on('data', function(data) { backendSocket.write(data); });
    backendSocket.on('data', function(data) { clientSocket.write(data); });
    clientSocket.on('error', function() { backendSocket.destroy(); });
    backendSocket.on('error', function() { clientSocket.destroy(); });
    clientSocket.on('close', function() { backendSocket.destroy(); });
    backendSocket.on('close', function() { clientSocket.destroy(); });

    // Flush any remaining head data
    if (head && head.length > 0) clientSocket.write(head);
  });

  wsReq.on('error', function(e) {
    console.error('[ws] err ' + t.port + ': ' + e.message);
    try { res.writeHead(502); res.end(); } catch(e2) {}
  });
});

server.listen(PORT, '0.0.0.0', function() { console.log('agent-proxy :' + PORT + ' -> ' + HOST); });
