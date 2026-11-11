# One Python base across every first-party service (see platform-base/machine/Dockerfile for why 3.12).
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY static/ ./static/

EXPOSE 8984
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8984", "--proxy-headers", "--forwarded-allow-ips=*"]
