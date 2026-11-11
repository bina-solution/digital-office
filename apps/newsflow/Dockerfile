# newsflow — one stdlib Python service, no packages to install (main.py's header says why).
# python:3.12-slim is the base every first-party service here uses (platform-base/machine/Dockerfile).
FROM python:3.12-slim

WORKDIR /app
COPY main.py ./
COPY watchlist.json ./
COPY static/ ./static/

EXPOSE 8991
CMD ["python3", "-u", "main.py"]
