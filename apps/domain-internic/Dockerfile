# One Python base across every first-party service (see platform-base/machine/Dockerfile for why
# 3.12 and not a per-service tag).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# every module, not a list: a module that is not copied is a ModuleNotFoundError at its first use.
COPY *.py ./
COPY provider.json ./
COPY static/ ./static/

EXPOSE 8981
# --no-proxy-headers: the address a request comes FROM is the socket's, never an X-Forwarded-For a caller
# wrote. A consent to a write is taken only from 127.0.0.1 (the CLI inside this container, app.py
# api_records); with proxy headers trusted, any caller could send `X-Forwarded-For: 127.0.0.1` and be it.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8981", "--no-proxy-headers"]
