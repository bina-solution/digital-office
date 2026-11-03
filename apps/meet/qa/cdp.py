#!/usr/bin/env python3
"""Minimal Chrome DevTools client (stdlib only) for the meeting page.
   cdp.py <remote-debugging-port> <expression>      evaluate JS, print the result
   cdp.py <remote-debugging-port> key:<char>        press one key (a real, trusted key event)"""
import base64, json, os, socket, struct, sys, urllib.request
from urllib.parse import urlparse

port, expr = int(sys.argv[1]), sys.argv[2]
targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=10))
pages = [t for t in targets if t.get("type") == "page" and "meet.fpg" in t.get("url", "")]
if not pages:
    sys.exit("no meeting page: " + ", ".join(t.get("url", "")[:60] for t in targets))
u = urlparse(pages[0]["webSocketDebuggerUrl"])
s = socket.create_connection((u.hostname, u.port), timeout=20)
key = base64.b64encode(os.urandom(16)).decode()
s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
buf = b""
while b"\r\n\r\n" not in buf:
    buf += s.recv(4096)
assert b" 101 " in buf.split(b"\r\n")[0], buf[:200]


def send(obj):
    data = json.dumps(obj).encode(); mask = os.urandom(4); n = len(data)
    hdr = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536
                           else bytes([0x80 | 127]) + struct.pack(">Q", n))
    s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def rd(n):
    b = b""
    while len(b) < n:
        c = s.recv(n - len(b))
        if not c:
            raise EOFError
        b += c
    return b


def recv():
    h = rd(2); n = h[1] & 0x7F
    if n == 126:
        n = struct.unpack(">H", rd(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", rd(8))[0]
    return json.loads(rd(n))


def call(i, method, params):
    send({"id": i, "method": method, "params": params})
    while True:
        m = recv()
        if m.get("id") == i:
            return m


if expr.startswith("key:"):
    ch = expr[4:]
    code = "Key" + ch.upper(); vk = ord(ch.upper())
    call(1, "Input.dispatchKeyEvent", {"type": "keyDown", "key": ch, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk, "text": ch})
    call(2, "Input.dispatchKeyEvent", {"type": "keyUp", "key": ch, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk})
    print(json.dumps({"key": ch, "sent": True}))
else:
    m = call(1, "Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
    r = m.get("result", {})
    print(json.dumps(r.get("result", r), ensure_ascii=False)[:6000])
