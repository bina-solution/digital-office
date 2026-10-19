FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir flask==3.0.* requests==2.31.* gunicorn==23.0.* sentry-sdk
COPY app.py .
COPY static ./static
EXPOSE 8000
# thin BFF: ONE worker + threads. A single process is required so the in-memory idempotency
# cache + per-key locks that make document creation exactly-once are authoritative (2 processes
# wouldn't share them); threads keep it concurrent for I/O-bound proxying.
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "1", "-k", "gthread", "--threads", "8", "--timeout", "150", "app:app"]
