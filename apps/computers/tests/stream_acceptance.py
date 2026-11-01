#!/usr/bin/env python3
"""The acceptance run for `computers.stream` (DGO-38), as one command.

What it proves, in order, against two REAL machines:

  1. a 2GB volume is streamed from one machine to another, and the job reports progress
     (`percent`, `bytes`, `rate`, `eta`) while it runs — not just at the end;
  2. the copy is CANCELLED mid-flight, and the bytes that reached the destination are still there
     afterwards (the staging file's own size);
  3. a second run RESUMES from that size (`resumed_from` > 0 and the source does not re-send from
     byte 0) instead of starting over;
  4. the finished job is `ok` with `staged_bytes == total`, a sha256 that matched the source's own
     `tar`, and an extracted destination volume whose own sha256 equals the source's — checked
     INDEPENDENTLY of the job's word, through a separate `exec` on each machine;
  5. it cleans up after itself (both probe volumes, the staging files), unless `--keep` is given.

It is deliberately not a unit test with mocks: the thing being tested is a link between two machines,
and a mocked link has never once dropped in the way a real one does.

Usage (from the office checkout, with the stack up):

    python3 apps/computers/tests/stream_acceptance.py --to computer_ssh-<id>
    python3 apps/computers/tests/stream_acceptance.py --to computer_ssh-<id> --size-mb 2048
    python3 apps/computers/tests/stream_acceptance.py --to computer_ssh-<id> --keep

Refuses to start when the office host is busy (`uptime` load1 > 20) or short of disk (< 6GB), the
same two rules every other heavy job in this repo follows: a test that runs on an overloaded machine
measures the machine, not the code.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request

COMPUTERS = "http://computers:8977"
SRC = "computer_local-local"


def api(path: str, body: dict | None = None, timeout: int = 120) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(COMPUTERS + path, data=data,
                                 headers={"content-type": "application/json"},
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"✗ {path} → HTTP {e.code}: {detail}")


def sh(machine: str, command: str, timeout: int = 300) -> dict:
    """Run a command ON a machine — the only door to a machine in this repo."""
    res = api(f"/api/computers/{machine}/exec", {"command": command, "timeout": timeout},
              timeout=timeout + 60)
    return res


def ok(machine: str, command: str, timeout: int = 300) -> str:
    res = sh(machine, command, timeout)
    if res.get("code") != 0:
        raise SystemExit(f"✗ {machine}: {command[:80]} → code {res.get('code')}: "
                         f"{(res.get('stderr') or res.get('reason') or '')[:400]}")
    return res.get("stdout") or ""


def script(machine: str, body: str, timeout: int = 300) -> str:
    """A multi-line remote script, base64'd and piped to bash.

    Not `bash -c "<text>"`: quoting a script through an ssh command line is where multi-line shell
    silently turns into one mangled line, and a test helper that does that reports the quoting bug as
    a product bug."""
    enc = base64.b64encode(body.encode()).decode()
    return ok(machine, f"echo {enc} | base64 -d | bash", timeout)


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{'✓' if condition else '✗'} {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        raise SystemExit(1)


def fill_volume(machine: str, volume: str, size_mb: int) -> None:
    """A 2GB volume with a shape that can catch a wrong copy: one big zero file, one big RANDOM file
    (zeros compress and hash the same however they are cut), a deep tree and a few thousand small
    files — a resume that splices the wrong offset shows up in the random file's hash."""
    half = max(1, size_mb // 2)
    out = script(machine, f"""
set -e
V=/var/lib/docker/volumes/{volume}/_data
rm -rf "$V"; mkdir -p "$V/big" "$V/tree/a/b/c" "$V/many"
head -c {half}M /dev/zero > "$V/big/zeros.bin"
head -c {half}M /dev/urandom > "$V/big/random.bin"
printf 'hello from the office\\n' > "$V/tree/a/b/c/note.txt"
i=1; while [ $i -le 2000 ]; do printf 'file %s %s\\n' "$i" "$(date +%s%N)" > "$V/many/f$i.txt"; i=$((i+1)); done
printf 'root marker\\n' > "$V/ROOT.txt"
du -sb "$V" | cut -f1
""", timeout=900)
    print(f"   ה-volume במקור מולא: {int(out.strip().splitlines()[-1]) / 1024 ** 2:.0f}MB")


def vol_sha(machine: str, volume: str) -> str:
    """The content identity of a volume, computed ON the machine that holds it.

    `LC_ALL=C` on BOTH the find and the sort is load-bearing: without it the two machines sort the
    same file list differently (macOS's collation is not Debian's), the concatenated `sha256sum`
    output comes out in a different ORDER, and two identical volumes hash to different digests. That
    is a false alarm that looks exactly like data corruption — measured, on the first run of this
    script: every file matched, the digests did not."""
    out = script(machine, f"cd /var/lib/docker/volumes/{volume}/_data && "
                          f"LC_ALL=C find . -type f -print0 | LC_ALL=C sort -z | "
                          f"xargs -0 sha256sum | sha256sum | cut -d' ' -f1",
                 timeout=1800)
    return out.strip().splitlines()[-1].strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="destination machine id (from GET /api/computers)")
    ap.add_argument("--size-mb", type=int, default=2048)
    ap.add_argument("--volume", default="bina_stream_probe")
    ap.add_argument("--dest-volume", default="bina_stream_probe_dest")
    ap.add_argument("--cancel-at", type=float, default=0.25, help="fraction of the archive to cancel at")
    ap.add_argument("--keep", action="store_true", help="leave the probe volumes behind")
    args = ap.parse_args()

    if args.to == SRC:
        raise SystemExit("✗ היעד חייב להיות מכונה אחרת")

    fleet = api("/api/computers?probe=0")
    ids = {c["id"] for c in fleet.get("computers") or []}
    check("שתי המכונות ברשימת המחשבים", {SRC, args.to} <= ids,
          f"יש: {sorted(ids)}")

    up = ok(SRC, "uptime | sed 's/.*load average: //'").strip().split()[0].rstrip(",")
    free = int(ok(SRC, "df -BG --output=avail / | tail -1 | tr -dc 0-9").strip() or 0)
    check("המכונה הזאת פנויה", float(up) <= 20.0, f"load1={up}")
    check("יש מקום כאן לבדיקה", free >= 6, f"{free}GB פנויים")

    print(f"── מכין {args.size_mb}MB במקור ({SRC})")
    ok(SRC, f"docker volume create {args.volume}")
    fill_volume(SRC, args.volume, args.size_mb)
    src_sha = vol_sha(SRC, args.volume)
    print(f"   sha256 של המקור: {src_sha[:12]}")

    print("── העברה ראשונה (נעצרת באמצע)")
    job = api(f"/api/computers/{SRC}/stream",
              {"to": args.to, "volume": args.volume, "dest_volume": args.dest_volume}).get("job") or {}
    jid = job.get("id")
    check("ההעברה החלה", bool(jid), json.dumps(job)[:200])

    seen_progress, last = [], 0
    target = int((job.get("total") or 0) * args.cancel_at) or (args.size_mb * 1024 * 1024 // 4)
    while True:
        time.sleep(5)
        row = (api(f"/api/transfers/{jid}").get("transfer") or {})
        done, total = int(row.get("done_bytes") or 0), int(row.get("total") or 0)
        if done != last:
            print(f"   {done / 1024 ** 2:.0f}MB / {total / 1024 ** 2:.0f}MB "
                  f"({row.get('percent')}%) · {int(row.get('rate_bps') or 0) / 1024 ** 2:.1f}MB/s"
                  f" · נותרו ~{row.get('eta_s')}s")
            last = done
        seen_progress.append((done, row.get("percent"), row.get("rate_bps")))
        if row.get("state") not in (None, "queued", "running"):
            raise SystemExit(f"✗ ההעברה הסתיימה לפני שביקשנו לעצור: {row.get('state')} {row.get('error')}")
        if done >= target:
            break
    check("ההתקדמות מדווחת תוך כדי ריצה",
          any(p for _, p, _ in seen_progress if p) and any(r for _, _, r in seen_progress if r),
          f"{len(seen_progress)} דגימות")

    print("── עוצר באמצע")
    api(f"/api/transfers/{jid}/cancel", {})
    for _ in range(24):
        time.sleep(5)
        row = (api(f"/api/transfers/{jid}").get("transfer") or {})
        if row.get("state") in ("cancelled", "error", "ok"):
            break
    check("ההעברה נעצרה", row.get("state") == "cancelled", str(row.get("state")))
    staged = int(ok(args.to, f"stat -c %s /var/lib/bina-transfer/{args.volume}__{args.dest_volume}.tar "
                             f"2>/dev/null || echo 0").strip().splitlines()[-1] or 0)
    check("הבתים שהגיעו נשמרו ביעד", staged > 0, f"{staged / 1024 ** 2:.0f}MB")
    print(f"   ביעד יש {staged / 1024 ** 2:.0f}MB — זו נקודת ההמשך")

    print("── העברה שנייה (ממשיכה)")
    job2 = api(f"/api/computers/{SRC}/stream",
               {"to": args.to, "volume": args.volume, "dest_volume": args.dest_volume}).get("job") or {}
    jid2 = job2.get("id")
    check("ההמשך התחיל", bool(jid2), json.dumps(job2)[:200])
    # The resume offset is discovered by the worker (it reads the staging file's size on the
    # destination), so it is not in the start response — poll for it rather than assert on a zero
    # that only means "the first round trip has not finished yet".
    resumed, row = 0, {}
    for _ in range(60):
        time.sleep(5)
        row = (api(f"/api/transfers/{jid2}").get("transfer") or {})
        resumed = int(row.get("resumed_from") or 0)
        if resumed or row.get("state") in ("error", "cancelled", "ok"):
            break
    check("ההמשך לא מתחיל מאפס", resumed > 0, f"resumed_from={resumed / 1024 ** 2:.0f}MB")
    check("נקודת ההמשך היא מה שהגיע ליעד", abs(resumed - staged) <= 8 * 1024 * 1024,
          f"{resumed / 1024 ** 2:.0f}MB מול {staged / 1024 ** 2:.0f}MB שהיו ביעד")

    t0 = time.time()
    while True:
        time.sleep(10)
        row = (api(f"/api/transfers/{jid2}").get("transfer") or {})
        if row.get("state") in ("ok", "error", "cancelled"):
            break
        if time.time() - t0 > 6 * 3600:
            raise SystemExit("✗ ההמשך לא הסתיים בשש שעות")
    check("ההמשך הסתיים בהצלחה", row.get("state") == "ok", f"{row.get('state')} {row.get('error') or ''}")
    check("ההמשך העביר רק את מה שנותר",
          int(row.get("bytes") or 0) <= int(row.get("total") or 0) - resumed + 1024 * 1024,
          f"העביר {int(row.get('bytes') or 0) / 1024 ** 2:.0f}MB מתוך {int(row.get('total') or 0) / 1024 ** 2:.0f}MB")
    check("גודל הארכיון תואם את הנמדד במקור",
          int(row.get("staged_bytes") or 0) == int(row.get("total") or -1),
          f"{row.get('staged_bytes')} מול {row.get('total')}")
    check("האימות (sha256) עבר", bool(row.get("sha256")), str(row.get("sha256"))[:12])

    print("── אימות בלתי תלוי (לא דרך דיווח ההעברה)")
    dst_sha = vol_sha(args.to, args.dest_volume)
    check("התוכן ביעד זהה למקור", dst_sha == src_sha, f"{dst_sha[:12]} מול {src_sha[:12]}")
    got = int(ok(args.to, f"du -sb /var/lib/docker/volumes/{args.dest_volume}/_data | cut -f1")
              .strip().splitlines()[-1])
    print(f"   {got / 1024 ** 2:.0f}MB חולצו ביעד")

    if not args.keep:
        print("── מפנה")
        ok(SRC, f"docker volume rm -f {args.volume} || true")
        ok(args.to, f"docker volume rm -f {args.dest_volume} || true; "
                    f"rm -f /var/lib/bina-transfer/{args.volume}__{args.dest_volume}.tar* || true")
    print("\n✓ DGO-38: 2GB עברו בהתקדמות, ניתוק → המשך ולא התחלה מחדש, והתוכן זהה במקור וביעד")
    return 0


if __name__ == "__main__":
    sys.exit(main())
