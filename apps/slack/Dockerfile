# slack — the adapter: Slack's Web API behind chat.v1 (adapter/server.py says what it does).
# One Python base across every first-party service (see platform-base/machine/Dockerfile for why 3.12).
# Standard library only: no requirements to install.
FROM python:3.12-slim

WORKDIR /app
COPY adapter/server.py /app/server.py
RUN useradd --uid 1000 --create-home slack
USER 1000
EXPOSE 3094
CMD ["python", "-u", "/app/server.py"]
