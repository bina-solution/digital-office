# ONE Python base across every first-party service (see platform-base/machine/Dockerfile for why
# 3.12 and not a per-service tag).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Every module of the app, not a list of names: a list silently drops the next module someone adds.
COPY *.py ./
COPY static/ ./static/

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
