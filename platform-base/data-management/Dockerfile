# The docker CLI *and* the compose v2 plugin, taken from the official image rather than apt.
#
# Both are needed and neither is packaged usefully in Debian: `docker.io` ships the DAEMON and lists
# the CLI only as a Recommends (so --no-install-recommends yields no `docker` binary at all), the
# `docker-cli` package is stuck at 26.1.5, and `docker-compose-v2` is not in the repos at this base's
# suite. Pinning the tag here also keeps the client on the SAME major (28.x) the platform requires of
# the daemon — see the Docker-29 warning in CLAUDE.md.
#
# Compose is not optional: deployment-archive.py discovers every bind mount and secret path through
# `dc config --format json`. Without the plugin that call fails and the inventory reports zero binds
# and zero secrets — an empty answer that looks exactly like "nothing to back up".
#
# The EXACT release, not `28-cli`: a moving tag is a different client and a different plugin on
# the day somebody rebuilds (gate G74). This service only READS with compose (`dc config`) and
# never brings a container up, so unlike app-management and bina-ds it need not follow the host's.
FROM docker:28.5.2-cli AS dockercli

# ONE Python base across every first-party service - see platform-base/machine/Dockerfile for why
# 3.12 rather than 3.13. Do not drift this tag independently.
FROM python:3.12-slim

WORKDIR /app

# postgresql-client is the meta-package tracking the distro default (17), which is >= every server
# in the stack (15.8 / 16 / 17). That direction matters: pg_dump refuses a server NEWER than itself.
#
# git is not incidental: deployment-archive.py decides what a bind mount actually contributes with
# `git ls-files` (tracked files arrive with the clone; only UNTRACKED ones must be carried) and
# refuses to write an archive into a path `git check-ignore` does not claim. Without it, bind and
# secret discovery fails and the inventory silently reports zero of both.
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 # The repo arrives as a bind mount whose owner uid is the host's, not this container's, which
 # makes git refuse it as "dubious ownership" and exit non-zero on every command. This service only
 # ever READS the checkout, so waiving the check is right here and confined to this image.
 && git config --global --add safe.directory '*'

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
# scripts/dc looks for the plugin at this exact path before it will run.
COPY --from=dockercli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/libexec/docker/cli-plugins/docker-compose

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# EVERY module app.py imports must be named here. This is an explicit file list, not a
# directory copy, so a new module is silently left OUT of the image - and because app.py
# imports them at module load, a missing one is not a degraded feature, it is a container that
# crashes on startup. Caught 2026-08-24 with a build already in flight: plan.py had been added
# and imported, this line had not been updated, and the resulting image would have failed to
# boot the moment it was deployed.
COPY app.py inventory.py plan.py pull.py coverage_report.py ./
COPY static/ ./static/

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
