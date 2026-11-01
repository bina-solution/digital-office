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
# The uninstall/reinstall is not belt-and-braces, it is the fix for a crash loop. `requirements.txt`
# asks for opencv-python-headless, but `layoutparser` depends on plain `opencv-python`, and pip
# installs it too. Both ship the SAME `cv2` package, so whichever lands last wins — and the GUI
# build did. It links libGL.so.1, which the X11 libs were deliberately dropped from this image
# above, so `import cv2` raised ImportError and gunicorn crash-looped every worker on any machine
# whose image cache predated the layoutparser pin.
#
# Adding libgl1 back would also silence it, at the cost of carrying X11 libs to satisfy a package
# nothing imports (layoutparser's one user was an exploratory test file, removed 2026-10-07; it
# reached for a Detectron2 model that is not installed). Making headless authoritative removes the
# conflict instead of paying for it.
#
# `--no-deps` on the reinstall is load-bearing. Without it, --force-reinstall re-resolves the
# dependency tree and pulls numpy 2.x over the pinned 1.26.4, after which cv2 — compiled against
# numpy 1 — dies with "numpy.core.multiarray failed to import". Every dependency is already
# satisfied at that point; the only thing that needs restoring is the cv2 files the uninstall
# above removed.
#
# The final import is a build-time assertion, not decoration: it fails the image here rather than
# in a crash loop on the machine where it is deployed.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y opencv-python opencv-contrib-python \
    && pip install --no-cache-dir --force-reinstall --no-deps opencv-python-headless==4.9.0.80 \
    && python -c "import cv2, numpy; print('cv2', cv2.__version__, '+ numpy', numpy.__version__, 'import without libGL')"

# Copy application code
COPY . .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port
EXPOSE 8080

# Use Gunicorn for production
CMD ["gunicorn", "--config", "gunicorn.conf.py", "run:application"]


