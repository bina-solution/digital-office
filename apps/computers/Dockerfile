# ONE Python base across every first-party service (see platform-base/machine/Dockerfile for why
# 3.12 and not a per-service tag).
FROM python:3.12-slim

WORKDIR /app

# ssh + ssh-keygen, and NOTHING else. This app opens machines over SSH with the real OpenSSH client,
# so it needs the real OpenSSH client: the key it mints is a plain OpenSSH key the owner pastes into
# an authorized_keys file, ssh's exit code is the remote command's exit code (/exec returns it
# verbatim), and the failure wording on stderr is the wording the owner will also see on the machine.
# A Python SSH library would give us none of those three and would add a dependency to keep patched.
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-client \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Every module of the app, not a list of names: a list silently drops the next module someone
# adds (transfer.py was written 2026-09-30 and the image answered `No module named 'transfer'`
# to the op that declares it — the same way dgo-extend crashed on `import peers` a day earlier).
COPY *.py ./
COPY static/ ./static/

EXPOSE 8977
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8977", "--proxy-headers", "--forwarded-allow-ips=*"]
