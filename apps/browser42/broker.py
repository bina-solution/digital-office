#!/usr/bin/env python3
import asyncio
import json
import os
import uuid
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve


extension = None
pending = {}
PROTOCOL_VERSION = 1
SUPPORTED_ACTIONS = {"allocate", "close", "status", "list", "claim"}
# How long the broker waits for the extension to answer one command. Must exceed
# the slowest legitimate operation (allocate on an ad-heavy page: the ownership
# wait in group-manager can run minutes). Real failures stay event-driven: when
# the extension socket closes, every pending future is failed immediately, so a
# dead extension still returns fast. The OLD hardcoded 20s timed out valid
# ad-heavy-site allocates, the client's 25s recv expired first, the client closed its socket,
# and the unguarded result-send below then raised ConnectionClosedError — the
# "connection handler failed" / "extension is not connected" flapping (0805r-t).
COMMAND_WAIT_SECONDS = float(os.environ.get("BROWSER42_BROKER_WAIT_SECONDS", "240"))


async def handle_extension(socket):
    global extension
    extension = socket
    try:
        async for raw in socket:
            try:
                message = json.loads(raw)
            except (ValueError, TypeError):
                continue  # never let one malformed frame kill the extension socket
            request_id = message.get("requestId")
            future = pending.pop(request_id, None)
            if future and not future.done():
                future.set_result(message)
    finally:
        if extension is socket:
            extension = None
        for future in pending.values():
            if not future.done():
                future.set_exception(RuntimeError("extension disconnected"))
        pending.clear()


async def handle_client(socket, message):
    command = dict(message.get("command") or {})
    if command.get("protocolVersion") != PROTOCOL_VERSION:
        await socket.send(json.dumps({"ok": False, "error": {"code": "protocol_mismatch", "message": "unsupported Browser42 broker protocol"}}))
        return
    if command.get("action") not in SUPPORTED_ACTIONS:
        await socket.send(json.dumps({"ok": False, "error": {"code": "invalid_command", "message": "unsupported Browser42 broker action"}}))
        return
    if extension is None:
        await socket.send(json.dumps({"ok": False, "error": {"code": "extension_unavailable", "message": "extension is not connected"}}))
        return
    request_id = uuid.uuid4().hex
    command["requestId"] = request_id
    future = asyncio.get_running_loop().create_future()
    pending[request_id] = future
    try:
        await extension.send(json.dumps(command))
        result = await asyncio.wait_for(future, timeout=COMMAND_WAIT_SECONDS)
    except asyncio.TimeoutError:
        pending.pop(request_id, None)
        result = {"ok": False, "error": {"code": "broker_timeout", "message": f"extension did not answer within {COMMAND_WAIT_SECONDS:.0f}s"}, "requestId": request_id}
    except Exception as error:
        pending.pop(request_id, None)
        result = {"ok": False, "error": {"code": "broker_error", "message": str(error)}, "requestId": request_id}
    try:
        await socket.send(json.dumps(result))
    except Exception:
        pass  # client gave up and closed (its own recv budget expired); not an error


async def handler(socket):
    raw = await asyncio.wait_for(socket.recv(), timeout=10)
    message = json.loads(raw)
    if message.get("role") == "extension":
        await handle_extension(socket)
    elif message.get("role") == "client":
        await handle_client(socket, message)
    else:
        await socket.send(json.dumps({"ok": False, "error": "invalid broker role"}))


async def main():
    host = os.environ.get("BROWSER42_BROKER_HOST", "127.0.0.1")
    async with serve(handler, host, 8765, ping_interval=15, ping_timeout=15):
        print("browser42 broker listening on 127.0.0.1:8765", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())