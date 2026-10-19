# archify — the office's diagrams, rendered by Archify (https://github.com/tt-a1i/archify, MIT).
#
# The renderer is THIRD-PARTY code that runs on every start, so it is pinned twice: to a commit (the
# URL names the blob at that commit, which git addresses by content) and to a checksum of the bytes
# that arrive. "Download an archive and unpack it into the image" is exactly the step where a silent
# substitution would be invisible, and a tag alone is something its owner can move.
#
# `archify.zip` is upstream's own packaging of its `archify/` directory: the CLI, the five renderers
# and their schemas, with no dependency to install (measured 2026-10-05: 106 files, 7.3 MB, renders
# with nothing but node). Its licence travels with it, in the same archive.
FROM node:22-alpine

ARG ARCHIFY_COMMIT=2ab3cae7ac2c2a55d7386ca789d03c4fcd31816c
ARG ARCHIFY_SHA256=b0b23bd28db314f04ca8ab9620fe20f8c1ac6474a3546bd8fe4679508aa1b7f5

RUN wget -q -O /tmp/archify.zip "https://raw.githubusercontent.com/tt-a1i/archify/${ARCHIFY_COMMIT}/archify.zip" \
 && echo "${ARCHIFY_SHA256}  /tmp/archify.zip" | sha256sum -c - \
 && unzip -q /tmp/archify.zip -d /opt \
 && rm /tmp/archify.zip \
 && test -f /opt/archify/LICENSE \
 && node /opt/archify/bin/archify.mjs examples >/dev/null

WORKDIR /app
COPY server.mjs .
USER node
EXPOSE 8080
CMD ["node", "server.mjs"]
