# One Python base across every first-party service (see platform-base/machine/Dockerfile for why
# 3.12 and not a per-service tag).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# every module, not a list: a new file (browser_session.py arrived this way) that is not
# copied is a ModuleNotFoundError at the FIRST use, in production, far from the change.
COPY *.py ./
COPY static/ ./static/

EXPOSE 8980
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8980", "--proxy-headers", "--forwarded-allow-ips=*"]
