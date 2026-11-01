# ui-capture — a minimal, single-purpose Playwright/Chromium image for the UI map.
#
# Replaces the heavyweight browser42 stack (browser-browser + mcp + caddy, CPU-capped,
# shared long-running browser with a tab reaper) for capture. This image does ONE thing:
# launch a private headless Chromium and drive capture.py. Run N of these containers on the
# stack network in parallel (each --shard i/N, its own Chromium) for cores-wide parallelism,
# and they reach the console DIRECTLY by service DNS on :8000 — no Traefik hop, which is what
# made browser42's captures render near-empty. Identical image is used locally and in CI.
FROM python:3.12-slim

# Chromium + the fonts the Hebrew RTL UI needs to render legibly, plus the shared libs a
# headless Chromium links against. chromium's apt deps pull most of them; the explicit list is
# belt-and-braces so the binary never fails to start on a slim base.
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium \
      fonts-noto-core fonts-noto-cjk fonts-noto-color-emoji fonts-dejavu-core \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
      libasound2 libpango-1.0-0 libcairo2 libatspi2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# capture.py drives Chromium via the playwright PYTHON api (launching the system chromium
# binary, not a downloaded one); pyyaml/pillow are only for the host report/compose steps but
# are cheap to include so the same image can run those too.
# PIP_TRUSTED is empty in CI (direct pypi); a proxied dev host passes
# --build-arg PIP_TRUSTED="--trusted-host=pypi.org --trusted-host=files.pythonhosted.org".
ARG PIP_TRUSTED=""
RUN pip install --no-cache-dir ${PIP_TRUSTED} playwright pyyaml pillow

ENV UI_OWN_BROWSER=1 \
    UI_CHROME_BIN=/usr/bin/chromium \
    PYTHONUNBUFFERED=1

WORKDIR /repo
