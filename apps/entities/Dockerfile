# ONE Python base across every first-party service (see platform-base/machine/Dockerfile for why
# 3.12 and not a per-service tag).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Every module of the app, not a list of names: a list silently drops the next module someone adds.
COPY *.py ./
# the screen: its page, its styles (the office's blocks, G27) and its script
COPY static/ ./static/
# the office's one door for a Python app, from the platform (compose: build.additional_contexts `dgo`)
COPY --from=dgo signin.py /opt/dgo/signin.py
# …and the platform's one verifier of the link door's signature, which the door asks for a linked office's person
# (DGO-2135; compose: build.additional_contexts `dgolink`)
COPY --from=dgolink link_identity.py /opt/dgo/link_identity.py

EXPOSE 8999
# --no-proxy-headers: the caller's address is the socket's, never a header's — the loopback rule rests on it
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8999", "--no-proxy-headers"]
