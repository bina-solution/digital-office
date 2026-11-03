FROM python:3.12-slim
WORKDIR /app
# ffmpeg pictures and probes video and audio (a frame, a cover, a waveform, a duration) — read
# straight from storage over HTTP, never downloaded whole.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
# Majors are bounded so a rebuild cannot silently pick up a breaking release. Pillow (+ pillow-heif
# for iPhone photos) and pypdfium2 draw the thumbnails of images and PDFs.
RUN pip install --no-cache-dir "flask>=3.1,<4" "gunicorn>=23,<24" "psycopg2-binary>=2.9.10,<3" \
    "requests>=2.32,<3" "sentry-sdk>=2,<3" "cryptography>=44" "Pillow>=11" "pillow-heif>=0.18" "pypdfium2>=4.30"
COPY app.py connections_client.py extensions.py db.py profiles.py bootstrap.py media.py media_jobs.py uploads.py \
     cli.py gunicorn.conf.py ./
# app.json is the ONLY place engine profiles are declared, and bootstrap.py reads it at start — so
# the manifest ships INSIDE the image rather than being restated as an env var.
COPY app.json ./app.json
COPY adapters ./adapters
COPY static ./static
EXPOSE 8975
# Server settings live in gunicorn.conf.py alone. The RUNNING command usually comes from app.json
# `broker.entrypoint` (the inject.sh wrapper that mints credentials) and is the same command.
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
