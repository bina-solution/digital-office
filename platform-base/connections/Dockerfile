FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py broker.py identity.py cli.py ui.html ./
COPY providers/ ./providers/
COPY manifests/ ./manifests/
EXPOSE 8990
CMD ["python", "app.py"]
