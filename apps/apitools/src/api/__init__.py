import os
import time

import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from src.api.ocr_api import get_document_ocr, perform_ocr_json_query, document_exists
from src.ocr_core import ocr_cache
from src.api.pdf_to_jpeg import optimized_pdf_to_jpeg
from src.api.doc_gen_api import generate_document, generate_sample
from src.api import documents_api as docs
from src.utils.storage import storage_path
from src.utils.logging_config import (
    get_logger, log_request_start, log_request_end,
    set_request_context, clear_request_context
)

# Environment configuration
DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

# Initialize Sentry for error tracking
SENTRY_DSN = os.getenv('SENTRY_DSN')
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[FlaskIntegration()],
        environment=os.getenv('SENTRY_ENVIRONMENT', 'production'),
        release=os.getenv('SENTRY_RELEASE', '0.5.3'),
        traces_sample_rate=0.1,  # 10% of transactions for performance monitoring
        send_default_pii=False,  # Don't send personally identifiable information
    )

# Get the application logger
logger = get_logger('apitools.api')

def create_app():
    app = Flask(__name__)
    
    # Configuration
    app.config['DEBUG'] = DEBUG
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size
    
    # Enable CORS for API endpoints
    CORS(app)
    
    # Request middleware
    @app.before_request
    def before_request():
        request_id, start_time = log_request_start(logger, request)
        g.start_time = start_time
        g.request_id = request_id
        ocr_cache.begin_request()

    @app.after_request
    def after_request(response):
        # SHARED-CACHE OUTAGE -> 503, IN ONE PLACE.
        # Every OCR route wraps its body in `except Exception: return ..., 500`, so an
        # OcrCacheUnavailable raised deep in ocr_cache would surface as a 500 -- which
        # haproxy does NOT list in `retry-on` and which reads like an application bug.
        # Rewriting here instead of editing each route means routes added later are
        # covered automatically, and it is a status rewrite rather than an exception
        # path, so the existing error bodies and logging are untouched.
        # 503 is load-bearing: `be_split`/`be_localfile` already retry it, so the
        # request is redispatched to the peer that CAN reach the shared cache and the
        # caller usually never sees a failure at all.
        # Consumed unconditionally so the thread-local never leaks into the next
        # request served by this (reused) sync worker thread.
        shared_cache_failed = ocr_cache.failed_this_request()
        if shared_cache_failed and response.status_code >= 500:
            response.status_code = 503
            response.headers['X-Shared-Cache'] = 'unavailable'
            response.headers['Retry-After'] = '2'

        log_request_end(logger, response.status_code, g.start_time)

        # Add request ID to response headers for tracing
        response.headers['X-Request-ID'] = g.get('request_id', '-')
        
        # Security headers
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        return response
    
    # Error handlers
    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        logger.warning(f"HTTP Exception: {e.code} - {e.description}")
        return jsonify({
            'error': e.description,
            'status_code': e.code
        }), e.code
    
    @app.errorhandler(Exception)
    def handle_general_exception(e):
        logger.error(f"Unhandled Exception: {str(e)}", exc_info=True)
        return jsonify({
            'error': 'Internal server error',
            'status_code': 500
        }), 500
    
    # Routes
    @app.route('/', methods=['GET'])
    def home():
        return jsonify({
            'service': 'API Tools',
            'version': '0.5.3',
            'status': 'healthy'
        })
    
    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint for monitoring"""
        try:
            # Check storage path accessibility
            storage_accessible = os.path.exists(storage_path()) and os.access(storage_path(), os.W_OK)
            
            return jsonify({
                'status': 'healthy',
                'storage_accessible': storage_accessible,
                'timestamp': time.time()
            }), 200
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return jsonify({
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': time.time()
            }), 503
    
    @app.route('/readyz', methods=['GET'])
    def readyz():
        """LOAD-BALANCER READINESS — 'can this instance serve CORRECT results?'

        Distinct from /health ('is the process alive') and from the gunicorn master's
        health sidecar on :8082 ('is the master accepting'). This one answers the
        question that actually matters for a two-instance deployment: is the SHARED
        Postgres OCR cache reachable from here? An instance that cannot reach it either
        diverges silently (the pre-2026-08-11 behaviour, 1,171 orphaned results) or
        503s everything -- either way haproxy should stop sending it traffic, and this
        is how it finds out. haproxy's `http-check` for both backends points here.

        Cheap and unblockable by design: the normal answer is a read of a tmpfs marker
        that real traffic keeps warm. Only when nothing has touched the cache for
        OCR_CACHE_PROBE_TTL does it dial an independent, timeout-bounded probe -- never
        the shared connection, so a busy instance is never mistaken for a dead one, and
        never the storage bind mount, which is why /health is unsuitable for this."""
        ok, detail = ocr_cache.status()
        detail['status'] = 'ready' if ok else 'not_ready'
        detail['timestamp'] = time.time()
        return jsonify(detail), (200 if ok else 503)

    @app.route('/pdfToJpeg', methods=['POST'])
    def upload_pdf():
        try:
            return optimized_pdf_to_jpeg(request)
        except Exception as e:
            logger.error(f"PDF to JPEG conversion failed: {str(e)}", exc_info=True)
            return jsonify({'error': 'PDF processing failed'}), 500
    
    @app.route('/documentOcr', methods=['POST'])
    def upload_document():
        try:
            return get_document_ocr(request)
        except Exception as e:
            logger.error(f"Document OCR failed: {str(e)}", exc_info=True)
            return jsonify({'error': 'OCR processing failed ' + str(e)}), 500
    
    @app.route('/documentJsonQuery', methods=['POST'])
    def document_json_query():
        try:
            # Run the query (with optional drawing controlled inside)
            resp = perform_ocr_json_query(request)
            if isinstance(resp, tuple):
                return resp

            # If caller asked for an image, serve the drawing image file
            fmt = request.args.get('format', 'json').lower()
            draw_requested = str(request.args.get('draw', 'false')).lower() in ('1', 'true', 'yes', 'y')
            if draw_requested and fmt in ('image', 'img'):
                from flask import send_file
                import mimetypes
                drawing_path = resp.get('drawing_path')
                if not drawing_path:
                    return jsonify({'error': 'Drawing not available'}), 400
                mime = mimetypes.guess_type(drawing_path)[0] or 'image/jpeg'
                return send_file(drawing_path, mimetype=mime, as_attachment=False)

            return resp
        except Exception as e:
            logger.error(f"Document JSON query failed: {str(e)}", exc_info=True)
            return jsonify({'error': f'JSON query processing failed: {str(e)}'}), 500

    def _ensure_draw_base(ocr_object):
        """Ensure a coordinate-aligned base image to draw on, even for cache entries
        written before the text-layer raster existed (image_path missing)."""
        od = ocr_object.ocr_data.ocr_dict
        if not od.get('image_path') or not os.path.exists(od.get('image_path') or ''):
            src = od.get('original_file_path')
            if src and os.path.exists(src):
                if src.lower().endswith('.pdf'):
                    from src.ocr_core.pdf_textlayer import _render_stacked
                    verts = ocr_object.ocr_data.ocr_dict['textAnnotations'][0]['boundingPoly']['vertices']
                    pw = max(v.get('x', 0) for v in verts); ph = max(v.get('y', 0) for v in verts)
                    rendered = _render_stacked(src, pw, ph)
                    if rendered:
                        od['image_path'] = rendered
                else:
                    od['image_path'] = src            # images: the file is the base

    @app.route('/documentDraw', methods=['POST'])
    def document_draw():
        """Run several queries on one document and draw ALL their matches on a single
        image, so every extraction is visualised together. Body:
          {"file_id": "<hash>", "queries": [{"label": "amount", "ocr_json_query": {...}}, ...]}
        Returns the annotated image (?format=image, default) or JSON with drawing_path
        and each query's result. Uses the engine's own OcrDrawings — the same drawing
        the query engine produces with draw=true, accumulated across queries."""
        try:
            from src.ocr_core.ocr_object import OcrObject
            body = request.json or {}
            file_id = body.get('file_id')
            queries = body.get('queries') or []
            if not file_id or not queries:
                return jsonify({'error': 'file_id and queries[] are required'}), 400
            ocr_engine = request.args.get('ocr_engine') or body.get('ocr_engine') or None
            ocr_object = OcrObject.from_file_id(file_id, ocr_engine=ocr_engine)
            _ensure_draw_base(ocr_object)
            ocr_object.query.draw = True                      # accumulate on one image
            results = []
            for q in queries:
                spec = q.get('ocr_json_query') or q
                try:
                    val = ocr_object.json_query.json_query(spec, match_index=q.get('match_index', 0))
                except Exception as qe:
                    val = None
                    logger.warning(f"draw query failed ({q.get('label')}): {qe}")
                results.append({'label': q.get('label'), 'result': val})
            ocr_object.drawing.save_drawing_image()
            drawing_path = os.path.abspath(ocr_object.drawing.drawing_image_path)
            if str(request.args.get('format', 'image')).lower() in ('image', 'img'):
                from flask import send_file
                import mimetypes
                mime = mimetypes.guess_type(drawing_path)[0] or 'image/png'
                return send_file(drawing_path, mimetype=mime, as_attachment=False)
            return jsonify({'file_id': file_id, 'drawing_path': drawing_path, 'results': results})
        except FileNotFoundError:
            return jsonify({'error': 'file_not_found'}), 404
        except Exception as e:
            logger.error(f"documentDraw failed: {str(e)}", exc_info=True)
            return jsonify({'error': f'draw failed: {str(e)}'}), 500

    @app.route('/documentOcrDraw', methods=['GET', 'POST'])
    def document_ocr_draw():
        """Draw EVERY OCR token (word box + recognised text tag) on the document — the
        raw character-recognition map, independent of any query. ?file_id=<hash> (or
        POST {"file_id": ...}); returns the annotated image."""
        try:
            from src.ocr_core.ocr_object import OcrObject
            body = request.json if request.is_json else {}
            file_id = request.args.get('file_id') or (body or {}).get('file_id')
            if not file_id:
                return jsonify({'error': 'file_id is required'}), 400
            ocr_engine = request.args.get('ocr_engine') or (body or {}).get('ocr_engine') or None
            ocr_object = OcrObject.from_file_id(file_id, ocr_engine=ocr_engine)
            _ensure_draw_base(ocr_object)
            # dedicated drawing folder: the per-image drawing file is shared mutable
            # state — a concurrent /documentDraw (the marked-extraction pane loading
            # in parallel) writes the same path mid-read otherwise
            tokens_dir = os.path.join(ocr_object.drawing.DRAWING_IMAGES_FOLDER, 'tokens')
            os.makedirs(tokens_dir, exist_ok=True)
            ocr_object.drawing.DRAWING_IMAGES_FOLDER = tokens_dir  # instance shadows class
            ocr_object.drawing.draw_all_annotations(save=True)
            drawing_path = os.path.abspath(ocr_object.drawing.drawing_image_path)
            from flask import send_file
            import mimetypes
            mime = mimetypes.guess_type(drawing_path)[0] or 'image/png'
            return send_file(drawing_path, mimetype=mime, as_attachment=False)
        except FileNotFoundError:
            return jsonify({'error': 'file_not_found'}), 404
        except Exception as e:
            logger.error(f"documentOcrDraw failed: {str(e)}", exc_info=True)
            return jsonify({'error': f'ocr draw failed: {str(e)}'}), 500

    @app.route('/documentImage', methods=['GET'])
    def document_image():
        """The document's own page image, CLEAN — no boxes, no tags. ?file_id=<hash>.

        The two draw endpoints above both render onto this same base image, so the
        bytes were always here; there was simply no way to ask for them undrawn.
        That gap is why INDOX's document page could show the two overlays but not the
        document itself: a real row's original is an external drive.google.com URL the
        browser cannot embed, while apitools has held the rasterised page all along,
        keyed by the very hash the row already stores in API_TOOLS_ID.

        Read-only and side-effect free — unlike the draw endpoints it writes nothing
        into the shared drawing folder, so it cannot race a concurrent /documentDraw.
        """
        try:
            from src.ocr_core.ocr_object import OcrObject
            file_id = request.args.get('file_id')
            if not file_id:
                return jsonify({'error': 'file_id is required'}), 400
            ocr_engine = request.args.get('ocr_engine') or None
            ocr_object = OcrObject.from_file_id(file_id, ocr_engine=ocr_engine)
            image_path = os.path.abspath(ocr_object.ocr_data.image_filepath)
            if not os.path.exists(image_path):
                # OCR json is cached but the rasterised page is gone (cache eviction).
                # Say so precisely rather than 500ing on the send_file.
                return jsonify({'error': 'image_not_found'}), 404
            from flask import send_file
            import mimetypes
            mime = mimetypes.guess_type(image_path)[0] or 'image/jpeg'
            return send_file(image_path, mimetype=mime, as_attachment=False)
        except FileNotFoundError:
            return jsonify({'error': 'file_not_found'}), 404
        except Exception as e:
            logger.error(f"documentImage failed: {str(e)}", exc_info=True)
            return jsonify({'error': f'document image failed: {str(e)}'}), 500

    @app.route('/docGen', methods=['POST'])
    def doc_gen():
        try:
            return generate_document(request)
        except (ValueError, TypeError) as e:
            return jsonify({"error": "bad_model", "message": str(e)}), 400

    @app.route('/docGen/sample', methods=['GET'])
    def doc_gen_sample():
        try:
            return generate_sample(request)
        except (ValueError, TypeError, KeyError) as e:
            return jsonify({"error": "bad_request", "message": str(e)}), 400

    # ── /documents — business-document management (CRUD + lifecycle, DB-backed) ──
    @app.route('/documents', methods=['GET', 'POST'])
    def documents_root():
        return docs.create(request) if request.method == 'POST' else docs.list_docs(request)

    @app.route('/documents/verify', methods=['GET'])
    def documents_verify():
        return docs.verify(request)

    @app.route('/documents/<doc_id>/signature', methods=['GET'])
    def documents_signature(doc_id):
        return docs.signature_doc(doc_id)

    @app.route('/reports/pcn874', methods=['GET'])
    def report_pcn874():
        return docs.pcn874_report(request)

    # ── single-business setup + entities ──
    @app.route('/business', methods=['GET', 'PUT', 'POST'])
    def business():
        return docs.business_save(request) if request.method in ('PUT', 'POST') else docs.business_get(request)

    @app.route('/customers', methods=['GET', 'POST'])
    def customers_root():
        return docs.customers(request)

    @app.route('/customers/<rid>', methods=['GET', 'PATCH', 'DELETE'])
    def customers_one(rid):
        return docs.customers(request, rid)

    @app.route('/items', methods=['GET', 'POST'])
    def items_root():
        return docs.items(request)

    @app.route('/items/<rid>', methods=['GET', 'PATCH', 'DELETE'])
    def items_one(rid):
        return docs.items(request, rid)

    @app.route('/documents/consent', methods=['POST'])
    def documents_consent():
        return docs.consent(request)

    @app.route('/documents/<doc_id>', methods=['GET', 'PATCH'])
    def documents_one(doc_id):
        return docs.update_doc(doc_id, request) if request.method == 'PATCH' else docs.get_doc(doc_id)

    @app.route('/documents/<doc_id>/issue', methods=['POST'])
    def documents_issue(doc_id):
        return docs.issue_doc(doc_id, request)

    @app.route('/documents/<doc_id>/download', methods=['GET'])
    def documents_download(doc_id):
        return docs.download_doc(doc_id, request)

    @app.route('/documents/<doc_id>/send', methods=['POST'])
    def documents_send(doc_id):
        return docs.send_doc(doc_id, request)

    @app.route('/documents/<doc_id>/pay', methods=['POST'])
    def documents_pay(doc_id):
        return docs.pay_doc(doc_id, request)

    @app.route('/documents/<doc_id>/cancel', methods=['POST'])
    def documents_cancel(doc_id):
        return docs.cancel_doc(doc_id, request)

    @app.route('/documents/<doc_id>/convert', methods=['POST'])
    def documents_convert(doc_id):
        return docs.convert_doc(doc_id, request)

    @app.route('/documents/<doc_id>/events', methods=['GET'])
    def documents_events(doc_id):
        return docs.events_doc(doc_id)

    @app.route('/documents/<doc_id>/allocation', methods=['POST'])
    def documents_allocation(doc_id):
        return docs.allocation_doc(doc_id, request)

    @app.route('/docExists', methods=['GET', 'POST'])
    def doc_exists():
        try:
            return document_exists(request)
        except Exception as e:
            logger.error(f"Document exists check failed: {str(e)}", exc_info=True)
            return jsonify({'error': 'Document exists check failed'}), 500

    return app


# Create app instance
app = create_app()

if __name__ == '__main__':
    # This should only be used for development
    logger.warning("Running in development mode. Use Gunicorn for production!")
    app.run(host="0.0.0.0", port=8080, debug=DEBUG)
