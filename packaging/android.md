# Android — the full office on a phone

> **Status 2026-11-01 (DGO-1071, DGO-1084).** The app is the office. Install the APK, open it: it
> sets the whole DGO up on the phone by itself — as `bbox run` does on every other OS — and opens its
> console. Nothing to choose, nothing to connect; linking it to other offices (DGO Extend) and the rest
> is done from inside the office, as everywhere else.

## On the phone

1. **Install the APK** from its draft release (`android-0.1.N`, attached by
   [`android-app.yml`](../.github/workflows/android-app.yml)); allow installs from that source. It is
   under 2 GB: the office's machine is inside it, every image the office runs already in it. A 0.1.1 or
   0.1.2 is removed first, once — each was signed by another key; from 0.1.3 on, every APK installs over
   the one before.
2. **Open it.** The first open unpacks the office's machine into the app's storage (it needs 10 GB free:
   ~7 GB for the machine, the rest for the office's data), starts the engine, and shows the
   office's own lines while it comes up — the screen stays on meanwhile. The first start is long: an
   app gets no hardware acceleration on a phone, so the machine's CPU is emulated. Then the console
   opens; sign in as on every office.
3. **From then on** the app opens the console (starting the office first when it is not running). The
   office runs in the background with a notification; its *Stop* powers the machine off.

## How it is made

`packaging/android` is the app — framework-only Java (no AndroidX), minSdk 26, arm64 — built by
`android-app.yml` (a push to dgo-stable whose head commit says `[android]`) from one engine draft that
holds both of its halves:

* **QEMU** for android/arm64 — `android-engine.yml`'s `qemu` job: our trimmed termux-packages recipe
  (`engine/dgo-qemu`) under the app's package name, its binary and libraries as `lib*.so` in the APK's
  `jniLibs` (the one place an app targeting Android 10+ may execute its own program), each finding its
  libraries beside itself (RUNPATH `$ORIGIN`), its firmware in `assets/qemu`; beside it the zstd program
  QEMU's own dependency brings, which unpacks the machine;
* **the office's machine** — its `guest` job (`engine/guest.sh`): the Mac engine's pinned Ubuntu 24.04
  arm64 image and provisioning, Docker 28.5.2 and Compose 2.40.3, the office at /opt/office brought up
  at every boot by `dgo-office.service` (whose lines go to the machine's console, which the app shows),
  and every image the office runs — its own built for arm64 in CI, the public ones (the edge, the
  databases, the sign-in) pulled for arm64 there — unpacked into the machine's image store in CI, so the
  phone builds, pulls and unpacks none (pulled at the first boot, they took 1.8 h under emulation). A
  raw 24 GB disk, xz'd (the smallest the zstd program reads: the whole office in one APK under GitHub's
  2 GB a file) — `assets/guest` in the APK, unpacked sparse at the first open, and never again over a
  machine that is there: it holds the office's data, and the office updates itself from inside. When the
  office does not come up clean, the machine's console lists its containers and each unhealthy one's
  last probes (`dgo-office-report`), on the app's screen and in the boot test's log.

The engine (`EngineService`) runs QEMU as a foreground service with the CPU kept awake, TCG unless the
phone opens `/dev/kvm` to the app, and forwards the machine's edge (80) to the phone's 127.0.0.1:8080:
the console is `http://console.localhost:8080`, as on the Mac. The app opens it when bbox run in the
machine has said "up" and the edge answers (sign-in answers for every host before the console behind it
is ready).

`android-guest.yml` (`[android-guest]`) boots the newest machine the same way on GitHub's runner —
`engine/try-guest.sh`, any Linux machine with Docker — and says how long each stage took, until the
office is up.

What each build is made from is pinned, so an APK made tomorrow carries the engine proven today: Termux's
recipe at one commit and its builder image by digest (QEMU 11.1.2; a newer QEMU moves the commit, the
digest and `engine/dgo-qemu/build.sh` together), the machine's Ubuntu image by digest
(`packaging/macos/engine.yaml`), Docker and Compose in it. Every APK from 0.1.3 on is signed by one kept
debug key (the workflow's cache, or the repository secret `DGO_ANDROID_DEBUG_KEYSTORE` for good).

## Known limits

* **Speed.** No KVM for an app on a stock phone: QEMU emulates the CPU — measured ~20× slower to boot
  than native on the MacBook's engine. The first start is the long one.
* **Size.** The APK carries the machine (under 2 GB, GitHub's limit for a release file; the workflow
  stops an APK over it). The store will take it as an install-time asset pack
  (Play Asset Delivery) — with the owner's signing key and Play account (DGO-1073), the privacy policy
  ([android/PRIVACY.md](android/PRIVACY.md)) and a listing; and before the store the machine is made
  from the public line.
* A file downloaded from the office opens in the phone's browser, which has not signed in (the system's
  download service cannot resolve `*.localhost`); Google's sign-in opens in the browser too (Google
  refuses it in a WebView), so a Google connection made there completes there.
* An old Android System WebView (below 85) cannot show the sign-in: the app says so and links its update.

## Without the app

* **Android's Linux terminal** (Android 15+, the Android Virtualization Framework's Debian 12 arm64
  machine, under Developer options → *Linux development environment*) takes the office as any Debian
  machine does — `git clone`, `./bbox install debian`, `./bbox run` — measured on a clean Debian 12
  arm64 (2026-10-31): `bbox install debian` in 26 s, identity "up." in 186 s. Leave it 20 GB of disk.
  Not yet tried on a phone.
* **`dgo` for android/arm64** ships with each release (`dgo-android-arm64`, in SHA256SUMS): the native
  core as a command in an app such as Termux. It runs no office there; `dgo engine doctor` says where
  the phone's office runs.
