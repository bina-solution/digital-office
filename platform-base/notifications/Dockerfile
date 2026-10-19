FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py gunicorn.conf.py ./
COPY static ./static
# /data holds the SQLite db (mount a volume in compose so it persists).
RUN mkdir -p /data
EXPOSE 8977
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
