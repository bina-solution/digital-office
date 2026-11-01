# One Python base across every first-party service (see platform-base/machine/Dockerfile for why
# 3.12 and not a per-service tag).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ffmpeg is the difference between "a film" and "a film that PLAYS". Telegram's channels publish
# mostly Matroska (which no browser can open) and often AC3/DTS audio (which Chrome cannot decode), so
# the app needs to inspect what a file really is and, when the container or the audio is the only
# problem, remux it on the fly into fragmented MP4 — video stream copied, so it costs ~5% of a core
# instead of a transcode. `--no-install-recommends` keeps the extra ~300 MB of GUI/X libraries out.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# every module, not a list — a missing COPY is an ImportError at the first request that needs the
# new file, and this app's failure mode for a missing module is a 500 in the middle of the wizard.
COPY *.py ./
COPY static/ ./static/

EXPOSE 8982
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8982", "--proxy-headers", "--forwarded-allow-ips=*"]
