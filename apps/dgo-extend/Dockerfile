# ONE Python base across every first-party service (see platform-base/machine/Dockerfile for why
# 3.12 and not a per-service tag). No ssh, no docker CLI: machines are reached through `computers`.
FROM python:3.12-slim

WORKDIR /app

# A tunnel needs three binaries the python base does not carry: `wg-quick` (wireguard-tools),
# `nft` (nftables) and `ip` (iproute2). They are installed HERE rather than in a second image because
# the tunnel is this app's own sidecar (service `dgo-net`, same image) — one image to build, and the
# renderer and the applier can never drift apart by being two.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
        wireguard-tools nftables iproute2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Every module of the app, not a list of names: a list silently drops the next module someone adds
# (peers.py was built on 2026-09-30 and the image crash-looped on `import peers`).
COPY *.py ./
COPY static/ ./static/
COPY tunnel-entrypoint.sh /tunnel-entrypoint.sh
RUN chmod +x /tunnel-entrypoint.sh

EXPOSE 8983
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8983", "--proxy-headers", "--forwarded-allow-ips=*"]
