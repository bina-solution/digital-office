# One Python base across every first-party service (see platform-base/machine/Dockerfile for why
# 3.12 and not a per-service tag).
FROM python:3.12-slim

# libcairo2: cairosvg's renderer. An SVG logo becomes the PNG avatars and banners are cut from — no
# social platform accepts an SVG, and without this the plan says "upload a PNG" instead.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libcairo2 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# every module and the blueprints (data): a blueprint that is not copied is a gallery that silently
# lacks it. research/ is evidence for humans, not runtime.
COPY *.py ./
COPY blueprints/ ./blueprints/
COPY static/ ./static/

EXPOSE 8985
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8985", "--proxy-headers", "--forwarded-allow-ips=*"]
