FROM python:3.12-slim
WORKDIR /app
# docker CLI: installing an app must also install its AUTOMATIONS, and the tested logic for that
# lives in apps/n8n/hooks/{push,unpush}, which drive `docker exec` against the n8n
# container. Without the CLI this service could flip enabled=true in platform.state.yaml and start
# containers, but an automation-only app (kind: blueprint) would appear "installed" with nothing
# imported into n8n. Reusing the hooks beats reimplementing them here in docker-py.
# NOTE: `docker.io` on Debian trixie ships only the DAEMON (dockerd/docker-proxy/docker-init) —
# the client moved to `docker-cli`. Installing docker.io here silently produced an image with no
# /usr/bin/docker at all. Verify the binary exists at build time so this can never regress.
# compose plugin: _install brings an app up through /repo/scripts/dc — the SAME canonical
# invocation `bbox run` uses — instead of reimplementing compose semantics in docker-py. That needs
# `docker compose` to exist in this image.
#
# Debian trixie ships NEITHER docker-compose-plugin NOR docker-compose-v2 (only the obsolete v1
# `docker-compose`), so the plugin comes from Docker's own apt repo — the same source and the same
# package the host gets from debian-install.sh, so the control plane and the CLI run one compose
# build rather than two. Installed at /usr/libexec/docker/cli-plugins/docker-compose, which is what
# ${BBOX_COMPOSE} names (see scripts/lib.sh: `docker compose` is a plugin SEARCH and resolves to
# Docker Desktop's binary wherever Desktop is installed).
#
# THE SAME VERSION AS THE HOST'S, said out loud. "The same package" was not the same build: unpinned,
# this image took whatever was newest on the day it was built (5.5.1 on the MacBook, 5.6.0 on
# hp-laptop) — and two versions of compose normalise one short-syntax bind differently
# (`bind.create_host_path`), so 18 of 25 services had one identity for the apps screen and another
# for `bbox run`, and each re-created what the other had made (measured 2026-10-06). The version is
# handed in by whoever builds (docker-compose.yml `build.args`, from the compose that host runs);
# the default is what debian-install.sh installs, and gate G74 holds the two equal.
#
# Verified at build time so a silently-plugin-less image can never regress — the same reason the
# docker-cli line below asserts `docker --version`.
ARG COMPOSE_VERSION=2.40.3
RUN apt-get update \
 && apt-get install -y --no-install-recommends docker-cli ca-certificates curl gnupg \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && chmod a+r /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends "docker-compose-plugin=${COMPOSE_VERSION}-1~debian.12~bookworm" \
 && rm -rf /var/lib/apt/lists/* \
 && docker --version \
 && test "$(docker compose version --short)" = "${COMPOSE_VERSION}"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py admission.py ./
COPY static ./static
EXPOSE 8080
# ONE worker, many threads. This service holds state that must be the same for every request: the
# lifecycle lock, the bring-up jobs a caller follows (`/api/apps/<id>/job`) and the staged-install
# tokens. With two workers each had its own: "one lifecycle op at a time" held per worker, not per
# office, and a previewed install's token existed only in the worker that had staged it.
CMD ["gunicorn","-w","1","-k","gthread","--threads","16","-b","0.0.0.0:8080","--timeout","120","--access-logfile","-","app:app"]
