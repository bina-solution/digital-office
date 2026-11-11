# Operating «אמולטור אנדרואיד» (the `android-emulator` app)

An emulated Android phone in the office (x86_64 Android 35 with arm64 translation, on the host's KVM). The owner
sees it and uses it from its tile: the live display through noVNC, touch and keyboard. It ships off, and it is
refused on a machine without /dev/kvm (app.json `requires_host`). In the herd it belongs on the Dell.

## One owner of the device

`server/supervisor.py` is the only thing that starts the emulator. Ask it; never start one by hand:

```bash
GET  http://android-emulator:8080/api/status        # off | waiting | booting | running | paused, who asked, °C
POST http://android-emulator:8080/api/start  {"by": "<who>"}
POST http://android-emulator:8080/api/stop
GET  http://android-emulator:8080/api/apks/<name>.apk?bytes=N   # would a PUT be kept? ask first: a refused
PUT  http://android-emulator:8080/api/apks/<name>.apk # PUT's reason dies with its connection; DELETE removes
POST http://android-emulator:8080/api/install {"apk": "<name>.apk"}   # from the /apks volume only
POST http://android-emulator:8080/api/shell {"argv": ["getprop sys.boot_completed"]}   # one line the device's sh runs
GET  http://android-emulator:8080/api/screenshot      # PNG, only while running
```

`device.py` is the client (the same verbs from a shell; a paused device is waited for). `check.py` is the APK
install-check that android-install-check.yml runs when its job is in the office: first install, first open,
«מצב», and with `--machine` the machine. It stops the device only if it started it.

## The heat rule (server/governor.py)

The Dell switched itself off at 92°C under an emulator (2026-11-09). So: it starts only under 80°C, is paused
(SIGSTOP, never killed) at 85°C, resumed under 80°C, and stopped at 90°C, on one physical core (cpu0 and its
sibling). A paused device does not answer adb: wait, do not retry. Under 20 GB free on the office's disk it is
stopped too. Each start, pause, resume and stop is on «כל מקביל» (`dgo:flow:android-emulator`).

## Traps

- The image is heavy (the SDK and one system image): it is built on the Dell's office, one heavy job at a time.
- It maps the host's /dev/kvm (ANDROID_KVM_DEVICE names another node); where there is none, it is not enabled.
- Its window needs Qt's xcb libraries: «could not load the Qt platform plugin xcb» in its log means one is missing.
