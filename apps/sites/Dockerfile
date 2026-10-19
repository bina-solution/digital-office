# One Python base across every first-party service (see platform-base/machine/Dockerfile for why
# 3.12 and not a per-service tag).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# every module, not a list — same reason as apps/domains/Dockerfile: a missing COPY is
# an ImportError at the first request that needs the new file.
COPY *.py ./
COPY checks/ ./checks/
COPY static/ ./static/

EXPOSE 8979
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8979", "--proxy-headers", "--forwarded-allow-ips=*"]
