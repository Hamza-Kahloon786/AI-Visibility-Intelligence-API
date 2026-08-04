"""Consistent JSON error format across every endpoint.

Every error response looks like:
    {"error": {"code": "<snake_case_code>", "message": "<human message>", "details": <optional>}}
"""
from __future__ import annotations

from flask import Flask, jsonify
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException


class APIError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        code: str = "bad_request",
        details=None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details

    def to_response(self):
        body = {"error": {"code": self.code, "message": self.message}}
        if self.details is not None:
            body["error"]["details"] = self.details
        return jsonify(body), self.status_code


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def _handle_api_error(err: APIError):
        return err.to_response()

    @app.errorhandler(ValidationError)
    def _handle_validation_error(err: ValidationError):
        details = [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
            for e in err.errors()
        ]
        return (
            jsonify(
                {
                    "error": {
                        "code": "validation_error",
                        "message": "Request body failed validation.",
                        "details": details,
                    }
                }
            ),
            400,
        )

    @app.errorhandler(HTTPException)
    def _handle_http_exception(err: HTTPException):
        return (
            jsonify(
                {
                    "error": {
                        "code": (err.name or "http_error").lower().replace(" ", "_"),
                        "message": err.description or "HTTP error.",
                    }
                }
            ),
            err.code or 500,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected_error(err: Exception):
        app.logger.exception("Unhandled exception while processing request")
        return (
            jsonify(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "An unexpected error occurred.",
                    }
                }
            ),
            500,
        )
