#!/usr/bin/env bash
# rollback.sh [backup-dir] — undo deploy.sh (AUD-C5-001331): stop + disable the timer, put back what was
# there before (from /root/office-watch-backup-<stamp>/), remove what was not. Rows already told to the
# notice centre stay (they are history; the deploy's test row is an info row).
set -uo pipefail
BK=${1:-$(ls -d /root/office-watch-backup-* 2>/dev/null | sort | tail -1)}
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
{ [ -n "$BK" ] && [ -d "$BK" ]; } || { echo "no backup directory (give it as the first argument)"; exit 1; }
systemctl disable --now office-watch.timer 2>/dev/null || true
systemctl stop office-watch.service 2>/dev/null || true
for t in /usr/local/sbin/office-watch /etc/default/office-watch /etc/systemd/system/office-watch.service \
         /etc/systemd/system/office-watch.timer /usr/local/share/doc/office-watch/README.md; do
  if [ -e "$BK$t" ]; then
    cp -a "$BK$t" "$t" && echo "restored $t"
  elif [ -e "$t" ]; then
    rm -f "$t" && echo "removed $t"
  fi
done
rmdir /usr/local/share/doc/office-watch 2>/dev/null || true
rm -rf /var/lib/office-watch
if [ -d "$BK/var/lib/office-watch" ]; then
  cp -a "$BK/var/lib/office-watch" /var/lib/office-watch && echo "restored /var/lib/office-watch"
fi
systemctl daemon-reload
if [ -f "$BK/TIMER_WAS_ENABLED" ] && [ -e /etc/systemd/system/office-watch.timer ]; then
  systemctl enable --now office-watch.timer
fi
echo "rolled back from $BK"
