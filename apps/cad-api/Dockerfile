# ONE Python base across every first-party service (see platform-base/machine/Dockerfile for why 3.12).
FROM python:3.12-slim

# KERNEL=1 (the default): build123d on OpenCascade, so /model exports STEP and glTF. KERNEL=0: the quote-only build — the
# takeoff, the caps' BOM and cost answer, /model says the kernel is not here (a loaded office pricing jobs, DGO-1076).
ARG KERNEL=1

# build123d's kernel (OCP = OpenCascade) links libGL and glib even headless; nothing else from the OS.
RUN if [ "$KERNEL" = "1" ]; then apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
      && rm -rf /var/lib/apt/lists/*; fi

WORKDIR /app
COPY requirements.txt requirements-kernel.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$KERNEL" = "1" ]; then pip install --no-cache-dir -r requirements-kernel.txt; fi

# Every module and every family, not a list of names: a list silently drops the next one someone adds.
COPY *.py ./
COPY families/ ./families/
COPY caps/ ./caps/
# the pages a person opens (the caps' gallery and one page per cap) and the three.js they draw with (r160, from npm)
COPY static/ ./static/

EXPOSE 8996
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8996", "--proxy-headers", "--forwarded-allow-ips=*"]
