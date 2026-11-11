# ONE Python base across every first-party service (see platform-base/machine/Dockerfile for why
# 3.12 and not a per-service tag). The app and its sensor run from this one image.
# BOOKWORM, on purpose (DGO-1358): the sensor writes its nftables table into the HOST's namespace, and the host's
# own `nft` must still read it. `python:3.12-slim` moved to Debian 13, whose nft 1.1.3 writes rulesets that
# Debian 12's nft 1.0.6 cannot list at all — it segfaults on any of them (measured on vps1 2026-11-05: `nft list
# tables` exit 139, and the host-level tunnel to the MacBook died on it). Written by bookworm's nft 1.0.6, the
# same tables list cleanly there (measured the same day, in a throwaway namespace), and every newer nft reads an
# older one's (Ubuntu 24.04's 1.0.9 reads them on the MacBook's engine).
FROM python:3.12-slim-bookworm

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

# Every module of the app, not a list of names (see apps/computers/Dockerfile for why) — and its data: egress.yaml
# is the outbound declaration egress.py loads, so an image without it would fail the selftest below (DGO-1561).
COPY *.py *.yaml ./
COPY static/ ./static/
COPY tests/ ./tests/

# the parsers, the kernel filter, the jails and the nftables script are proved before the image exists
RUN python3 tests/selftest.py

EXPOSE 8995
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8995", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
