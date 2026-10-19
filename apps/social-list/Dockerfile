# One Python base across every first-party service (see platform-base/machine/Dockerfile for why
# 3.12 and not a per-service tag).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# every module and every data file, not a list: a new adapter or script that is not copied is a
# ModuleNotFoundError (or an empty catalogue) at its FIRST use, in production, far from the change.
COPY *.py ./
COPY platforms.yaml ./
COPY adapters/ ./adapters/
COPY scripts/ ./scripts/
COPY static/ ./static/

EXPOSE 8986
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8986", "--proxy-headers", "--forwarded-allow-ips=*"]
