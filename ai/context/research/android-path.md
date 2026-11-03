# DGO on Android — what is realistic in 2026 (research note, 2026-10-14)

**Verdict:** an Android "office" is **layer 0 only** — a pocket console (identity, office link, notifications,
console UI) that *links to* a real office. Layers 1-3 (Docker) cannot run on an unrooted phone, and Android will
not let any app be a 24/7 server others depend on.

## 0. What our binary already is (measured here, Go 1.22.3)

`GOOS=android GOARCH=arm64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w"` of `packaging/dgo` →
**ET_DYN (PIE), `PT_INTERP=/system/bin/linker64`, every `LOAD` segment `p_align=0x10000`, 2.75 MB.** The Go arm64
linker defaults `FlagRound` to 64 KB for ELF, so it already passes Play's 16 KB-page check. The `GOOS=linux`
static build (2.49 MB, same alignment) runs in Termux unchanged — the Termux path needs no Android artifact.
(Parser: `scratchpad/research/elf_phdrs.py`.)

Two **stdlib blockers** need Go code before any Android binary is "stable":
- **DNS** — `net/conf.go`: "DNS requests don't work on Android, so prefer the cgo resolver"; with `CGO_ENABLED=0`
  the Go resolver is forced and Android skips `/etc/resolv.conf` → hostname lookups fail (golang/go#8877, open
  since 2014). Fix: a `net.Resolver` whose `Dial` targets a DNS we know (the office link's), or IPs over the link.
- **Interfaces** — Android 11 denies netlink `RTM_GETLINK` to apps targeting API 30+ →
  `net.Interfaces()/InterfaceAddrs()` fail with `netlinkrib: permission denied` (golang/go#40569, 2020). Drop-in:
  `github.com/wlynxg/anet`. Termux's F-Droid build (targetSdk 28) is spared; any modern APK is not. Syncthing-Fork
  also passes `FALLBACK_NET_GATEWAY_IPV4` to its Go process for "an Android 14+ restriction".

## 1. A Go server without root

**Termux (F-Droid/GitHub build)** keeps targetSdk 28 on purpose: Android 10's W^X rule says "Untrusted apps that
target Android 10 cannot invoke execve() directly on files within the app's home directory". The **Play build**
(relaunched 2024-06-07, Android 11+, current targetSdk) is a separate codebase that runs packages through
termux-exec's `LD_PRELOAD` interceptor as `/system/bin/linker64 /abs/path` (Go packages fixed for that mode
2026-02-07); Termux:API is still missing there (issue #29 open, last comment 2026-09-30). Never mix sources
(different signing keys).

Keeping it alive: `termux-wake-lock` (partial wake lock + notification), a Termux:Boot script (`termux-wake-lock`
then `sv up`), battery → *Unrestricted*. What remains: Doze cuts network/CPU outside maintenance windows; the
**Android 12+ phantom-process killer** kills child processes beyond **32 system-wide** or on "excessive CPU"
(ADB: `device_config put activity_manager max_phantom_processes 2147483647` + `settings put global
settings_enable_monitor_phantom_procs false`; Android 14+ has a Developer-options toggle); on **Android 15** users
report kills even with wake lock + Unrestricted (termux-app #5150, open). ADB/Shizuku buys only that toggle.

**Wrapper APK** — the Go ELF ships as `lib/arm64-v8a/libdgo.so` and is exec'ed from `nativeLibraryDir` with
`ProcessBuilder` (Syncthing's `libsyncthingnative.so … serve --no-browser`); nothing is exec'ed from the data dir.
`gomobile bind` (AAR, cgo+NDK, min API 16/NDK 28 → 21) is the in-process route Tailscale took in May 2024 — only
worth it for the VPN FD hand-off. Background rules: Android 14+ must declare a **foreground-service type**;
`dataSync` is capped at **6 h per 24 h** and cannot start from `BOOT_COMPLETED` on API 35+; `specialUse` is
"reviewed when you submit your app in Google Play Console"; **`systemExempted` is allowed for VPN apps configured
under Settings › Network & Internet › VPN**; `connectedDevice` needs a manifest permission such as
`CHANGE_WIFI_MULTICAST_STATE`. **Play policy**: an app "may not modify, replace, or update itself using any method
other than Google Play's update mechanism" and "may not download executable code (such as dex, JAR, .so files)
from a source other than Google Play" → `dgo-install`'s signed-manifest self-update is **forbidden inside a Play
APK**; the binary updates with the APK (Syncthing: `STNOUPGRADE=1`).

## 2. Networking

- **WireGuard without root**: yes, inside an app via `VpnService` — the official client "opportunistically uses
  the kernel implementation, and falls back to using the non-root userspace implementation" (wireguard-go);
  `com.wireguard.android:tunnel` is on Maven Central; one active VPN per device. Its `libwg-go.so` was flagged
  UNALIGNED for 16 KB in Aug 2025 (cgo needs `-Wl,-z,max-page-size=16384`; pure Go does not). **Termux has no
  `/dev/net/tun`** → no tunnel; only an in-process netstack works (Tailscale's `--tun=userspace-networking
  --socks5-server=localhost:1055`; TailSocks does it via tsnet with no VpnService). In Termux, dgo must *be* the
  netstack: the link reaches dgo's own sockets, nothing system-wide.
- **Ports**: anything ≥1024 binds without root (Termux sshd: 8022; Nextcloud-on-Termux: 8080/2080);
  `http://localhost:PORT` works in the phone's browser; LAN peers reach the phone unless the AP isolates clients.
- **mDNS**: `NsdManager` (DNS-SD) is the API; on Android ≤12 and 13-without-T-ext-7 an app must hold a
  `WifiManager.MulticastLock` to receive (Syncthing-Fork does, around its Go process); API 37 adds
  `ACCESS_LOCAL_NETWORK`. A Go process in Termux cannot take the lock → discover offices over the link, not multicast.

## 3. Docker — no

`dockerd` needs namespaces, cgroups and overlay mounts; Android grants none to an app (SELinux). Termux's `docker`
lives in the **root-repo** (pinned 20.10.12 since 2021, usually plus a custom kernel). Rootless substitutes are not
Docker: `proot-distro` (ptrace chroot, slow), `udocker` (works with DNS fixes, proot speed), QEMU ("too slow … not
usable"). **Confirmed: Android office = layer 0 only**; n8n/Plane/Postgres stay where Docker is.

## 4. Distribution (2026-10-14)

- **Play**: target **API 36 since 2026-08-31** (extension to 2026-11-01); existing apps need ≥35 to stay visible;
  FGS types declared in Play Console; **16 KB: "Starting February 1, 2027, if your app updates don't support 16 KB
  … you won't be able to release these updates"** (page updated 2026-09-16; slid from Nov 2025 → May 2026 →
  Feb 2027); 200 MB base module (AAB; legacy APK 100 MB); AAB + Play App Signing required since Aug 2021.
- **Developer verification**: Aug 2026 "limited distribution accounts and power user advanced flow launch";
  **2026-09-30 protections began in Brazil, Indonesia, Singapore, Thailand** (certified devices, Android 7+);
  global 2027; hobbyists may share with **up to 20 devices** without ID/fee; **ADB exempt**. A sideloaded APK from
  an unverified developer will need the advanced flow or `adb install`.
- **F-Droid**: builds from source under its own key (Tailscale: "F-Droid builds are not released, updated, or
  verified by the Tailscale team"); F-Droid's open letter (2026-02-24): "we unequivocally advise against signing up".

## 5. Precedents

- **Tailscale Android** — Go core via `gomobile bind`, Kotlin UI, `VpnService`; Play, Amazon, own APKs, F-Droid.
- **Syncthing-Android** — official app discontinued (announced Oct 2024, last release Dec 2024; Play delisted over
  "all files access"); Catfriend1 fork lives on F-Droid/GitHub: Go binary in `jniLibs`, `ProcessBuilder`,
  `STHOMEDIR/STNOUPGRADE=1/GOGC`, restart on exit 3, no self-update — **the shape a dgo wrapper should copy.**
- **WireGuard Android** — kernel if rooted, else wireguard-go userspace; `tunnel` lib on Maven Central.
- **Termux servers / Nextcloud** — Nextcloud ships only a client on Android; server-on-Termux reports (unrooted
  Android 9 LAMP in proot; PHP 8.5 + MariaDB repo, 2026) all say "works, not for production".

## Recommendation

**Promise**: "DGO in your pocket — identity, office link, notifications, console — linked to an office that runs
somewhere real." **Not**: containers on the phone, port 80/443, system-wide VPN from Termux, uptime, self-updating
binaries on Play. **MVP (days)**: Termux script — `curl` the existing **linux/arm64 static** `dgo` into
`$PREFIX/bin`, Termux:Boot (`termux-wake-lock; sv up dgo`), console on `localhost:8080`, link in netstack mode;
plus the resolver and `anet` fixes. **Phase 2 (weeks)**: Kotlin wrapper APK, `libdgo.so` from `jniLibs`, FGS
(`systemExempted` once the VPN is configured, else `specialUse`), `VpnService` via `com.wireguard.android:tunnel`;
F-Droid + direct APK first, Play last. **Blockers**: (1) Android's process-killing regime — the phone is a client
that is *sometimes* up; (2) no Docker → no layers 1-3, and until the DNS/netlink fixes land the stdlib-only binary
cannot resolve a name or list its interfaces on a modern Android.

## The native core, decided (2026-11-01, DGO-1090)

The owner wants the whole office on the phone, and the console the moment the app opens. The app, since
DGO-1071, boots an emulated arm64 guest (QEMU TCG, 10–20× slower) and every service as a container in it; the
first start took hours. The decision splits the office the way core-native-plan.md does: **what must exist
before a container can is native; the containers are apps, started on demand.** On the phone:

- **Native, from `nativeLibraryDir`, two processes** (the phantom-process killer counts children; QEMU is a third
  only when a container app runs): `libdgo.so` running the edge, the console's server and the control plane in
  ONE process, and `libforward-auth.so` (identity; first-run setup makes the owner — setup.go). The edge
  (`dgo be-child edge`, packaging/dgo/internal/edge) routes by host and gates through forward-auth exactly as
  traefik does, so forward-auth, the console and every app see what they see behind traefik.
- **No port that believes its caller.** Loopback is shared by every app on a phone, so what trusts the hop
  in front of it — the console believes identity headers from the edge, the control plane answers loopback —
  listens on a Unix socket in the app's own directory, its owner's alone (`dgo be-child native`,
  packaging/dgo/internal/native; forward-auth's `FORWARD_AUTH_LISTEN=unix:`). The edge alone may face the
  WebView on 127.0.0.1: it believes no caller (every identity and forwarding header a client sends is
  stripped, every gated host asks forward-auth), so another app there gets what any browser gets — the
  sign-in page. Not a socket for the WebView too: `shouldInterceptRequest` never sees a request's body, so a
  sign-in POST could not reach the edge through one. The guest's ports, when it runs, are forwarded only to
  the edge. (forward-auth's limiter then counts every app on the phone as one address: a sign-in storm from
  another app can hold the owner's sign-in back for the block's length — the price of the shared loopback.)
- **An office root in the app's storage.** `dgo be-child control` answers from a checkout's state file and
  catalog (serve.go); a phone has no checkout. The APK carries a minimal office root, unpacked to
  `File(filesDir, "office")` on first open (made 0700 by the app's umask — not `getDir()`, which is 0771 and
  so refused) and updated with the app: `platform.state.core.yaml` as `platform.state.yaml` (4 KB), every
  app's manifest (141 KB: the core's 17, and every one the install wizard may offer), the one registry file the
  console reads, `.generated/registry/console.modules.yaml`, and the bina-ui palette and icon set (28 KB) the
  install wizard's hue and animal are checked against — no secret: the phone makes its own at first run.
  Measured on the Dell (7d4964c1): 9 apps, 12 files, 52 KB, before the palette and icons. It is built by `packaging/android/native/office-root.sh` and carried as `assets/office-root.zip`.
  `dgo be-child` takes it where no checkout is found, from `DGO_OFFICE_ROOT` (main.go `officeRoot`): an
  absolute directory that neither its group nor others may write, holding `.dgo-office-root` (with the
  commit it was made from) and the state file as regular files.
- **The two stdlib blockers above are fixed before shipping**: a resolver whose `Dial` names a server (or no
  names at all — the core speaks to its own sockets), and no `net.Interfaces()` on the phone's path.
- **Container apps** (n8n, INDOX, Plane…) come from the console's first-run wizard as everywhere: the first one
  starts the guest (QEMU) in the background, from a machine downloaded in content-addressed pieces (DGO-1089),
  not bundled. Until then the APK is the core alone: ~20 MB.

**The machine on demand, decided (2026-11-01).** A container app (n8n, INDOX…) runs in the guest, whose edge
is traefik on the guest's :80; the native edge routes that app's host to it. QEMU's user network forwards a
guest port only to a host TCP port (no Unix socket), and both the machine and the core cannot hold 8080 — so:
1. QEMU forwards the guest's :80 to `127.0.0.1:<a port chosen at each boot>` (`hostfwd`), kept in files/run.
   QEMU binds it as it starts; a port another app holds makes QEMU fail to start, never the edge talk to
   that app. The native edge routes the container apps' hosts there only while that QEMU is alive.
2. A token is made at each boot and given to the guest outside its network (QEMU
   `-fw_cfg name=opt/dgo/edge-token,file=…`, read at boot into forward-auth's FORWARD_AUTH_EDGE_TOKEN). It
   never travels: the native edge SIGNS each request it sends the machine — HMAC-SHA256(token, when, a
   nonce of its own, method, host, URI, identity) in X-DGO-Edge-At/-Nonce/-Sig — and the guest's
   forward-auth takes the identity only from a request signed for itself, within a minute, once, and never
   from before its own start; the guest's traefik removes the three headers before a gated app sees them
   (authResponseHeaders). An open route (a sign-in, a webhook) is not gated, so its app sees them: a
   signature of that one request, good for nothing else. Before it sends the machine anything, the edge has the machine prove
   it holds the token (/edge-proof: HMAC of a fresh nonce), so whatever else holds the port gets nothing.
3. Identity stays the core's: the native edge has asked the core's forward-auth and writes the identity as
   it does for the console, the core's own sign-in cookies left out of what goes to the machine. Another
   app on the phone that reaches the forwarded port is anonymous there: the guest's open routes (its
   sign-in, its webhooks) answer it as they would any browser.
4. The wizard's enable then starts the machine when the first container app is chosen (control plane:
   POST /api/apps/<id>/enable starts EngineService through the app, waits for the guest's app-management,
   and hands the enable on to it); until it is up the enable answers 202 with the machine's progress, which
   install.js already follows (`/job`). Nothing of this changes the core: the machine is one more upstream.
   Decided for it (2026-11-02):
   - **What the wizard can offer**: the office root carries every app's manifest (141 KB, not the core's
     17), so the native catalog lists the container apps — their Started/Ready Unknown until the machine
     runs. Their compose files stay in the machine: the root's catalog has no services to list.
   - **Who holds a container app's state**: the machine, whose app-management enables it (compose up)
     and keeps its own platform.state.yaml as every office does. The core's root mirrors the one fact the
     core's screens need — that the app is on — written by the native control plane (set-state, `by:
     machine`) once the machine's enable has answered done; a disable likewise. The machine's state wins
     where the two differ: at each start of the machine, the core reads its enabled apps through the
     machine's app-management and sets its mirror to them.
   - **The signal**: the control plane (Go, in the core's process) asks for the machine by a file in the
     sockets' directory (`machine-wanted`); NativeService, which watches its two processes every second,
     starts EngineService with BEHIND_CORE when it appears and removes it. The control plane learns the
     machine is up as the edge does (run/machine, proved). What the app cannot do it says in
     `machine-refused` (one line), which the job answers with 503; an enable is the owner asking again,
     so it removes that line first and the app says it again only if it still holds.
   - **The disk**: when the APK carries it, the app unpacks it at that first ask (under a wakelock, its
     percent the wizard's step; stopped with the core) and marks it the core's (`files/guest.core`), so
     the app keeps opening the core — a disk without the mark is the machine's own office (DGO-1084).
   - **After a restart**: an office whose state holds apps the machine enabled (`by: machine`) asks for
     the machine as its core starts, and a host of theirs (their `routing[].host`, or its console tile's
     `<host>.console.<domain>`) opened before it is up answers the signed-in owner a page that loads itself
     again until the machine is — its step, or the app's refusal, which the page shows and does not retry
     (the owner's next enable does, and the app asks again once each time the owner comes back to it). An
     anonymous caller signs in first and starts nothing.
   - **An update**: a new APK's office root replaces the old one by renames (a swap cut short is taken
     back) and keeps the office's `platform.state.yaml` — its record and apps are the office's — when its
     schema is the new core's; the APK's own state lies beside it as `platform.state.shipped.yaml`, whose
     apps the core adds where the office's lacks them (a core app the later APK brings), once.

**The thin APK, decided (2026-11-02, DGO-1089).** With the core native, the APK is the core — dgo,
forward-auth, QEMU's libraries, the office root: ~25 MB — and never the machine (943 MB xz today):
1. The machine is fetched the first time a container app is chosen, as pieces named by their SHA-256
   (fixed 32 MiB chunks of the .xz, plus a manifest listing them in order), so an update fetches only the
   pieces that changed and a cut download resumes at its last whole piece.
2. The manifest's own SHA-256 is compiled into the APK (the engine draft it was built from, as today's
   digest check): the phone trusts no piece it cannot hash to the manifest, and no manifest it cannot hash to
   the APK — a host that serves them needs no trust at all.
3. The pieces are served where a phone can reach them without a sign-in: the office's public door
   (vps1, `https://<public host>/dgo/machine/<sha256>`), put there by the engine workflow once a draft is
   whole — not GitHub's drafts, which a phone cannot read.
4. Unpacking is today's (zstd from the native-library directory, sparse), fed the pieces in the manifest's
   order; the machine's data stays the phone's own (files/guest.img), never replaced by an update.
5. The phone's side (Guest.fetch): the APK's BuildConfig MACHINE_URL and MACHINE_MANIFEST (both empty: no
   fetch; build.gradle refuses anything but an https URL and a hex SHA-256); the list is
   `{"version": 1, "total": <bytes>, "pieces": [{"sha256", "size"}…]}`; every piece is fetched into its
   `.part` with a Range resume, hashed as it comes, named by its SHA-256 only once it checks out, kept in
   files/machine-pieces (with the list) until the machine is whole, a kept one hashed again before the
   unpack, what an earlier list left swept; every connection on the one unmetered network the fetch began
   on — a Wi-Fi gone mid-way fails it, never carries it onto the owner's data plan (a refusal that the next
   return to the app asks again); a wakelock of at most 6 h.
6. The workflow's side: the guest job (guest-box.sh) cuts the .xz into 32 MiB pieces named by their
   SHA-256 and writes their list — as `dgo-guest-arm64.manifest.json`, and among the pieces under its own
   SHA-256, the name a phone asks for it by — all on the engine's draft beside the parts (a re-run's dead
   pieces deleted first); android-app builds a fetching APK — no machine in it, BuildConfig naming the
   list — only where the repository variable DGO_MACHINE_URL is set and the list and every piece answer
   there over https alone, each piece as long as the list says; else it embeds the machine as before.
7. Not yet: a place that serves the pieces (DGO_MACHINE_URL, and what copies a draft's pieces there), and
   the machine built from the public release's tree first (DGO-1089's finding: today's disk holds the
   private repo — it is served to nobody until then).

Order, each shipping alone: (1) the edge (done, 4626ed7f); (2) the office root and `DGO_OFFICE_ROOT`;
(3) `be-child native` — edge + console + control in one process; (4) the app: `NativeService` starts the two
processes (libforward-auth.so, `libdgo.so be-child native`, built by android-app.yml with the console inside),
mints the first-run code and keeps its link — written, and NOT yet what MainActivity starts: behind the native
console every route it does not answer goes to the console's container, so (5) the console's own first-screen
routes natively — /api/me, and app-management's app list and enable for the wizard — come first, then
MainActivity opens the native core and starts the VM only on demand; (6) the thin APK and the machine
downloaded in pieces (DGO-1089).

## Sources (accessed 2026-10-14)
developer.android.com: about/versions/10/behavior-changes-10 (W^X); develop/background-work/services/fgs/{service-types,timeout,changes} (2026-10-01); guide/practices/page-sizes (2026-09-16); google/play/requirements/target-sdk; developer-verification · support.google.com/googleplay/android-developer/answer/9888379 (policy), /9859372 (size) · mobileidworld.com (ADB exempt) · github.com/termux-play-store (README 2024-06-07…2026-02-11), termux-apps#29; fornwall/termux-exec; termux-app #5150, #377; Termux-Monet README · go.googlesource.com/go: net/conf.go, cmd/link/internal/arm64/obj.go; golang/go#8877, #40569; wlynxg/anet · git.zx2c4.com/wireguard-android/about; wireguard.com/embedding; lists.zx2c4.com 2025-08 · tailscale.com/blog/android (2024-05-15); tailscale/tailscale-android; tailscale.com/kb/1112/userspace-networking · Catfriend1/syncthing-android SyncthingRunnable.java; alternativeto.net 2024-10 · forums.docker.com /t/130128, /t/140886; cosyra.com (vendor, 2026-07-18) · f-droid.org 2026/02/24, 2025/10/28 · help.nextcloud.com /t/72597, /t/248257 · danballard.com 2025-09-28.
