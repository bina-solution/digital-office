# DGO Cloud — one Python service, the standard library only: nothing to fetch, nothing to pin but the base image.
# The data (one SQLite file) lives in the volume at /data (app.json `data.volumes`).
FROM python:3.12-slim

WORKDIR /app
# every module, not a list of names: a list silently drops the next module someone adds
COPY *.py prices.json ./
COPY static/ ./static/
COPY node/ ./node/

ENV DGOCLOUD_PORT=8080 \
    DGOCLOUD_DATA=/data \
    PYTHONUNBUFFERED=1
EXPOSE 8080 5353/udp 5353/tcp

CMD ["python3", "server.py"]
