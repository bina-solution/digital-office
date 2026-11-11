# android-emulator's image (DGO-1797, package 11): the Android SDK's emulator with one x86_64 system image, baked
# at build time (the SDK no longer lives in a runner's home folder), the display on TigerVNC + websockify + noVNC
# (browser42's stack), and python3 for the supervisor. Built on the Dell's office (one heavy job), never on the Mac.
FROM ubuntu:24.04

ARG CMDLINE_TOOLS=commandlinetools-linux-11076708_latest.zip
ARG CMDLINE_TOOLS_SHA256=2d2d50857e4eb553af5a6dc3ad507a17adf43d115264b1afc116f95c92e5e258
ARG SYSTEM_IMAGE="system-images;android-35;google_apis;x86_64"

ENV ANDROID_SDK_ROOT=/opt/android-sdk \
    ANDROID_HOME=/opt/android-sdk \
    PATH=/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/emulator:/opt/android-sdk/platform-tools:$PATH \
    DISPLAY=:1

RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless python3 unzip wget ca-certificates util-linux \
        tigervnc-standalone-server tigervnc-common xauth fluxbox websockify novnc \
        libpulse0 libgl1 libnss3 libxcomposite1 libxcursor1 libxi6 libxtst6 libasound2t64 \
        libxkbcommon-x11-0 libxcb-xinerama0 libxcb-cursor0 libxrandr2 libxdamage1 libgbm1 libxkbfile1 \
        libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-sync1 \
        libxcb-xfixes0 libxcb-xkb1 \
    && rm -rf /var/lib/apt/lists/*

# the SDK's command-line tools, checked against their published digest, then the emulator, platform-tools and ONE
# system image (the one android-install-check.yml measured: Android 35, google_apis, x86_64 with arm64 translation)
RUN mkdir -p "${ANDROID_SDK_ROOT}/cmdline-tools" \
    && wget -q "https://dl.google.com/android/repository/${CMDLINE_TOOLS}" -O /tmp/tools.zip \
    && echo "${CMDLINE_TOOLS_SHA256}  /tmp/tools.zip" | sha256sum -c - \
    && unzip -q /tmp/tools.zip -d "${ANDROID_SDK_ROOT}/cmdline-tools" \
    && mv "${ANDROID_SDK_ROOT}/cmdline-tools/cmdline-tools" "${ANDROID_SDK_ROOT}/cmdline-tools/latest" \
    && rm /tmp/tools.zip \
    && yes | sdkmanager --licenses > /dev/null \
    && sdkmanager --install "platform-tools" "emulator" "${SYSTEM_IMAGE}" > /dev/null

# the window's Qt plugin finds every library it links, or the build says which one is missing (a missing one is
# «could not load the Qt platform plugin xcb» at the first start, long after the build)
RUN q="${ANDROID_SDK_ROOT}/emulator/lib64/qt/plugins/platforms/libqxcb.so"; \
    if [ ! -f "${q}" ]; then echo "warning: no ${q} in this emulator — its libraries are not checked"; exit 0; fi; \
    missing="$(LD_LIBRARY_PATH="${ANDROID_SDK_ROOT}/emulator/lib64/qt/lib:${ANDROID_SDK_ROOT}/emulator/lib64" \
               ldd "${q}" | grep 'not found' || true)"; \
    [ -z "${missing}" ] || { echo "the emulator's Qt xcb plugin is missing: ${missing}"; exit 1; }

COPY start.sh /start.sh
EXPOSE 6080 8080
ENTRYPOINT ["/bin/sh", "/start.sh"]
