FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir flask gunicorn requests sentry-sdk
COPY app.py .
COPY static ./static
EXPOSE 8976
# gthread, not the default sync worker: this app is a thin PROXY — every request blocks on an
# upstream mailapi/n8n call (a message open alone fans out to /api/message + /api/thread +
# /api/doc-context, and doc-context waits up to 30s on an n8n webhook). Two sync workers meant two
# in-flight upstream calls saturated the entire UI for every user; threads are the right unit for
# IO-bound waiting. 2x8 = 16 concurrent proxied requests, still one shared requests.Session pool.
CMD ["gunicorn","-w","2","-k","gthread","--threads","8","-b","0.0.0.0:8976","--timeout","120","--access-logfile","-","app:app"]
