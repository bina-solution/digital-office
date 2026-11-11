FROM python:3.12-slim

# No dependencies: this is one stdlib handler (server.py). Keep it that way — the office's front
# door for port 80 must be boring, and an image with nothing to install cannot drift or phone home.
WORKDIR /app
# `--chmod`: the file arrives with whatever mode the checkout gave it (this tree keeps 0600), and the
# image runs as uid 10001 — measured 2026-11-09, without this the container crash-looped on
# "can't open file '/app/server.py': [Errno 13] Permission denied"
COPY --chmod=0644 server.py ./

ENV PYTHONUNBUFFERED=1 HTTPS_REDIRECT_PORT=8079
# non-root, and nothing writable in the image: the service answers headers, it stores nothing
RUN useradd -r -u 10001 -s /usr/sbin/nologin httpsredir
USER 10001

EXPOSE 8079
CMD ["python", "-u", "server.py"]
