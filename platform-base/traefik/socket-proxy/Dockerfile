# The read-only door in front of the engine socket (DGO-136).
#
# python:3.12-slim is the base every first-party python service here builds from (autoheal, machine,
# connections), so this adds one COPY layer and pulls nothing: no socat, no third-party proxy image
# to pin and trust — the rule is stdlib only, in proxy.py.
FROM python:3.12-slim
WORKDIR /app
COPY proxy.py /app/proxy.py
# Unbuffered so a refusal is in `docker logs` the moment it happens, not when the buffer fills: a
# door that refuses silently is a door whose refusals nobody reads.
CMD ["python", "-u", "/app/proxy.py", "--port", "2375", "--socket", "/var/run/docker.sock"]
