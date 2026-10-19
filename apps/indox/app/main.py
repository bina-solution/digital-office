"""Standalone Flask entrypoint for the Incoming Documents service.

Replaces the feature-flagged blueprint that used to live inside apitools.
"""
from __future__ import annotations

import logging
import os
import time

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request
from flask_compress import Compress
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

load_dotenv()

import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

from incoming_documents.api import create_blueprint as _create_idoc_bp
from incoming_documents.kafka import ConfluentKafkaConsumer, NullKafkaConsumer
from incoming_documents.repo_factory import (
    default_kafka_admin,
    default_kafka_producer,
)
from incoming_documents.webapp_blueprint import (
    create_webapp_blueprint as _create_idoc_webapp_bp,
)


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("incoming_documents.main")

DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[FlaskIntegration()],
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        release=os.getenv("SENTRY_RELEASE", "0.1.0"),
        traces_sample_rate=0.1,
        send_default_pii=False,
    )


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["DEBUG"] = DEBUG
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
    CORS(app)
    # Compression (platform Fix 3, applied per-app — see platform-base/console/app.py for the
    # matching console-side fix). The SPA's built JS/CSS (INCOMING_DOCS_WEBAPP_DIST) and this
    # blueprint's JSON responses were never compressed. Safe for the SSE route in
    # incoming_documents/api/__init__.py (mimetype="text/event-stream"): flask-compress only acts
    # on responses whose mimetype is in COMPRESS_MIMETYPES, and text/event-stream was never on
    # that default list, so the stream is skipped before COMPRESS_STREAMS even applies.
    Compress(app)

    @app.before_request
    def _before():
        g.start_time = time.time()

    @app.after_request
    def _after(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        # SAMEORIGIN (not DENY) so the console can embed the SPA in a
        # same-origin iframe at console.localhost/a/incoming/ (the console
        # reverse-proxies this service under its own origin). DENY would block
        # all framing and leave the embed blank.
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    @app.errorhandler(HTTPException)
    def _http_err(e):
        return jsonify({"error": e.description, "status_code": e.code}), e.code

    @app.errorhandler(Exception)
    def _err(e):
        logger.error("Unhandled exception: %s", e, exc_info=True)
        return jsonify({"error": "Internal server error", "status_code": 500}), 500

    # NOTE: the app root ``/`` is served by the webapp blueprint (the SPA
    # index.html). The former JSON ``home`` route was removed so the SPA can be
    # reached at the root — use ``/health`` for a liveness probe.

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "healthy", "timestamp": time.time()}), 200

    kafka_bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    consumer = (
        ConfluentKafkaConsumer(bootstrap_servers=kafka_bootstrap)
        if kafka_bootstrap
        else NullKafkaConsumer()
    )

    app.register_blueprint(
        _create_idoc_bp(
            kafka_producer=default_kafka_producer(),
            kafka_admin=default_kafka_admin(),
            kafka_consumer=consumer,
        )
    )
    app.register_blueprint(_create_idoc_webapp_bp())
    logger.info("incoming_documents blueprints mounted")

    return app


app = create_app()
application = app


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=DEBUG)
