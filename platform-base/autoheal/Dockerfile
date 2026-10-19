# autoheal — stdlib only, on purpose.
#
# python:3.12-slim is ALREADY PRESENT on every host in this estate (it is the base the other
# first-party python services build from), so this image adds one COPY layer and pulls nothing.
# That matters on this deployment specifically: `~/.docker/config.json` carries a `credsStore`
# whose helper does not exist under WSL, so any build that needs a registry round-trip fails with
# "error getting credentials" — a build with no new base and no package install cannot hit it.
#
# There is deliberately no `pip install`: the whole service talks to the Docker Engine API over the
# unix socket with http.client, the same way platform-base/connections/identity.py does. Adding
# docker-py would pull ~40 packages to save about twenty lines, on a host with 132 MiB free.
FROM python:3.12-slim

WORKDIR /app
COPY autoheal.py /app/autoheal.py

# Unbuffered so a restart decision reaches `docker logs` before the restart it describes takes the
# container's log stream with it.
ENV PYTHONUNBUFFERED=1

# Runs as root because the docker socket is root-owned. This container's only capability is
# "restart a container that opted in by label", but the socket itself is root-equivalent on the
# host — that residual risk is stated here and in the compose file rather than glossed over.
CMD ["python", "/app/autoheal.py"]
