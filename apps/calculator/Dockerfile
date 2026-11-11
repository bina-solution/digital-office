FROM python:3.12-alpine
WORKDIR /app
COPY server.py ./
COPY static/ ./static/
EXPOSE 8997
CMD ["python3", "-u", "server.py"]
