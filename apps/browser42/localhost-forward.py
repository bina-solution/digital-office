#!/usr/bin/env python3
"""Loopback -> Traefik forwarder for internal *.localhost apps.

Chrome pins *.localhost to loopback (RFC 6761) and ignores /etc/hosts and
--host-resolver-rules for it, so the name can't be pointed at Traefik directly.
Instead we make loopback actually serve it: listen on 127.0.0.1 + [::1] on :80
and :443 and L4-forward to the Traefik host, which routes by Host header
(e.g. auth.localhost -> Authentik). One forward per port covers every
*.localhost app — no per-host config. Pure stdlib; no extra dependency.

Usage: localhost-forward.py <traefik-host> [port ...]   (default ports: 80 443)
"""
import asyncio
import sys

TARGET = sys.argv[1]
PORTS = [int(p) for p in sys.argv[2:]] or [80, 443]


async def _pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _serve(port):
    async def on_client(client_reader, client_writer):
        try:
            target_reader, target_writer = await asyncio.open_connection(TARGET, port)
        except Exception:
            client_writer.close()
            return
        await asyncio.gather(
            _pipe(client_reader, target_writer),
            _pipe(target_reader, client_writer),
        )

    # host=["127.0.0.1", "::1"] binds both loopback families (Chrome may use either).
    server = await asyncio.start_server(on_client, host=["127.0.0.1", "::1"], port=port)
    return server


async def main():
    servers = [await _serve(p) for p in PORTS]
    print(f"[localhost-forward] *.localhost -> {TARGET} on loopback {PORTS}", flush=True)
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == "__main__":
    asyncio.run(main())
