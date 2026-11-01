# ONE Python base across every first-party service. any-concurrency and machine were written
# later and picked the then-current tag, so the platform shipped python:3.12-slim AND
# python:3.13-slim - a second ~119 MB base layer set in the artifact, a second base to keep
# patched, and a second set of runtime behaviours to reason about, for no decision anybody made.
# 3.12 is the majority and is what every layer-3 first-party app uses. Moving the whole estate to
# 3.13 is fine, but it is a deliberate one-commit change, not a per-service drift.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static/ ./static/

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
