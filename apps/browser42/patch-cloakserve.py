#!/usr/bin/env python3
"""patch-cloakserve.py — every change browser42 makes to cloakserve, in one place, at image build time.

cloakserve (CloakBrowser's launcher, plain Python, digest-pinned in Dockerfile.browser) is written for
throwaway fingerprint profiles. browser42 runs ONE persistent profile behind it, the owner's sign-ins,
so a few of its lines are wrong here. Each patch is an exact run of whole lines and its replacement; a
run that is not in the file exactly once fails the build, so a base-image bump that moves a line is
heard and never silently unpatched. Until DGO-1921 these lived in three sed RUNs,
guard-shared-browser.py and two seds that start-browser.sh re-ran at every start.

    python3 patch-cloakserve.py [/usr/local/bin/cloakserve]
"""
import sys
from pathlib import Path

PATCHES = [
    (
        # 2026-09-22: a recreate ran cloakserve's shutdown cleanup and wiped every login.
        "the owner's profile is never deleted when Chrome is stopped",
        "        await asyncio.to_thread(self._safe_rmtree, proc.user_data_dir)\n",
        "        if key not in RESERVED_SEEDS:\n"
        "            await asyncio.to_thread(self._safe_rmtree, proc.user_data_dir)\n",
    ),
    (
        # A launch cancelled while it waits for CDP (a client gone, a shutdown) left its Chrome running
        # and unregistered; the next launch on the same profile then hands off to it and never binds.
        "a launch cut short kills the Chrome it started",
        "            if not await self._wait_for_cdp(port):\n",
        "            try:\n"
        "                ready = await self._wait_for_cdp(port)\n"
        "            except BaseException:\n"
        "                process.kill()\n"
        "                raise\n"
        "            if not ready:\n",
    ),
    (
        # 2026-09-27: three wipes in twenty minutes on a loaded host. A quarantine (moving it aside)
        # replaced the delete, and then 242 quarantined copies and a promote-it-back step in
        # start-browser.sh followed (2026-09-30). The profile simply stays, and says so; the next
        # launch reuses it.
        "…nor deleted or moved aside when a launch misses the CDP wait",
        "                await asyncio.to_thread(self._safe_rmtree, user_data_dir)\n",
        "                if seed_key not in RESERVED_SEEDS:\n"
        "                    await asyncio.to_thread(self._safe_rmtree, user_data_dir)\n"
        "                else:\n"
        '                    logger.error("Chrome did not bind CDP on the persistent profile %s; the profile is kept as it is", user_data_dir)\n',
    ),
    (
        # Upstream drops a profile's launch lock in its cleanup — while the request that is cleaning up
        # still holds it. Any client that arrives during that wake gets a NEW lock and launches a SECOND
        # Chrome on the same profile, which never binds CDP and holds the new lock for the whole launch
        # wait. Measured 2026-11-17 13:32:47: a wake from idle sleep plus one `bbox b42 tab list` → two
        # launches, CDP blocked, the CDP watchdog killed cloakserve, the container restarted (DGO-1921).
        "a profile's launch lock is never dropped while it is held",
        "        self._locks.pop(key, None)\n",
        "",
    ),
    (
        "extensions load: the tab-group bridge (/extension) is one",
        '    "--disable-extensions",\n',
        "",
    ),
    (
        # A Playwright client calls Browser.close in its normal cleanup; on the one shared browser that
        # would end everyone's session.
        "a client's Browser.close is answered, never forwarded",
        "                        if msg.type == aiohttp.WSMsgType.TEXT:\n"
        "                            await cdp_ws.send(msg.data)\n",
        "                        if msg.type == aiohttp.WSMsgType.TEXT:\n"
        "                            command = json.loads(msg.data)\n"
        '                            if command.get("method") == "Browser.close":\n'
        '                                logger.warning("%s: blocked Browser.close on shared browser", label)\n'
        '                                if "id" in command:\n'
        '                                    await client_ws.send_str(json.dumps({"id": command["id"], "result": {}}))\n'
        "                                continue\n"
        "                            await cdp_ws.send(msg.data)\n",
    ),
    (
        # A cold headed Chromium with a real profile took 15-90 s to bind CDP at load 46 (2026-09-30).
        "a launching Chrome gets 180 s to bind CDP, not 10",
        "    async def _wait_for_cdp(port: int, timeout: float = 10.0) -> bool:\n",
        "    async def _wait_for_cdp(port: int, timeout: float = 180.0) -> bool:\n",
    ),
    (
        # start-browser.sh §4a: CDP on loopback, and on browser42's own network through the forwarder.
        "CDP listens where BROWSER42_CDP_HOST says, not on every interface",
        '    host = "0.0.0.0" if in_container else "127.0.0.1"\n',
        '    host = os.environ.get("BROWSER42_CDP_HOST") or ("0.0.0.0" if in_container else "127.0.0.1")\n',
    ),
    (
        # Its health probes ask every 5-10 s, and each answer was a line: ~1,200 an hour of the container's
        # log (2026-11-17). Launches, connects and refusals are logged by cloakserve itself and stay.
        "no access log line per HTTP request",
        "    web.run_app(app, host=host, port=port, print=None)\n",
        "    web.run_app(app, host=host, port=port, print=None, access_log=None)\n",
    ),
]


def patch(source: str) -> str:
    for why, old, new in PATCHES:
        count = source.count("\n" + old)
        if count != 1:
            raise SystemExit(f"cloakserve: the lines for «{why}» are there {count} times, not once — re-derive the patch")
        source = source.replace("\n" + old, "\n" + new, 1)
    compile(source, "cloakserve", "exec")
    return source


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "/usr/local/bin/cloakserve")
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    for why, _, _ in PATCHES:
        print(f"cloakserve patched: {why}")


if __name__ == "__main__":
    main()
