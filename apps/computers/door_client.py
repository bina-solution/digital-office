#!/usr/bin/env python3
"""ssh's ProxyCommand for a SHARED computer: stdin/stdout ⇄ wss://<lender>/share/<token>.

    ssh -o ProxyCommand='python3 /app/door_client.py wss://computers.<domain>/share/<token>' …

The lending office's side is share.py. This goes through the environment's proxy when one is set
(HTTPS_PROXY, honouring NO_PROXY) and trusts the system store or SSL_CERT_FILE, so it works on a
laptop, on a VPS and behind a TLS-intercepting egress alike.
"""
import asyncio
import os
import ssl
import sys

from websockets.asyncio.client import connect


def _ssl(url):
    if not url.startswith("wss://"):
        return None
    ca = os.environ.get("SSL_CERT_FILE")
    return ssl.create_default_context(cafile=ca) if ca and os.path.exists(ca) else ssl.create_default_context()


async def main(url):
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    out = sys.stdout.buffer
    async with connect(url, ssl=_ssl(url), max_size=None, open_timeout=20,
                       ping_interval=20, ping_timeout=40, compression=None) as ws:
        async def up():
            while chunk := await reader.read(65536):
                await ws.send(chunk)
            await ws.close()

        async def down():
            async for msg in ws:
                out.write(msg if isinstance(msg, bytes) else msg.encode())
                out.flush()

        _, pending = await asyncio.wait([asyncio.create_task(up()), asyncio.create_task(down())],
                                        return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else ""
    if not url.startswith(("wss://", "ws://")):
        sys.exit("door_client: usage: door_client.py wss://<lender>/share/<token>")
    try:
        asyncio.run(main(url))
    except Exception as e:  # ssh prints our stderr as its own reason — one line, what failed
        sys.exit(f"door_client: {type(e).__name__}: {e}")
