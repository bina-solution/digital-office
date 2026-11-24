#!/usr/bin/env bash
# test_guest_memory.sh — guest-memory.sh's pass, against a made-up /proc and /sys (no root, no kernel touched).
#   bash scripts/wsl/test_guest_memory.sh        exit 0 only when every case passes
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="${HERE}/guest-memory.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
pass=0; fail=0
ok() { if eval "$2"; then pass=$((pass + 1)); else fail=$((fail + 1)); printf 'FAIL  %s\n      %s\n' "$1" "$2"; fi; }

# a fresh made-up machine: world NORMAL_ROW [DMA32_ROW] — the rows are the eleven counts of orders 0…10
world() {
  rm -rf "${T:?}/w"; mkdir -p "${T}/w/proc/sys/vm" "${T}/w/proc/sys/kernel" "${T}/w/sys/kernel/mm/transparent_hugepage" \
    "${T}/w/run" "${T}/w/etc/dgo" "${T}/w/office/data/power"
  { printf 'Node 0, zone      DMA      0      0      0      0      0      0      0      9      9      9      9\n'
    printf 'Node 0, zone    DMA32 %s\n' "${2:-0 0 0 0 0 0 0 0 0 0 0}"
    printf 'Node 0, zone   Normal %s\n' "$1"; } > "${T}/w/proc/buddyinfo"
  : > "${T}/w/proc/sys/vm/compact_memory"; : > "${T}/w/proc/sys/vm/drop_caches"
  echo '93.184.216.49-microsoft-standard-WSL2' > "${T}/w/proc/sys/kernel/osrelease"
  echo 'always [madvise] never' > "${T}/w/sys/kernel/mm/transparent_hugepage/enabled"
  printf 'MemTotal:       %s kB\nMemFree:          437000 kB\n' "${MEMTOTAL_KB:-10188800}" > "${T}/w/proc/meminfo"
}
run() {   # run [VAR=value…] — one pass in the made-up machine
  env GM_PROC="${T}/w/proc" GM_SYS="${T}/w/sys" GM_RUN="${T}/w/run" GM_ETC="${T}/w/etc" GM_FAILS="${FAILS:-0}" "$@" \
    bash "${GUARD}" tick > "${T}/out" 2>&1
}
field() { sed -n "s/.*\"$1\":\"\{0,1\}\([^,\"}]*\)\"\{0,1\}[,}].*/\1/p" "${T}/w/run/guest-memory.json"; }
wrote() { [ -s "${T}/w/proc/sys/vm/$1" ]; }

# 1. a healthy guest: nothing is touched, nothing is said
world '9 9 9 9 9 9 9 100 0 0 0'
run; ok "healthy: no compaction" '! wrote compact_memory'
ok "healthy: no cache drop" '! wrote drop_caches'
ok "healthy: ok is true, 100 blocks" '[ "$(field ok)" = true ] && [ "$(field blocks)" = 100 ]'
ok "healthy: a quiet pass prints nothing" '[ ! -s "${T}/out" ]'

# 2. the count: order 8 is two blocks, order 9 four, order 10 eight; DMA's are never counted; DMA32's are
world '0 0 0 0 0 0 0 1 1 1 1' '0 0 0 0 0 0 0 3 0 0 0'
run env DGO_GUEST_BLOCKS_LOW=1 DGO_GUEST_BLOCKS_MIN=1
ok "count: 1+2+4+8 in Normal and 3 in DMA32 = 18, DMA's 135 left out" '[ "$(field blocks)" = 18 ]'
printf 'Node 0, zone  Movable      0      0      0      0      0      0      0     50      0      0      0\n' >> "${T}/w/proc/buddyinfo"
run env DGO_GUEST_BLOCKS_LOW=1 DGO_GUEST_BLOCKS_MIN=1
ok "count: a Movable zone's 50 are not a kernel allocation's: still 18" '[ "$(field blocks)" = 18 ]'

# 2b. a count that cannot be read is «unknown», never «0»: nothing is compacted or dropped on it, and it is said
world '0 0 0 0 0 0 0 0 0 0 0'
printf 'Node 0, zone      DMA      0      0      0      0      0      0      0      9      9      9      9\n' > "${T}/w/proc/buddyinfo"
run; ok "no zone row to count: no compaction, no cache drop" '! wrote compact_memory && ! wrote drop_caches'
ok "…the state says it could not tell (blocks -1, not ok, in words)" \
  '[ "$(field blocks)" = -1 ] && [ "$(field ok)" = false ] && grep -q "gave no zone row" "${T}/w/run/guest-memory.json"'
printf 'garbage\n' > "${T}/w/proc/buddyinfo"
run; ok "a buddyinfo that is not one: the same" '! wrote drop_caches && [ "$(field blocks)" = -1 ]'

# 3. under LOW: compacted, and no more than that while MIN holds
world '9 9 9 9 9 9 9 40 0 0 0'
run; ok "low (40 < 64): compacted" 'wrote compact_memory'
ok "low: the caches are kept (40 >= 16)" '! wrote drop_caches'
ok "low: it says what it did" 'grep -q "compacted" "${T}/out" && [ "$(field ok)" = true ]'

# 4. under MIN: caches dropped and compacted again — once in ten minutes, not every pass
world '9 9 9 9 9 9 9 5 0 0 0'
run; ok "under MIN (5 < 16): caches dropped (3)" '[ "$(cat "${T}/w/proc/sys/vm/drop_caches")" = 3 ]'
ok "under MIN: the state says not ok, and why" '[ "$(field ok)" = false ] && grep -q "free 512 KB block" "${T}/w/run/guest-memory.json"'
: > "${T}/w/proc/sys/vm/drop_caches"; : > "${T}/w/proc/sys/vm/compact_memory"
run; ok "under MIN, a minute later: compacted again" 'wrote compact_memory'
ok "under MIN, a minute later: the caches are NOT dropped again" '! wrote drop_caches'
ok "the first drop wrote its time, and the first wait (600 s)" 'read -r w1 w2 < "${T}/w/run/guest-memory.dropped" && [ "${w1}" -gt 1700000000 ] && [ "${w2}" = 600 ]'
# the wait is over (the drop's time moved back), and the blocks never came back: dropped again — and the NEXT wait
# is doubled, and doubled again, and stops at six hours
printf '%s 600\n' "$(( $(date +%s) - 601 ))" > "${T}/w/run/guest-memory.dropped"
run; ok "the wait over, still under MIN: dropped again" 'wrote drop_caches'
ok "…and the next wait is 1200 s" '[ "$(cut -d" " -f2 "${T}/w/run/guest-memory.dropped")" = 1200 ]'
: > "${T}/w/proc/sys/vm/drop_caches"
printf '%s 1200\n' "$(( $(date +%s) - 700 ))" > "${T}/w/run/guest-memory.dropped"
run; ok "700 s into a 1200 s wait: not dropped" '! wrote drop_caches'
printf '%s 20000\n' "$(( $(date +%s) - 20001 ))" > "${T}/w/run/guest-memory.dropped"
run; ok "the wait never passes six hours" 'wrote drop_caches && [ "$(cut -d" " -f2 "${T}/w/run/guest-memory.dropped")" = 21600 ]'
# the blocks are back: the next drop, if one is ever needed, waits the first wait again — the time of the last one kept
printf '9 9 9 9 9 9 9 100 0 0 0\n' | sed 's/^/Node 0, zone   Normal /' > "${T}/w/proc/buddyinfo"
t_last="$(cut -d" " -f1 "${T}/w/run/guest-memory.dropped")"
run; ok "recovered: the wait is the first wait again, the last drop's time kept" '[ "$(cat "${T}/w/run/guest-memory.dropped")" = "${t_last} 600" ]'
# a guard that cannot write down its drop does not drop: it would have no memory of it, and drop every minute
if [ "$(id -u)" != 0 ]; then
  world '9 9 9 9 9 9 9 5 0 0 0'; chmod 555 "${T}/w/run"
  run; chmod 755 "${T}/w/run"
  ok "the time of the drop cannot be written: no drop" '! wrote drop_caches && wrote compact_memory'
fi

# 4b. three bad passes in a row are counted, and one good pass forgets them
world '9 9 9 9 9 9 9 5 0 0 0'
run; run; run
ok "three passes under MIN: bad_passes is 3" '[ "$(field bad_passes)" = 3 ]'
printf '9 9 9 9 9 9 9 100 0 0 0\n' | sed 's/^/Node 0, zone   Normal /' > "${T}/w/proc/buddyinfo"
run; ok "a good pass: bad_passes is 0 again" '[ "$(field bad_passes)" = 0 ] && [ "$(field ok)" = true ]'

# 5. the kernel failed an allocation: compacted even with blocks to spare, and it is not called ok
world '9 9 9 9 9 9 9 100 0 0 0'
FAILS=3 run; ok "failures with 100 blocks: compacted" 'wrote compact_memory'
ok "failures with 100 blocks: caches kept" '! wrote drop_caches'
ok "failures: not ok, and the count is in the state" '[ "$(field ok)" = false ] && [ "$(field fails_2m)" = 3 ]'
world '9 9 9 9 9 9 9 40 0 0 0'
FAILS=1 run; ok "failures and under LOW: caches dropped" 'wrote drop_caches'
# which failures count: the size a session needs (order 7 and up), read from the kernel's own lines — a small
# atomic failure says nothing about contiguous memory and must not flush the caches at 40 blocks
mkdir -p "${T}/jbin"
cat > "${T}/jbin/journalctl" <<'EOF'
#!/bin/sh
cat <<'LOG'
2026-11-24T09:56:20+0200 host kernel: kworker/0:4: page allocation failure: order:7, mode:0xdc0(GFP_KERNEL|__GFP_ZERO), nodemask=(null)
2026-11-24T09:56:21+0200 host kernel: swapper/0: page allocation failure: order:0, mode:0xa20(GFP_ATOMIC), nodemask=(null)
2026-11-24T09:56:22+0200 host kernel: node: page allocation failure: order:1, mode:0x40cc0(GFP_KERNEL|__GFP_COMP)
2026-11-24T09:56:23+0200 host kernel: kworker/1:2: page allocation failure: order:10, mode:0xdc0(GFP_KERNEL|__GFP_ZERO)
LOG
EOF
chmod +x "${T}/jbin/journalctl"
world '9 9 9 9 9 9 9 100 0 0 0'
run env GM_FAILS= PATH="${T}/jbin:${PATH}"
ok "of four failures in the log, the two of order 7 and 10 are counted" '[ "$(field fails_2m)" = 2 ]'
printf '#!/bin/sh\necho "2026-11-24T09:56:21+0200 host kernel: swapper/0: page allocation failure: order:0, mode:0xa20(GFP_ATOMIC)"\n' > "${T}/jbin/journalctl"
world '9 9 9 9 9 9 9 40 0 0 0'
run env GM_FAILS= PATH="${T}/jbin:${PATH}"
ok "a small failure at 40 blocks: compacted (40 < 64), the caches kept, and it is ok" '! wrote drop_caches && [ "$(field fails_2m)" = 0 ] && [ "$(field ok)" = true ]'

# 6. transparent huge pages: `always` becomes madvise; `keep` leaves it; a made-up value means madvise
world '9 9 9 9 9 9 9 100 0 0 0'; echo '[always] madvise never' > "${T}/w/sys/kernel/mm/transparent_hugepage/enabled"
run; ok "huge pages always → madvise" '[ "$(cat "${T}/w/sys/kernel/mm/transparent_hugepage/enabled")" = madvise ]'
ok "…and it is said" 'grep -q "thp always→madvise" "${T}/out"'
echo '[always] madvise never' > "${T}/w/sys/kernel/mm/transparent_hugepage/enabled"
run env DGO_GUEST_THP=keep
ok "DGO_GUEST_THP=keep: untouched" 'grep -q "^\[always\]" "${T}/w/sys/kernel/mm/transparent_hugepage/enabled"'
run env DGO_GUEST_THP=sometimes
ok "a value that is none of the four: madvise" '[ "$(cat "${T}/w/sys/kernel/mm/transparent_hugepage/enabled")" = madvise ]'

# 7. a typo in a threshold never stops the guard: the default applies
world '9 9 9 9 9 9 9 40 0 0 0'
run env DGO_GUEST_BLOCKS_LOW=abc DGO_GUEST_BLOCKS_MIN=-4
ok "thresholds that are no number: 64 and 16" '[ "$(field low)" = 64 ] && [ "$(field min)" = 16 ] && wrote compact_memory'

# 8. the office's copy: written where its folder is, never created where it is not
world '9 9 9 9 9 9 9 100 0 0 0'
run env GM_MIRROR="${T}/w/office/data/power/guest-memory.json"
ok "the office's copy is the state" 'cmp -s "${T}/w/run/guest-memory.json" "${T}/w/office/data/power/guest-memory.json"'
run env GM_MIRROR="${T}/w/gone/data/power/guest-memory.json"
ok "no folder: no copy, and the pass still ends well" '[ ! -e "${T}/w/gone" ] && [ "$(field ok)" = true ]'
printf '%s\n' "${T}/w/office/data/power/from the file.json" > "${T}/w/etc/dgo/guest-memory.mirror"
run; ok "the mirror is read from install's own file (a name with spaces too)" '[ -s "${T}/w/office/data/power/from the file.json" ]'
# …and where install's file is, it alone decides: a GM_MIRROR left in a settings file (the HP's first install wrote
# one) cannot send the copy anywhere else
printf 'GM_MIRROR=%s\n' "${T}/w/office/data/power/from-old-env.json" > "${T}/w/etc/dgo/guest-memory.env"
run; ok "a GM_MIRROR in the settings file does not override install's" '[ ! -e "${T}/w/office/data/power/from-old-env.json" ]'
: > "${T}/w/etc/dgo/guest-memory.mirror"
run env GM_MIRROR="${T}/w/office/data/power/from-env-2.json"
ok "install's file empty: no mirror, whatever the environment says" '[ ! -e "${T}/w/office/data/power/from-env-2.json" ] && [ ! -e "${T}/w/office/data/power/from-old-env.json" ]'
# the office's own settings are a person's file, read at every pass
printf 'DGO_GUEST_BLOCKS_LOW=200\nDGO_GUEST_THP=keep\n' > "${T}/w/etc/dgo/guest-memory.env"
echo '[always] madvise never' > "${T}/w/sys/kernel/mm/transparent_hugepage/enabled"
run; ok "guest-memory.env is read: LOW 200 (so 100 blocks compact), huge pages kept" \
  '[ "$(field low)" = 200 ] && wrote compact_memory && grep -q "^\[always\]" "${T}/w/sys/kernel/mm/transparent_hugepage/enabled"'

# 9. the state is one JSON object a strict reader takes
ok "the state parses as JSON" 'python3 -c "import json,sys; d=json.load(open(sys.argv[1])); assert set(d)>={\"at\",\"ok\",\"bad_passes\",\"blocks\",\"blocks_before\",\"low\",\"min\",\"fails_2m\",\"thp\",\"acted\",\"why\"}" "${T}/w/run/guest-memory.json"'

# 10. install, as root would run it (id, systemctl and sysctl stood in for; every path made up): the guard on the
#     distro's own disk, the office's copy named, the sysctl file, the unit and its timer — and the timer started.
#     (The first install on the HP died on its first line: a function named `install` hid the command it called.)
world '9 9 9 9 9 9 9 100 0 0 0'
mkdir -p "${T}/bin" "${T}/w/systemd-run"
printf 'DGO_GUEST_THP=keep\n' > "${T}/w/etc/dgo/guest-memory.env"       # a person's setting, there before the install
printf '#!/bin/sh\n[ "$1" = -u ] && echo 0 || exec /usr/bin/id "$@"\n' > "${T}/bin/id"
printf '#!/bin/sh\necho "$*" >> "%s/systemctl.calls"\n' "${T}" > "${T}/bin/systemctl"
printf '#!/bin/sh\nexit 0\n' > "${T}/bin/sysctl"
chmod +x "${T}/bin/id" "${T}/bin/systemctl" "${T}/bin/sysctl"
env PATH="${T}/bin:${PATH}" GM_PROC="${T}/w/proc" GM_SYS="${T}/w/sys" GM_RUN="${T}/w/run" GM_ETC="${T}/w/etc" \
    GM_LIB="${T}/w/lib" GM_SYSTEMD_RUN="${T}/w/systemd-run" bash "${GUARD}" install --mirror "${T}/w/office" > "${T}/out" 2>&1; rc=$?
ok "install: ends well" '[ "${rc}" = 0 ] && grep -q "installed:" "${T}/out"'
ok "install: the guard is copied whole, and runs" 'cmp -s "${GUARD}" "${T}/w/lib/guest-memory.sh" && [ -x "${T}/w/lib/guest-memory.sh" ]'
ok "install: the unit runs the copy, never the office folder's file" 'grep -q "^ExecStart=${T}/w/lib/guest-memory.sh tick$" "${T}/w/etc/systemd/system/dgo-guest-memory.service"'
ok "install: a timer every minute, from 20 s after boot" 'grep -q "^OnUnitActiveSec=60s$" "${T}/w/etc/systemd/system/dgo-guest-memory.timer" && grep -q "^OnBootSec=20s$" "${T}/w/etc/systemd/system/dgo-guest-memory.timer"'
ok "install: a pass that does not end is ended (a oneshot has no limit of its own)" 'grep -q "^TimeoutStartSec=45s$" "${T}/w/etc/systemd/system/dgo-guest-memory.service"'
ok "install: the reserve is a fortieth of this guest's memory (10 GB → 254720 kB), and the compaction" 'grep -q "^vm.min_free_kbytes = 254720$" "${T}/w/etc/sysctl.d/90-dgo-wsl-hvsock.conf" && grep -q "^vm.compaction_proactiveness = 50$" "${T}/w/etc/sysctl.d/90-dgo-wsl-hvsock.conf"'
ok "install: the mirror is named for the passes to come, in its own file" '[ "$(cat "${T}/w/etc/dgo/guest-memory.mirror")" = "${T}/w/office/guest-memory.json" ]'
ok "install: a person's settings file is left exactly as it was" '[ "$(cat "${T}/w/etc/dgo/guest-memory.env")" = "DGO_GUEST_THP=keep" ]'
# the reserve on other guests: never more than 256 MB, never under 64 MB
for pair in "33554432 262144" "4194304 104857" "1048576 65536"; do
  set -- ${pair}; printf 'MemTotal:       %s kB\n' "$1" > "${T}/w/proc/meminfo"
  env PATH="${T}/bin:${PATH}" GM_PROC="${T}/w/proc" GM_SYS="${T}/w/sys" GM_RUN="${T}/w/run" GM_ETC="${T}/w/etc" \
      GM_LIB="${T}/w/lib" GM_SYSTEMD_RUN="${T}/w/systemd-run" bash "${GUARD}" install > /dev/null 2>&1
  ok "the reserve of a $(( $1 / 1048576 )) GB guest is $2 kB" "grep -q '^vm.min_free_kbytes = $2\$' '${T}/w/etc/sysctl.d/90-dgo-wsl-hvsock.conf'"
done
env PATH="${T}/bin:${PATH}" GM_PROC="${T}/w/proc" GM_SYS="${T}/w/sys" GM_RUN="${T}/w/run" GM_ETC="${T}/w/etc" \
    GM_LIB="${T}/w/lib" GM_SYSTEMD_RUN="${T}/w/systemd-run" bash "${GUARD}" install --mirror "${T}/w/office" > "${T}/out" 2>&1
ok "install: the timer is enabled and started, after a reload" 'grep -qx "daemon-reload" "${T}/systemctl.calls" && grep -qx "enable --now dgo-guest-memory.timer" "${T}/systemctl.calls"'
ok "install: the stamp is the installed guard's sha256 and the sha256 of the folder as given" \
  '[ "$(cat "${T}/w/etc/dgo/guest-memory.stamp")" = "$(sha256sum "${GUARD}" | cut -c1-64) $(printf "%s" "${T}/w/office" | sha256sum | cut -c1-64)" ]'
# the office's folder as Windows names it: turned by the guest's own wslpath (stood in for here), kept as given in the stamp
printf '#!/bin/sh\n[ "$1" = -a ] && [ "$2" = "C:\\\\Users\\\\me\\\\DGO" ] && echo "%s/w/office" || exit 1\n' "${T}" > "${T}/bin/wslpath"; chmod +x "${T}/bin/wslpath"
env PATH="${T}/bin:${PATH}" GM_PROC="${T}/w/proc" GM_SYS="${T}/w/sys" GM_RUN="${T}/w/run" GM_ETC="${T}/w/etc" \
    GM_LIB="${T}/w/lib" GM_SYSTEMD_RUN="${T}/w/systemd-run" bash "${GUARD}" install --mirror 'C:\Users\me\DGO' > "${T}/out" 2>&1; rc=$?
ok "install --mirror C:\\…: the copy goes to the guest's path of it" '[ "${rc}" = 0 ] && [ "$(cat "${T}/w/etc/dgo/guest-memory.mirror")" = "${T}/w/office/guest-memory.json" ]'
# …and that installed guard's next pass really writes there (the mirror file is what the timer's pass reads)
env GM_PROC="${T}/w/proc" GM_SYS="${T}/w/sys" GM_RUN="${T}/w/run" GM_ETC="${T}/w/etc" GM_FAILS=0 bash "${T}/w/lib/guest-memory.sh" tick > "${T}/out" 2>&1
ok "the installed copy's pass writes the mirror" 'cmp -s "${T}/w/run/guest-memory.json" "${T}/w/office/guest-memory.json"'
ok "…and the stamp is of the name Windows gave, not of the guest's path" \
  'grep -q " $(printf "%s" "C:\\Users\\me\\DGO" | sha256sum | cut -c1-64)$" "${T}/w/etc/dgo/guest-memory.stamp"'
env PATH="${T}/bin:${PATH}" GM_PROC="${T}/w/proc" GM_ETC="${T}/w/etc" GM_LIB="${T}/w/lib" GM_SYSTEMD_RUN="${T}/w/systemd-run" \
    bash "${GUARD}" install --mirror 'D:\nowhere' > "${T}/out" 2>&1; rc=$?
ok "a Windows folder the guest cannot name: refused, in words" '[ "${rc}" = 1 ] && grep -q "cannot be turned into a path" "${T}/out"'
env PATH="${T}/bin:${PATH}" GM_PROC="${T}/w/proc" GM_ETC="${T}/w/etc" GM_LIB="${T}/w/lib" GM_SYSTEMD_RUN="${T}/w/systemd-run" \
    bash "${GUARD}" install > "${T}/out" 2>&1; rc=$?
ok "an install with no mirror: the earlier one's folder is not kept" '[ "${rc}" = 0 ] && [ ! -s "${T}/w/etc/dgo/guest-memory.mirror" ]'
env PATH="${T}/bin:${PATH}" GM_PROC="${T}/w/proc" GM_ETC="${T}/w/etc" GM_LIB="${T}/w/lib" GM_SYSTEMD_RUN="${T}/w/systemd-run" \
    bash "${GUARD}" install --mirror > "${T}/out" 2>&1; rc=$?
ok "--mirror with no folder: refused, in words" '[ "${rc}" = 1 ] && grep -q "names a folder" "${T}/out"'
env PATH="${T}/bin:${PATH}" GM_PROC="${T}/w/proc" GM_ETC="${T}/w/etc" GM_LIB="${T}/w/lib" GM_SYSTEMD_RUN="${T}/w/none" \
    bash "${GUARD}" install > "${T}/out" 2>&1; rc=$?
ok "install with no systemd in the guest: refused, in words" '[ "${rc}" = 1 ] && grep -q "runs no systemd" "${T}/out"'
echo 'Linux 6.8.0-generic' > "${T}/w/proc/sys/kernel/osrelease"
env PATH="${T}/bin:${PATH}" GM_PROC="${T}/w/proc" GM_ETC="${T}/w/etc" GM_LIB="${T}/w/lib2" GM_SYSTEMD_RUN="${T}/w/systemd-run" \
    bash "${GUARD}" install > "${T}/out" 2>&1; rc=$?
ok "install on a machine that is no WSL guest: refused, nothing copied" '[ "${rc}" = 1 ] && grep -q "not a WSL guest" "${T}/out" && [ ! -e "${T}/w/lib2" ]'

# 11. install is root's, and says so; with no verb it prints its usage and changes nothing
if [ "$(id -u)" != 0 ]; then
  bash "${GUARD}" install > "${T}/out" 2>&1; rc=$?
  ok "install as an ordinary user: refused, in words" '[ "${rc}" = 1 ] && grep -q "runs as root" "${T}/out"'
fi
bash "${GUARD}" > "${T}/out" 2>&1; rc=$?
ok "no verb: usage, exit 2" '[ "${rc}" = 2 ] && grep -q "guest-memory.sh tick" "${T}/out"'

printf 'guest-memory: %d passed, %d failed\n' "${pass}" "${fail}"
[ "${fail}" = 0 ]
