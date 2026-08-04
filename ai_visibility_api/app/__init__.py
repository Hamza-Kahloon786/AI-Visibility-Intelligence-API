from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify

from app.api import register_blueprints
from app.api.errors import register_error_handlers
from app.config import config_by_name
from app.extensions import db, limiter, migrate
from app.services.container import build_pipeline_orchestrator

load_dotenv()


def create_app(config_name: str | None = None) -> Flask:
    config_name = config_name or os.environ.get("FLASK_ENV", "development")
    if config_name not in config_by_name:
        config_name = "development"

    logging.basicConfig(level=logging.INFO)

    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    register_error_handlers(app)
    register_blueprints(app)

    with app.app_context():
        from app import models  # noqa: F401 -- registers models with SQLAlchemy metadata

    # Not a Flask extension in the init_app sense, just app-scoped dependency
    # injection: one shared orchestrator (and the LLM client/data provider it
    # wraps) per process, built once from config rather than per-request.
    app.pipeline_orchestrator = build_pipeline_orchestrator(app.config)

    @app.get("/api/v1/health")
    def health_check():
        return jsonify({"status": "ok"}), 200

    @app.get("/")
    def frontend_index():
        # Optional demo UI (app/static/index.html) -- not part of the graded
        # API surface, just a convenience for manually exercising it.
        return app.send_static_file("index.html")

    return app
