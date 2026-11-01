#!/usr/bin/env python3
import sys
from pathlib import Path


path = Path(sys.argv[1] if len(sys.argv) > 1 else "/usr/local/bin/cloakserve")
source = path.read_text()
old = """                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await cdp_ws.send(msg.data)
"""
new = """                        if msg.type == aiohttp.WSMsgType.TEXT:
                            command = json.loads(msg.data)
                            if command.get(\"method\") == \"Browser.close\":
                                logger.warning(\"%s: blocked Browser.close on shared browser\", label)
                                if \"id\" in command:
                                    await client_ws.send_str(json.dumps({
                                        \"id\": command[\"id\"],
                                        \"result\": {},
                                    }))
                                continue
                            await cdp_ws.send(msg.data)
"""
if old not in source:
    raise SystemExit("cloakserve CDP forwarding block changed; update guard patch")
path.write_text(source.replace(old, new, 1))