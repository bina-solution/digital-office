# ONE Python base across every first-party service (see platform-base/machine/Dockerfile for why
# 3.12 and not a per-service tag). The app and its sensor run from this one image.
FROM python:3.12-slim

WORKDIR /app

# The sensor's tools, and nothing else:
#   conntrack   the kernel's connection table, as events (`conntrack -E`) — every connection in and out
#   nftables    the one table the sensor owns (`inet dgo_security`): the ban set and the outbound blocks
#   iproute2    the machine's addresses and networks (`ip -j addr`)
#   systemd     for `journalctl` alone: the machine's sshd writes to its journal, read from a read-only mount
# Each is the kernel's or the distribution's own tool for its job; none is a daemon, none listens.
RUN apt-get update \
 && apt-get install -y --no-install-recommends conntrack nftables iproute2 systemd \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Every module of the app, not a list of names (see apps/computers/Dockerfile for why).
COPY *.py ./
COPY static/ ./static/
COPY tests/ ./tests/

# the parsers, the kernel filter, the jails and the nftables script are proved before the image exists
RUN python3 tests/selftest.py

EXPOSE 8995
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8995", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
