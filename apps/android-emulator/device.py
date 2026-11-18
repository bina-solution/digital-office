#!/usr/bin/env python3
"""device.py — the office's Android device, asked through its door (DGO-1797, package 12). Standard library only:
a CI job in the office (ci-runner's agent), an agent, or `bbox` runs it — none of them starts an emulator itself.

    python3 apps/android-emulator/device.py status
    python3 apps/android-emulator/device.py start [--by WHO]
    python3 apps/android-emulator/device.py wait [--limit S]      # until it runs; 1 when it stopped (why on stderr)
    python3 apps/android-emulator/device.py stop
    python3 apps/android-emulator/device.py put FILE.apk            # into its drop folder, the sha256 compared
    python3 apps/android-emulator/device.py install NAME.apk        # adb's answer; 1 unless it says Success
    python3 apps/android-emulator/device.py remove NAME.apk         # out of the drop folder
    python3 apps/android-emulator/device.py shell ARG...            # adb shell on the device: its output and rc
    python3 apps/android-emulator/device.py screenshot OUT.png

The door is ANDROID_DEVICE_DOOR, else http://android-emulator:8080 (the office's network). A paused device (the
heat) answers 409: the device's verbs wait while it is paused, up to their limit, and never retry at once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DOOR = os.environ.get("ANDROID_DEVICE_DOOR") or "http://android-emulator:8080"
RUNNING, PAUSED, OFF, STOPPING = "running", "paused", "off", "stopping"
INSTALL_WAIT_S = 1860                                # the door's 30 min for adb install, and its answer
SAVE_WAIT_S = 150                                    # the door's 120 s for a stopping device's snapshot, and some


class DeviceError(RuntimeError):
    """The door said no, or the device stopped: the message is what a person reads."""


class NoAnswer(DeviceError):
    """The device did not answer in time (504) — paused mid-call, or adb between answers: a reading not taken."""


class Door:
    def __init__(self, base: str = DOOR, sleep=time.sleep, clock=time.monotonic, say=None):
        self.base, self.sleep, self.clock = base.rstrip("/"), sleep, clock
        self.say = say or (lambda line: print(line, file=sys.stderr, flush=True))
        self.pauses = 0

    def call(self, method: str, path: str, doc=None, data=None, size=None, timeout=60) -> tuple[int, bytes]:
        headers = {}
        if doc is not None:
            data, headers["Content-Type"] = json.dumps(doc).encode(), "application/json"
        if size is not None:
            headers["Content-Length"] = str(size)
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def json(self, method: str, path: str, doc=None, timeout=60) -> tuple[int, dict]:
        code, body = self.call(method, path, doc, timeout=timeout)
        try:
            return code, json.loads(body or b"{}")
        except ValueError:
            return code, {"error": body[:200].decode("utf-8", "replace")}

    def status(self) -> dict:
        code, doc = self.json("GET", "/api/status", timeout=15)
        if code != 200:
            raise DeviceError(f"the door answered {code}: {doc.get('error', '')}")
        return doc

    def start(self, by: str) -> dict:
        code, doc = self.json("POST", "/api/start", {"by": by})
        if code != 202:
            raise DeviceError(f"the door did not start it ({code}): {doc.get('error', '')}")
        return doc

    def stop(self) -> dict:
        code, doc = self.json("POST", "/api/stop")
        if code != 200:
            raise DeviceError(f"the door did not stop it ({code}): {doc.get('error', '')}")
        # a running device saves its quick-boot snapshot before it exits (the door's `stopping`): wait for «off»
        end = self.clock() + SAVE_WAIT_S
        while doc.get("state") == STOPPING and self.clock() < end:
            self.sleep(2)
            doc = self.status()
        if doc.get("state") == STOPPING:
            raise DeviceError(f"the device is still saving its snapshot after {SAVE_WAIT_S} s")
        if doc.get("pid"):                     # «off» with a pid: the stop could not end the emulator (DGO-1817)
            raise DeviceError(f"the emulator (pid {doc['pid']}) did not stop: {doc.get('why', '')}")
        return doc

    def wait(self, limit_s: int = 1800, every_s: int = 5) -> dict:
        """Until the device runs. Its pauses for the heat are counted; it stopping (the 90 °C limit, an exit) or
        the limit passing is a DeviceError that says which."""
        end, was = self.clock() + limit_s, None
        while True:
            st = self.status()
            if st["state"] != was:
                if st["state"] == PAUSED:
                    self.pauses += 1
                self.say(f"device: {st['state']} ({st.get('temp')}°C)")
                was = st["state"]
            if st["state"] == RUNNING:
                return st
            if st["state"] == OFF:
                raise DeviceError(f"the device stopped: {st.get('why') or 'off'}")
            if self.clock() >= end:
                raise DeviceError(f"the device is still {st['state']} after {limit_s} s")
            self.sleep(every_s)

    def device(self, method: str, path: str, doc=None, limit_s: int = 900, timeout=660) -> tuple[int, dict]:
        """A device verb. Not running but on its way — paused for the heat, booting again after a resume, waiting
        for the heat to start — it is waited for (wait() counts the pauses), up to limit_s; off is a DeviceError,
        and an answer that did not come in time (504) a NoAnswer."""
        end = self.clock() + limit_s
        while True:
            code, ans = self.json(method, path, doc, timeout=timeout)
            if code == 409 and ans.get("state") not in (OFF, None) and self.clock() < end:
                self.wait(max(1, int(end - self.clock())))
                continue
            if code == 409:                          # off: its reason (the 90 °C limit, the disk) goes with it
                why = f" — {ans['why']}" if ans.get("why") else ""
                raise DeviceError((ans.get("error") or "the device is not running") + why)
            if code == 504:
                raise NoAnswer(ans.get("error") or "the device did not answer in time")
            return code, ans

    def put(self, path: str) -> dict:
        """The APK into the device's drop folder: asked first (a refused PUT is answered before its body is read,
        so a client still sending would see only a closed connection, never the reason), then sent, and the
        door's sha256 compared with the file's."""
        name, size, digest = os.path.basename(path), os.path.getsize(path), hashlib.sha256()
        code, ans = self.json("GET", f"/api/apks/{urllib.parse.quote(name)}?bytes={size}", timeout=30)
        if code != 200:
            raise DeviceError(f"the door keeps no {name} ({code}): {ans.get('error', '')}")
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        try:
            with open(path, "rb") as f:
                code, body = self.call("PUT", "/api/apks/" + urllib.parse.quote(name), data=f, size=size, timeout=900)
        except OSError as e:
            raise DeviceError(f"the door closed the upload of {name}: {e}") from e
        try:
            ans = json.loads(body or b"{}")
        except ValueError:
            ans = {"error": body[:200].decode("utf-8", "replace")}
        if code != 201:
            raise DeviceError(f"the door kept no APK ({code}): {ans.get('error', '')}")
        if ans.get("sha256") != digest.hexdigest():
            raise DeviceError(f"the door's copy differs: sha256 {ans.get('sha256')} for {digest.hexdigest()}")
        return ans

    def remove(self, name: str) -> bool:
        code, ans = self.json("DELETE", "/api/apks/" + name, timeout=30)
        return code == 200 and bool(ans.get("removed"))

    def install(self, name: str) -> tuple[bool, str]:
        code, ans = self.device("POST", "/api/install", {"apk": name}, timeout=INSTALL_WAIT_S)
        said = ans.get("said") or ans.get("error") or ""
        return code == 200 and "Success" in said, said

    def shell(self, *argv: str, timeout: int = 60) -> tuple[int, str]:
        code, ans = self.device("POST", "/api/shell", {"argv": list(argv), "timeout": timeout}, timeout=timeout + 30)
        if code != 200:
            raise DeviceError(f"shell {argv[0]}: {code} {ans.get('error', '')}")
        return ans["rc"], ans["out"]

    def screenshot(self) -> bytes | None:
        """The screen as PNG — None when the device gave none (paused, between answers): a shot to take again."""
        code, body = self.call("GET", "/api/screenshot", timeout=60)
        return body if code == 200 and body.startswith(b"\x89PNG") else None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="device.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--door", default=DOOR)
    sub = p.add_subparsers(dest="verb", required=True)
    sub.add_parser("status")
    sub.add_parser("start").add_argument("--by", default=os.environ.get("GITHUB_WORKFLOW") or "cli")
    sub.add_parser("wait").add_argument("--limit", type=int, default=1800)
    sub.add_parser("stop")
    sub.add_parser("put").add_argument("apk")
    sub.add_parser("install").add_argument("apk")
    sub.add_parser("remove").add_argument("apk")
    sub.add_parser("shell").add_argument("argv", nargs=argparse.REMAINDER)
    sub.add_parser("screenshot").add_argument("out")
    a = p.parse_args(argv)
    d = Door(a.door)
    try:
        if a.verb == "status":
            print(json.dumps(d.status(), ensure_ascii=False))
        elif a.verb == "start":
            print(json.dumps(d.start(a.by), ensure_ascii=False))
        elif a.verb == "wait":
            print(json.dumps(d.wait(a.limit), ensure_ascii=False))
        elif a.verb == "stop":
            print(json.dumps(d.stop(), ensure_ascii=False))
        elif a.verb == "put":
            print(json.dumps(d.put(a.apk), ensure_ascii=False))
        elif a.verb == "install":
            ok, said = d.install(a.apk)
            print(said)
            return 0 if ok else 1
        elif a.verb == "remove":
            removed = d.remove(a.apk)
            print("removed" if removed else f"{a.apk} was not in the drop folder")
            return 0 if removed else 1
        elif a.verb == "shell":
            if not a.argv:
                p.error("shell needs a command")
            rc, out = d.shell(*a.argv)
            sys.stdout.write(out)
            return rc
        elif a.verb == "screenshot":
            png = d.screenshot()
            if png is None:
                print("device: no screen now (not running, or paused)", file=sys.stderr)
                return 1
            with open(a.out, "wb") as f:
                f.write(png)
    except (DeviceError, OSError) as e:
        print(f"device: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
