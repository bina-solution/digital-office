# apitools — Project Snapshot

> Captured during phase one context collection. Do not edit by hand; refresh by re-running phase one.

## Identity
- Service name: `apitools`
- Version: `0.5.3` (per `src/api/__init__.py` and `Dockerfile`/`run.py` is `0.5.2`; mismatch noted)
- Runtime: Python 3.11+ (Docker image: 3.12), Flask + Gunicorn
- Entry: `run.py` → `src.api:app`
- Container: `apitools-${DEPLOYMENT_NAME}` exposed at `apitools.hacohen.bina-solutions.co.il`

## Existing HTTP API (today)
| Method | Path                   | Purpose |
|--------|------------------------|---------|
| GET    | `/`                    | Service info |
| GET    | `/health`              | Health/storage check |
| POST   | `/pdfToJpeg`           | PDF → stitched JPEG |
| POST   | `/documentOcr`         | Upload + OCR (returns `file_id` = MD5) |
| POST   | `/documentJsonQuery`   | Position-based query over cached OCR |
| GET    | `/docExists`           | Check OCR cache for `file_id` |

OCR engine selection: env `OCR_ENGINE=google|local` (default `google`); per-request `?ocr_engine=` disables cache.

## Source Tree (relevant subset)
```
apitools/
  run.py                        # WSGI entry, dotenv
  gunicorn.conf.py              # Production server config
  Dockerfile                    # poppler + tesseract + python deps
  docker-compose.yml            # standalone compose
  requirements.txt
  app.yaml
  README.md / readme.md
  src/
    __init__.py
    api/
      __init__.py               # Flask app factory + route registrations
      ocr_api.py                # /documentOcr, /documentJsonQuery, /docExists
      pdf_to_jpeg.py            # /pdfToJpeg
    ocr_core/                   # OCR data model + Google Vision + local Tesseract
      ocr_processor.py
      local_ocr_engine.py
      ocr_data.py / ocr_object.py / ocr_query.py / ocr_json_query.py
      models/                   # bounding boxes, points, positions
      validations/
      exceptions/
    pdf_core/
      pdf_to_jpg.py
    image_core/
      image_utils.py
    utils/
      storage.py logging_config.py hash.py file_utils.py deskew.py
      fuzzy_comparison.py rotation_calc.py web_view.py ocr.py image_utils.py
    scraps/                     # experimental, ignore
    incoming_documents/         # ← THIS PROJECT (new)
      plan.txt
      context-collection/       # phase 1 artifacts
```

## What is NOT in apitools today (to be added by this project)
- No persistence layer beyond on-disk OCR cache.
- No Google Sheets client, no Supabase client, no Kafka client.
- No notion of a "document repo" / "document repository" abstraction.
- No webhook for batch upsert / batch get of document records.
- No async background workers (Gunicorn sync workers only).

## Environment variables already in use
- `FLASK_DEBUG`, `PORT`, `OCR_ENGINE`, `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_RELEASE`
- Storage path via `src/utils/storage.py` (defaults to `.storage/` under cwd; mounted volume in Docker)

## Dependencies (high-level — see requirements.txt)
- Flask, flask-cors, gunicorn
- pdf2image, opencv-python, Pillow, numpy
- pytesseract (local OCR), requests (Google Vision REST)
- sentry-sdk[flask]
- python-dotenv
