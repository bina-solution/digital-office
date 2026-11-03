#!/usr/bin/env bash
# deploy.sh — AUD-C5-001331: the office watch on fpg-vps (severe events → the office notice centre).
# Run as root on fpg-vps from the staged directory:
#
#   DRY=1 bash deploy.sh   # every guard + one read-only look (--check); nothing changed
#   bash deploy.sh         # guards → back up → install → verify → first run → ONE test row → timer on;
#                          # any failure after the backup rolls everything back by itself
#
# Changes on the server (and nothing else): /usr/local/sbin/office-watch, /etc/default/office-watch
# (only if absent — an existing one is the owners' and is kept), /etc/systemd/system/office-watch.{service,timer},
# /usr/local/share/doc/office-watch/README.md, /var/lib/office-watch/ (state). No container, compose file,
# office file or other unit is touched; nothing is restarted. Backup: /root/office-watch-backup-<stamp>/.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
DRY=${DRY:-0}
EXPECT_HOST=${EXPECT_HOST:-srv2085127}
OFFICE=${OFFICE:-fireplace}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BK=/root/office-watch-backup-$STAMP
BIN=/usr/local/sbin/office-watch
CONF=/etc/default/office-watch
UNITS=/etc/systemd/system
DOC=/usr/local/share/doc/office-watch/README.md
STATE_DIR=/var/lib/office-watch
TARGETS=("$BIN" "$CONF" "$UNITS/office-watch.service" "$UNITS/office-watch.timer" "$DOC")
INSTALLING=0

say() { printf '%s\n' "$*"; }
die() { say "REFUSED: $*"; exit 1; }
step() { say ""; say "── $*"; }
on_exit() {
  local rc=$?
  if [ "$rc" -ne 0 ] && [ "$INSTALLING" = 1 ]; then
    say ""; say "FAILED (exit $rc) — rolling back from $BK"
    bash "$HERE/rollback.sh" "$BK" || say "ROLLBACK FAILED — restore by hand from $BK"
  fi
}
trap on_exit EXIT

# ── 1. guards: this machine, this package, the notice centre (read-only) ─────────────────────────
step "guards"
[ "$(id -u)" = 0 ] || die "run as root"
[ "$(hostname)" = "$EXPECT_HOST" ] || die "this is $(hostname), not $EXPECT_HOST (EXPECT_HOST=… to override)"
for t in python3 systemctl systemd-analyze docker curl md5sum install; do
  command -v "$t" >/dev/null || die "$t is missing"
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "python3 >= 3.9 is needed"
(cd "$HERE" && md5sum --quiet -c MANIFEST.md5) || die "a package file differs from MANIFEST.md5 (md5 guard)"
say "   md5 guard: $(wc -l < "$HERE/MANIFEST.md5") files match"
IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "notifications-$OFFICE" 2>/dev/null | awk '{print $1}')
[ -n "$IP" ] || die "notifications-$OFFICE has no address — is the notice centre running?"
CODE=$(curl -s -m 10 -o /dev/null -w '%{http_code}' "http://$IP:8977/api/notifications?limit=1" || true)
[ "$CODE" = 200 ] || die "the notice centre answered «$CODE» to a read-only GET (want 200)"
say "   notice centre notifications-$OFFICE at $IP:8977 answers (GET 200)"
if [ -r /proc/pressure/cpu ]; then say "   PSI available"; else say "   note: no PSI on this kernel — CPU busy % only"; fi
if [ -e "$CONF" ]; then say "   $CONF exists — the owners' settings are kept"; fi
step "one read-only look (--check: posts nothing, writes nothing)"
CHECK_CONF=$CONF; [ -e "$CONF" ] || CHECK_CONF=$HERE/server/office-watch.default
OFFICE_WATCH_CONF=$CHECK_CONF python3 "$HERE/server/office-watch.py" --check
if [ "$DRY" = 1 ]; then say ""; say "DRY=1: every guard passed; nothing was changed."; exit 0; fi

# ── 2. back up what is there now ────────────────────────────────────────────────────────────────
step "backup → $BK"
mkdir -p "$BK"; chmod 700 "$BK"
for t in "${TARGETS[@]}"; do
  if [ -e "$t" ]; then cp -a --parents "$t" "$BK/"; say "   saved $t"; fi
done
if [ -d "$STATE_DIR" ]; then cp -a --parents "$STATE_DIR" "$BK/"; fi
if systemctl is-enabled --quiet office-watch.timer 2>/dev/null; then touch "$BK/TIMER_WAS_ENABLED"; fi
INSTALLING=1

# ── 3. install ──────────────────────────────────────────────────────────────────────────────────
step "install"
install -m 0755 "$HERE/server/office-watch.py" "$BIN"
[ -e "$CONF" ] || install -m 0644 "$HERE/server/office-watch.default" "$CONF"
install -m 0644 "$HERE/server/office-watch.service" "$HERE/server/office-watch.timer" "$UNITS/"
install -D -m 0644 "$HERE/README.md" "$DOC"
systemd-analyze verify "$UNITS/office-watch.service" "$UNITS/office-watch.timer"
systemctl daemon-reload
say "   installed; systemd-analyze verify clean"

# ── 4. the first real run (oneshot: returns when done), then ONE test row ─────────────────────────
step "first run"
T0=$(date +%s)
systemctl start office-watch.service
say "   ran in $(( $(date +%s) - T0 )) s"
[ -s "$STATE_DIR/state.json" ] || die "no state after the first run"
journalctl -u office-watch.service -n 5 --no-pager -o cat 2>/dev/null || true
step "one clearly-marked test row (opened, then closed)"
python3 "$BIN" --test || die "the notice centre did not take the test row"

# ── 5. the timer ────────────────────────────────────────────────────────────────────────────────
step "timer"
systemctl enable --now office-watch.timer
systemctl is-active --quiet office-watch.timer || die "office-watch.timer is not active"
systemctl list-timers office-watch.timer --no-pager | head -2
INSTALLING=0
say ""
say "DONE. The office watch runs every minute. Settings: $CONF. Undo: bash $HERE/rollback.sh $BK"
