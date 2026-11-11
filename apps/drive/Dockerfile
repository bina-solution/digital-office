FROM python:3.12-slim
WORKDIR /app
# ffmpeg remuxes a recording made in a browser (MediaRecorder) into a container that seeks, before it is
# stored — whichever engine stores it. The engines draw pictures and probe media themselves (DGO-1500).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
# Majors are bounded so a rebuild cannot silently pick up a breaking release. No database driver, no
# imaging and no crypto here: those are the engines' (apps/drive-local, apps/drive-google).
RUN pip install --no-cache-dir "flask>=3.1,<4" "gunicorn>=23,<24" "requests>=2.32,<3" "sentry-sdk>=2,<3"
COPY app.py engines.py connections_client.py extensions.py media.py uploads.py cli.py gunicorn.conf.py ./
COPY static ./static
EXPOSE 8975
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
