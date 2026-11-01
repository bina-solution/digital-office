# API Tools

OCR- and document-tools microservice built with Flask. It provides endpoints for PDF→JPEG conversion, document OCR, and structured text queries over OCR results.


## What it does

- PDF to JPEG conversion and page stitching
- Document upload + OCR, returning a stable file_id (MD5 of content) for later queries
- JSON-driven, position-based queries over OCR text (e.g., “find after ‘invoice id’” with validations)
- Optional debug drawings of matches during development
- Works with images (JPEG/PNG) and PDFs; handles skew/rotation and fuzzy matching


## Architecture at a glance

- Web API: Flask app in `src/api` with CORS and structured logging
- OCR engine: Google Cloud Vision (via HTTP) in `src/ocr_core/ocr_processor.py` with on-disk caching
- PDF processing: `pdf2image` + OpenCV for page deskew/concat in `src/pdf_core`
- Image utilities: deskewing, resizing, rotations in `src/utils` and `src/image_core`
- Storage layout (created on demand):
  - `.storage/` (configurable by code; volume-mounted in Docker)
    - `files/` uploaded originals
    - `ocr_cache/` Vision API OCR JSON cache (keyed by MD5)
    - `ocr_pdf_images/` generated JPEGs from PDFs
    - `ocr_drawings/` optional debug visuals
  - `.test_files/` sample inputs for development/tests

Entrypoints:
- `run.py` loads environment (.env supported) and serves the Flask app
- `gunicorn.conf.py` provides a production-ready Gunicorn config
- `Dockerfile` packages system deps (poppler, tesseract) + Python deps
- `docker-compose.yml` runs the service as `apitools` on port 8080


## HTTP API

Base URL defaults to `http://localhost:8080` (PORT configurable).

- GET `/` – service info and health summary
  - 200: `{ "service": "API Tools", "version": "0.5.1", "status": "healthy" }`

- GET `/health` – readiness/health with storage check
  - 200/503 JSON status

- POST `/pdfToJpeg` – convert a PDF to a long JPEG
  - Body: multipart/form-data with `file` (application/pdf)
  - 200: `image/jpeg` response (attachment)

- POST `/documentOcr` – upload and OCR a file (PDF/JPEG/PNG)
  - Body: multipart/form-data with `file`
  - 200: JSON with fields including:
    - `file_name`, `file_type`, `file_extension`, `filepath`, `file_hash`
    - `ocr_json` (unless `?dont_return_ocr=1` set)

- POST `/documentJsonQuery` – run a structured query on an existing OCR result
  - JSON body:
    {
      "file_id": "<md5 returned from documentOcr>",
      "match_index": 0,
      "ocr_json_query": {
        "action": "find after",
        "action_value": ["invoice id", "חשבונית מס"],
        "value_validations": [
          {"validation_type": "has_number"},
          {"validation_type": "length_greater_than", "validation_value": 3},
          {"validation_type": "length_less_than", "validation_value": 20}
        ],
        "is_rtl": true
      }
    }
  - 200: `{ "result": "<extracted value>", "process_context": { ... } }`

- GET `/docExists` – check if a file_id already exists in cache
  - JSON body: `{ "file_id": "<md5>" }`
  - 200: `{ "file_id": "<md5>", "exists": true|false, "file_path": "..." }`


## Project structure

```
apitools/
  src/
    api/               # Flask endpoints and app factory
    ocr_core/          # OCR data model, query engine, Vision API integration
    pdf_core/          # PDF→JPEG conversion pipeline
    image_core/        # Generic image utilities
    utils/             # Storage paths, deskew, fuzzy match, etc.
  run.py               # Dev/WSGI entry (with dotenv support)
  gunicorn.conf.py     # Production server config
  requirements.txt     # Python dependencies
  docker-compose.yml   # Local container orchestration
  Dockerfile           # Container build (installs poppler + tesseract)
  .storage/            # Persisted data (mounted as volume in Docker)
  .test_files/         # Inputs for tests/dev
```


## Requirements

- Python 3.11+ (Docker image uses 3.12)
- System packages for local runs (Debian/Ubuntu):
  - `poppler-utils` (pdf2image backend)
  - `tesseract-ocr` + languages `tesseract-ocr-eng` and `tesseract-ocr-heb` (used by some tests and utilities)
- Google Cloud Vision API access for production OCR
  - Note: `src/ocr_core/ocr_processor.py` currently uses a hard-coded API key. Moving this to an environment variable is recommended.


## Run locally (Linux)

1) Install system dependencies (once):

```bash
sudo apt-get update
sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-heb
```

2) Create a virtual environment and install Python deps:

```bash
cd apitools
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

3) Optional: configure environment in a `.env` file (auto-loaded):

```bash
echo 'FLASK_DEBUG=True' > .env
echo 'LOG_LEVEL=INFO' >> .env
echo 'PORT=8080' >> .env
# Recommended future change: GOOGLE_VISION_API_KEY=<your-key>
```

4) Start the server:

```bash
# Development server
python run.py

# or Production-style (same machine)
gunicorn --config gunicorn.conf.py run:application
```

5) Smoke test:

```bash
curl -s http://localhost:8080/ | jq .
curl -s http://localhost:8080/health | jq .
```


## Run with Docker

The image installs all system and Python dependencies.

```bash
cd apitools
# Build
docker build -t apitools:local .

# Run (simple)
docker run --rm -p 8080:8080 \
  -v "$(pwd)/storage:/app/.storage" \
  -v "$(pwd)/logs:/app/logs" \
  --name apitools apitools:local
```

Using docker-compose (recommended for persistence and healthchecks):

```bash
cd apitools
docker compose up --build
```

Notes:
- `docker-compose.yml` references an external network `traefik-network`. If you don’t use Traefik, remove the `networks` section or create it beforehand:
  ```bash
  docker network create traefik-network
  ```


## Testing

There are two kinds of tests in `tests/`:

1) API tests that call a running server (http://127.0.0.1:8080 by default):
   - `tests/test_api.py`
   - `tests/test_doc_exists.py`

   How to run:
   - Start the server locally (see above)
   - Ensure sample files exist under `.test_files/`
   - Run tests from the project root:
     ```bash
     cd apitools
     python -m unittest tests/test_doc_exists.py
     python -m unittest tests/test_api.py
     ```
   Known caveats:
   - `test_api.py` expects the root endpoint to return "Hello API!", but the current app returns a JSON info object. Update the assertion or test `/health` instead.
   - `test_doc_exists.py` mixes GET and POST for `/docExists` while the API exposes GET. Prefer GET for both checks.

2) Unit tests that need no server — `tests/*_unit.py`, `tests/test_ocr_json_query_match_mode.py`,
   `tests/test_ocr_query_limits.py`. They import this app's own packages (`cv2`, `fitz`, `src`), so they
   run in the app's image; on an office that runs apitools the tests gate does that itself, in a
   throwaway container with no network:
   ```bash
   python3 scripts/refactor/plane-tests-lint.py --in-images     # from the repo root
   ```
   (The two API tests above are named there as "not a unit test": they ask a running server.)

Minimal smoke test without modifying tests:

```bash
# With server running
curl -s http://127.0.0.1:8080/health | jq .

# Convert a PDF
curl -f -X POST http://127.0.0.1:8080/pdfToJpeg \
  -F file=@.test_files/pdf_test_files/test.pdf \
  -o out.jpg && file out.jpg

# Upload and query
RESP=$(curl -s -X POST http://127.0.0.1:8080/documentOcr -F file=@.test_files/ocr_test_files/file1.jpg)
FID=$(echo "$RESP" | jq -r .file_hash)
curl -s -X POST http://127.0.0.1:8080/documentJsonQuery \
  -H 'Content-Type: application/json' \
  -d '{"file_id":"'"$FID"'","ocr_json_query":{"action":"find after","action_value":["invoice"],"value_validations":[{"validation_type":"length_greater_than","validation_value":2}],"is_rtl":false}}' | jq .
```


## Troubleshooting

- pdf2image requires poppler (installed via `poppler-utils` on Debian/Ubuntu). If you see "PDFInfoNotInstalledError", install poppler or use the Docker image.
- OCR calls use Google Vision API over HTTP. Without a valid API key, `/documentOcr` will fail on first uncached files. The service caches results in `.storage/ocr_cache/` by MD5, so retries on the same file can hit the cache.
- For production, prefer running via Gunicorn (as the Dockerfile does). The Flask dev server is single-process and not for load.
- Logs are written to `logs/apitools.log` in non-debug mode and to stdout.


## Roadmap (suggested)

- Move the Vision API key to an environment variable (e.g., `GOOGLE_VISION_API_KEY`) and remove hard-coded secrets
- Add an endpoint to return debug drawings generated by the query engine
- Align tests with current API responses and methods; add lightweight pytest suite
- Optional: support local Tesseract as a fallback OCR engine
