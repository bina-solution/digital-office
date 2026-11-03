# =============================================================================
# Python runtime
# =============================================================================
# Use Python 3.12 slim image for better security and smaller size
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FLASK_DEBUG=False \
    LOG_LEVEL=INFO \
    PORT=8080

# Install system dependencies for OCR and PDF processing
# ffmpeg removed: nothing here touches video — the only match in the tree was the string
# 'video/mp4' in a MIME table. That was ~300MB of codecs for nothing.
# libsm6/libxext6 removed: X11 libs needed only by the GUI build of OpenCV. We install
# opencv-python-headless now, which does not link them. The only cv2.imshow call in the
# repo is inside an example function nothing calls (ocr_processor.ocr_example).
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-heb \
    curl \
    # WeasyPrint (beautiful HTML/CSS -> PDF for doc_gen) runtime libraries
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fontconfig \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies.
#
# THE CONFLICT THAT MADE THIS LINE NECESSARY IS GONE (DGO-438). `requirements.txt` asked for
# opencv-python-headless while `layoutparser` — a package nothing in this tree imports; its one user
# was an exploratory test file, removed 2026-10-07, and it reached for a Detectron2 model that is not
# installed — depended on plain `opencv-python`. Both ship the same `cv2` package, so whichever
# landed last won, and the GUI build did: it links libGL.so.1, which the X11 libs were deliberately
# dropped from this image above, so `import cv2` raised ImportError and gunicorn crash-looped every
# worker. The fix at the time was to force the headless build back over it, with `--no-deps` because
# re-resolving pulled numpy 2.x over the pinned 1.26.4 and `cv2` then died on
# "numpy.core.multiarray failed to import". With layoutparser out of the file, nothing pulls the GUI
# build at all and there is nothing to undo.
#
# WHAT STAYS, AND WHY: the import below is a build-time assertion, not decoration — it fails the image
# HERE rather than in a crash loop on the machine where it is deployed, which is exactly the failure
# this whole comment describes. If a future dependency ever drags `opencv-python` back in, the build
# stops with "import without libGL" missing instead of shipping a broken worker.
# The final import is a build-time assertion, not decoration: it fails the image here rather than
# in a crash loop on the machine where it is deployed.
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import cv2, numpy; print('cv2', cv2.__version__, '+ numpy', numpy.__version__, 'import without libGL')" \
    && python -c "import importlib.util,sys; sys.exit(1 if importlib.util.find_spec('layoutparser') else 0)" 

# Copy application code
COPY . .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port
EXPOSE 8080

# Use Gunicorn for production
CMD ["gunicorn", "--config", "gunicorn.conf.py", "run:application"]


