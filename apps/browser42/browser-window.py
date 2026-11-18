#!/usr/bin/env python3
"""browser42-window.py compact|standard — the shared Chromium's presentation, set as a STATE.

Compact is Chrome's own fullscreen, the one F11 toggles: no tab strip, no toolbar. It used to be reached
by pressing F11, and a toggle cannot be made reliable: a press Chrome swallowed while starting left the
window standard for good, two presses landing late under load left it standard too, and the next press
could undo the hand-off's (DGO-1921). DevTools sets the state itself, so asking twice is asking once.

It talks to Chrome's own DevTools port, found on cloakserve's status page (which launches nothing) — never
through cloakserve's proxy, so no client is counted and a sleeping browser is not woken.
Exit 0 when every window already was in the asked state; 1 when one was just set (look again) or Chrome
is not running.
"""
import asyncio
import json
import sys
import urllib.request

from websockets.asyncio.client import connect


def get(url: str):
    with urllib.request.urlopen(url, timeout=5) as answer:
        return json.load(answer)


async def present(want: str) -> int:
    port = ((get("http://127.0.0.1:9222/").get("processes") or {}).get("__default__") or {}).get("port")
    if not port:
        return 1
    base = f"http://127.0.0.1:{port}"
    pages = [t["id"] for t in get(base + "/json/list") if t.get("type") == "page"]
    async with connect(get(base + "/json/version")["webSocketDebuggerUrl"], max_size=None, open_timeout=5) as ws:
        ids = iter(range(1, 1_000_000))

        async def call(method: str, params: dict) -> dict:
            i = next(ids)
            await ws.send(json.dumps({"id": i, "method": method, "params": params}))
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), 10))
                if message.get("id") == i:
                    return message.get("result") or {}

        windows = {(await call("Browser.getWindowForTarget", {"targetId": p})).get("windowId") for p in pages} - {None}
        settled = bool(windows)
        for window in windows:
            fullscreen = (await call("Browser.getWindowBounds", {"windowId": window})).get("bounds", {}).get("windowState") == "fullscreen"
            if fullscreen != (want == "compact"):
                await call("Browser.setWindowBounds", {"windowId": window,
                                                       "bounds": {"windowState": "fullscreen" if want == "compact" else "normal"}})
                settled = False
        return 0 if settled else 1


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("compact", "standard"):
        raise SystemExit("usage: browser42-window.py compact|standard")
    try:
        sys.exit(asyncio.run(present(sys.argv[1])))
    except Exception as error:                      # Chrome going away mid-call is "not yet", not a crash
        print(f"browser42-window: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
