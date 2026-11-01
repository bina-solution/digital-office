# One Python base across every first-party service (see platform-base/machine/Dockerfile for why
# 3.12 and not a per-service tag).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# A real `git` binary, for the mirror engine only (mirrors.py): a mirror is a `clone --mirror` from
# one provider's account and a `push --mirror` to the local forge's, both through this app's own
# smart-HTTP proxy. The API half of this app never needs it. `--no-install-recommends` keeps the
# image at roughly +50 MB; the slim base already carries ca-certificates.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

COPY app.py accounts.py proxy.py credentials.py mirrors.py bootstrap.py repoindex.py ./
COPY adapters/ ./adapters/
# The end-to-end proof lives in the image so the owner can run it against the live service:
#   docker exec -it git-<DEPLOYMENT_NAME> python3 /app/selftest.py [--read-only]
COPY selftest.py ./
COPY static/ ./static/

EXPOSE 8978
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8978", "--proxy-headers", "--forwarded-allow-ips=*"]
