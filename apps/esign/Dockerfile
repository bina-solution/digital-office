# esign — one Python service with two faces: the office's screen and API behind the sign-in, and the
# signer's page on the one public path `/s/<token>`.
#
# Why the fonts are installed here: a PDF has no notion of text direction, and the certificate page is
# Hebrew. DejaVu Sans carries the Hebrew letters (the tests rasterise the page and check for ink), and
# `python-bidi` puts the line in the visual order a PDF needs.
FROM python:3.12-slim AS base

RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY store.py pdfsign.py clients.py server.py ./
COPY templates/ ./templates/
COPY static/ ./static/

ENV ESIGN_PORT=8080 \
    ESIGN_DATA=/data \
    PYTHONUNBUFFERED=1
EXPOSE 8080

# ── the tests: a stage of their own, so the runtime image carries no test toolchain ──────────────
FROM base AS test
COPY requirements-test.txt ./
RUN pip install --no-cache-dir -r requirements-test.txt
COPY tests/ ./tests/
CMD ["python3", "-m", "pytest", "-q", "tests"]

# ── the runtime ──────────────────────────────────────────────────────────────────────────────────
FROM base AS runtime
# a non-root user with the volume's own uid: a signed PDF and a signing key are not root's
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin esign \
 && mkdir -p /data && chown -R esign:esign /data /app
USER esign
VOLUME ["/data"]
CMD ["python3", "-u", "server.py"]
