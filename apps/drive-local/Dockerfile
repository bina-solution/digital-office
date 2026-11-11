FROM python:3.12-slim
WORKDIR /app
# ffmpeg pictures and probes this engine's own video and audio (a frame, a cover, a waveform, a duration) —
# read straight from storage over HTTP, never downloaded whole. Pillow (+ pillow-heif for iPhone photos)
# and pypdfium2 draw the thumbnails of images and PDFs. Majors are bounded.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "flask>=3.1,<4" "gunicorn>=23,<24" "psycopg2-binary>=2.9.10,<3" \
    "requests>=2.32,<3" "sentry-sdk>=2,<3" "Pillow>=11" "pillow-heif>=0.18" "pypdfium2>=4.30"
COPY engine.py engine_rpc.py local.py opsupport.py media.py media_jobs.py profiles.py db.py bootstrap.py \
     connections_client.py gunicorn.conf.py provider.json ./
# app.json is the ONLY place engine profiles are declared, and bootstrap.py reads it at start
COPY app.json ./app.json
EXPOSE 8988
# The RUNNING command usually comes from app.json `broker.entrypoint` (the inject.sh wrapper that leases
# the supabase credentials) and is the same command.
CMD ["gunicorn", "-c", "gunicorn.conf.py", "engine:app"]
