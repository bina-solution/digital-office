#!/usr/bin/env python3
"""check.py — an APK checked on the office's Android device, as a phone would get it (DGO-1797, package 12).

What android-install-check.yml did with an emulator of its own on the runner's host (DGO-1090, DGO-1328,
DGO-1089), asked of the office's device through its door instead — so nothing starts an emulator outside the
office, and its heat rule (server/governor.py) is the one rule:

    python3 apps/android-emulator/check.py --apk dgo.apk --out DIR [--status-screen] [--machine]

  1. the device running (started only if it was off — and then stopped at the end; one the owner uses stays on);
     Android's version, its ABIs, whether it offers AVF, and /data
  2. the app removed, the APK put in the device's drop folder (sha256 compared) and installed: adb's answer and
     the installer's log lines — WHY an install fails, which a phone's installer never says
  3. the app opened, its first 45 s of log, and it still running
  4. --status-screen: «מצב» opened by its dgo://status link, a screenshot and the screen's own text; it must say
     the office, its base, «מכולות» and the way in, and none of the old screen's words
  5. --machine: the app's first open followed until its QEMU has run 20 minutes (150 with no QEMU fails), a
     reading each minute and a screenshot every 5

The files are DIR/check-<run>-*.png|xml (the workflow attaches them to the release). Exit 0 when every asked part
held; 1 with an «::error::» line that says which did not.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import xml.etree.ElementTree as et

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from device import DOOR, OFF, PAUSED, DeviceError, Door, NoAnswer  # noqa: E402

PKG = "il.co.digitaloffice.app"
INSTALLER = "PackageManager|PackageInstaller|INSTALL_|NativeLibraryHelper|ApkSignatureVerifier|PackageParser"
APP_LINES = r"il\.co\.digitaloffice|AndroidRuntime|FATAL|DEBUG"
STATUS_SAYS = ("הלשכה הדיגיטלית", "הבסיס", "מכולות", "פתיחת הלשכה")
STATUS_OLD = ("מנוע:", "המכונה של הלשכה", "✗")
BOOT_LIMIT_S = 1800              # a boot on one core under the heat rule runs at about half speed
FIRST_S = 45
MACHINE_DATA_GB = 12             # what the app asks before it fetches (Guest.java: 2 GB + 10 GB)
MACHINE_DONE_MIN, MACHINE_LIMIT_MIN, SHOT_EVERY_S = 20, 150, 300
PAUSED_LIMIT_S = 1800            # one pause for the heat longer than this ends the follow, and says so


class Failed(Exception):
    """One asked part did not hold: the message is the «::error::» line."""


def screen_texts(xml: str) -> list[str]:
    try:
        return [n.get("text", "") for n in et.fromstring(xml).iter("node") if n.get("text")]
    except et.ParseError:
        return []


def status_verdict(texts: list[str]) -> str | None:
    said = " ".join(texts)
    missing = [w for w in STATUS_SAYS if w not in said]
    old = [w for w in STATUS_OLD if w in said]
    return (f"the status screen does not say {missing}" if missing
            else f"the status screen still says {old}" if old else None)


def net_rx_mb(dev: str) -> int:
    """/proc/net/dev's received bytes over every interface but lo, in MB."""
    total = 0
    for line in dev.splitlines():
        name, _, rest = line.partition(":")
        if rest and name.strip() != "lo" and rest.split():
            try:
                total += int(rest.split()[0])
            except ValueError:
                continue
    return total // 1048576


def df_column_gb(df: str, col: int) -> float | None:
    """`df -k`'s second line, one column, in GB — None when it is not there."""
    rows = [r.split() for r in df.splitlines() if r.strip()]
    try:
        return int(rows[1][col]) / 1048576
    except (IndexError, ValueError):
        return None


class Check:
    def __init__(self, door, out: str, run: str, say=print, sleep=time.sleep, clock=time.monotonic):
        self.door, self.out, self.run, self.say, self.sleep, self.clock = door, out, run, say, sleep, clock
        self.started = False

    def sh(self, cmd: str, timeout: int = 60) -> str:
        return self.door.shell(cmd, timeout=timeout)[1].replace("\r", "").strip()

    def reading(self, cmd: str) -> str | None:
        """One of the machine's readings: None when the device did not answer in time — not a fact about the app."""
        try:
            return self.sh(cmd, timeout=30)
        except NoAnswer:
            return None

    def mark(self, name: str, text: str = ""):
        """What the cleanup (--cleanup, the workflow's always() step) must undo if this run is killed."""
        with open(os.path.join(self.out, f".{name}"), "w", encoding="utf-8") as f:
            f.write(text)

    def path(self, name: str) -> str:
        return os.path.join(self.out, f"check-{self.run}-{name}")

    def shot(self, name: str) -> bool:
        png = self.door.screenshot()
        if not png:
            return False
        with open(self.path(name), "wb") as f:
            f.write(png)
        return True

    def boot(self, by: str):
        st = self.door.status()
        if st["state"] == OFF:
            self.door.start(by)
            self.started = True
            self.mark("started")
        else:
            self.say(f"::warning::the device is already {st['state']}, asked by {st.get('asked_by') or '?'}: "
                     f"the check uses it as it is and leaves it on — the app is installed over, not first")
        self.door.wait(BOOT_LIMIT_S)
        self.say(f"booted: Android {self.sh('getprop ro.build.version.release')}, "
                 f"ABIs {self.sh('getprop ro.product.cpu.abilist')}")
        # DGO-1723 P3: does this emulator give an app AVF (a VM on the phone's own hypervisor), or only QEMU's?
        self.say(f"AVF here: feature {self.sh('pm has-feature android.software.virtualization_framework')}, "
                 f"vm.supported={self.sh('getprop ro.boot.hypervisor.vm.supported')}, "
                 f"protected_vm.supported={self.sh('getprop ro.boot.hypervisor.protected_vm.supported')}, "
                 f"/dev/kvm: {self.sh('ls -l /dev/kvm 2>&1')}")
        self.say(self.sh("df -h /data | tail -1"))

    def install(self, apk: str):
        name = os.path.basename(apk)
        # the office's device keeps its data between checks: removed first, so this is a phone's FIRST install —
        # only on a device this check started; one someone else runs keeps what is on it
        if self.started:
            self.sh(f"pm uninstall {PKG} >/dev/null 2>&1; true")
        self.sh("logcat -c")
        self.mark("put", name)
        put = self.door.put(apk)
        self.say(f"in the device's drop folder: {name}, {put['bytes']} bytes, sha256 {put['sha256']}")
        ok, said = self.door.install(name)
        self.say(said)
        self.say("--- the installer's log")
        self.say(self.sh(f"logcat -d | grep -E '{INSTALLER}' | tail -60"))
        if not ok:
            raise Failed(f"adb install refused {name}: {said.splitlines()[-1] if said else 'no answer'}")

    def first_open(self):
        self.sh("logcat -c")
        self.sh(f"monkey -p {PKG} -c android.intent.category.LAUNCHER 1")
        self.sleep(FIRST_S)
        self.say(f"--- the app's first {FIRST_S} s")
        self.say(self.sh(f"logcat -d | grep -E '{APP_LINES}' | tail -80"))
        if not self.sh(f"pidof {PKG}"):
            raise Failed(f"the app is not running {FIRST_S} s after its start")
        self.say("the app is running")

    def status_screen(self):
        self.sh(f"am start -W -a android.intent.action.VIEW -d dgo://status {PKG}", timeout=60)
        self.sleep(8)
        if not self.shot("status.png"):
            self.say("::warning::the status screen gave no screenshot")
        xml = self.sh("uiautomator dump /sdcard/status.xml >/dev/null && cat /sdcard/status.xml")
        with open(self.path("status.xml"), "w", encoding="utf-8") as f:
            f.write(xml)
        texts = screen_texts(xml)
        self.say("\n".join(texts))
        wrong = status_verdict(texts) if texts else "the status screen's text was not read"
        if wrong:
            raise Failed(wrong)

    def qemu(self) -> int | None:
        """The app's own QEMU processes (EngineService's libqemu-system-aarch64.so), one per line of ps — its name
        and its arguments both carry the path; None when ps said nothing or did not answer."""
        out = self.reading("ps -A -o NAME,ARGS")
        return sum("libqemu-system-aarch64" in line for line in out.splitlines()) if out else None

    def machine(self):
        try:
            self.follow()
        finally:
            # never in place of the reason it ended: a device the heat stopped has no lines to give
            try:
                last = self.reading(f"logcat -d | grep -E '{APP_LINES}' | tail -40")
            except (DeviceError, OSError):                  # the door gone too (URLError, a reset)
                last = None
            self.say("--- the app's last lines")
            self.say(last or "(none read)")

    def follow(self):
        if not self.started:
            raise Failed("the machine is a FIRST open's: a device someone else runs is not wiped for it — "
                         "stop it (./bbox android-emulator stop) and run the check again")
        free = df_column_gb(self.sh("df -k /data"), 3)
        if free is not None and free < MACHINE_DATA_GB:
            raise Failed(f"/data has {free:.1f} GB free and the app asks {MACHINE_DATA_GB} before it fetches: give "
                         f"the device ANDROID_EMULATOR_PARTITION_MB=20480 in the office's .env")
        start, seen, gone, last_shot, paused_since = self.clock(), None, 0, None, None
        while True:
            m = int((self.clock() - start) // 60)
            st = self.door.status()
            if st["state"] == OFF:
                raise Failed(f"the device stopped at {m} min: {st.get('why') or 'off'}")
            if st["state"] == PAUSED:             # paused for the heat: nothing it answers now is about the app
                if paused_since is None:
                    paused_since = self.clock()
                    self.say(f"[{m} min] paused for the heat ({st.get('temp')}°C): waiting")
                elif self.clock() - paused_since >= PAUSED_LIMIT_S:
                    raise Failed(f"the device has been paused for the heat {PAUSED_LIMIT_S // 60} min "
                                 f"({st.get('temp')}°C): the machine is not followed past it")
                self.sleep(10)
                continue
            paused_since = None
            q = self.qemu()
            used = df_column_gb(self.reading("df -k /data") or "", 2)
            dev = self.reading("cat /proc/net/dev")
            self.say(f"[{m} min] received {'?' if dev is None else net_rx_mb(dev)} MB, /data used "
                     f"{'?' if used is None else f'{used:.1f}'} GB, the app's QEMU {'unread' if q is None else q}")
            if last_shot is None or self.clock() - last_shot >= SHOT_EVERY_S:
                if self.shot(f"{m:03d}min.png"):
                    last_shot = self.clock()
            if self.reading(f"pidof {PKG}") == "":    # no answer in time is no word on the app
                self.shot(f"{m:03d}min.png")
                raise Failed(f"the app is gone at {m} min")
            if q and seen is None:
                seen = m
                self.say(f"QEMU started at {m} min: the machine is fetched, checked and unpacked")
            gone = gone + 1 if q == 0 else 0 if q else gone   # ended: no QEMU in two answers in a row
            if seen is not None and gone >= 2:
                self.shot(f"{m:03d}min.png")
                raise Failed(f"the app's QEMU ended at {m} min, {m - seen} min after it started")
            if seen is not None and m - seen >= MACHINE_DONE_MIN:
                self.shot(f"{m:03d}min.png")
                return
            if seen is None and m >= MACHINE_LIMIT_MIN:
                self.shot(f"{m:03d}min.png")
                raise Failed(f"no QEMU after {MACHINE_LIMIT_MIN} min")
            self.sleep(60)

    def run_all(self, apk: str, by: str, status_screen: bool, machine: bool) -> int:
        rc = 0
        try:
            self.boot(by)
            self.install(apk)
            self.first_open()
            if status_screen:
                self.status_screen()
            if machine:
                self.machine()
        except (Failed, DeviceError, OSError) as e:
            self.say(f"::error::{e}")
            rc = 1
        finally:
            self.say(f"heat: {getattr(self.door, 'pauses', 0)} pause(s) while it was asked")
            undo(self.door, self.out, self.say)
        return rc


def undo(door, out: str, say) -> None:
    """What a check leaves must not stay: the APK it put removed, the device stopped if it started it. Read from
    its marks, so the workflow's always() step (--cleanup) does it too when the check itself was killed."""
    def marked(name):
        p = os.path.join(out, f".{name}")
        if not os.path.exists(p):
            return None, p
        with open(p, encoding="utf-8") as f:
            return f.read().strip(), p
    # a mark goes only once its act is done: a failed one stays for the next --cleanup, and says so
    apk, p = marked("put")
    if apk:
        try:
            if door.remove(apk):
                os.remove(p)
            else:
                say(f"::warning::{apk} was not removed from the device's drop folder (the door kept it)")
        except (DeviceError, OSError) as e:
            say(f"::warning::{apk} stays in the device's drop folder: {e}")
    started, p = marked("started")
    if started is not None:
        try:
            door.stop()
            os.remove(p)
            say("the device stopped (this check started it)")
        except (DeviceError, OSError) as e:
            say(f"::warning::the device was not stopped: {e}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="check.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--apk")
    p.add_argument("--out", required=True)
    p.add_argument("--cleanup", action="store_true", help="only undo what a killed check left (its marks in --out)")
    p.add_argument("--status-screen", action="store_true")
    p.add_argument("--machine", action="store_true")
    p.add_argument("--by", default=f"install-check {os.environ.get('GITHUB_RUN_ID') or 'local'}")
    p.add_argument("--run", default=os.environ.get("GITHUB_RUN_ID") or "local")
    p.add_argument("--door", default=DOOR)
    a = p.parse_args(argv)
    say = lambda s: print(s, flush=True)  # noqa: E731
    if a.cleanup:
        if os.path.isdir(a.out):
            undo(Door(a.door), a.out, say)
        return 0
    if not a.apk:
        p.error("--apk is needed (or --cleanup)")
    os.makedirs(a.out, exist_ok=True)
    return Check(Door(a.door), a.out, a.run, say=say).run_all(a.apk, a.by, a.status_screen, a.machine)


if __name__ == "__main__":
    raise SystemExit(main())
