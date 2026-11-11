FROM python:3.12-slim
WORKDIR /app
# cryptography signs a service account's JWT. Majors are bounded so a rebuild cannot pick up a breaking release.
RUN pip install --no-cache-dir "flask>=3.1,<4" "gunicorn>=23,<24" "requests>=2.32,<3" "sentry-sdk>=2,<3" "cryptography>=44"
COPY engine.py engine_rpc.py gdrive.py gdrive_sa.py dlcache.py opsupport.py media.py connections_client.py \
     gunicorn.conf.py provider.json ./
EXPOSE 8989
CMD ["gunicorn", "-c", "gunicorn.conf.py", "engine:app"]
