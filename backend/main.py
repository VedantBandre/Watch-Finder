"""FastAPI entry point for the watch analysis service."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from collections import OrderedDict
from threading import Lock

from dotenv import load_dotenv
from fastapi import FastAPI, File, Response, UploadFile
from fastapi.responses import JSONResponse
from google.genai import errors
from pydantic import ValidationError

from backend.analyzer import (
    DEFAULT_MODEL,
    MAX_IMAGE_BYTES,
    PROMPT_VERSION,
    analyze_image,
)
from backend.models import WatchAnalysis


load_dotenv()

logger = logging.getLogger(__name__)
app = FastAPI(title="ChronoDesk Watch Analyzer", version="0.1.0")

_RETRY_DELAY_PATTERN = re.compile(
    r"retry\s+in\s+([0-9]+(?:\.[0-9]+)?)s",
    flags=re.IGNORECASE,
)


class AnalysisCache:
    """Small thread-safe LRU cache for successful analysis results."""

    def __init__(self, max_size: int = 32) -> None:
        self.max_size = max_size
        self._items: OrderedDict[str, WatchAnalysis] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> WatchAnalysis | None:
        with self._lock:
            result = self._items.get(key)
            if result is None:
                return None
            self._items.move_to_end(key)
            return result.model_copy(deep=True)

    def set(self, key: str, result: WatchAnalysis) -> None:
        with self._lock:
            self._items[key] = result.model_copy(deep=True)
            self._items.move_to_end(key)
            while len(self._items) > self.max_size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


analysis_cache = AnalysisCache(max_size=32)


def _cache_key(image_bytes: bytes, model: str) -> str:
    digest = hashlib.sha256()
    digest.update(image_bytes)
    digest.update(b"\0")
    digest.update(model.encode("utf-8"))
    digest.update(b"\0")
    digest.update(PROMPT_VERSION.encode("utf-8"))
    return digest.hexdigest()


def _retry_after_seconds(message: str | None) -> int | None:
    if not message:
        return None
    match = _RETRY_DELAY_PATTERN.search(message)
    if not match:
        return None
    return max(1, math.ceil(float(match.group(1))))


def _error_response(
    status_code: int,
    code: str,
    message: str,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    error: dict[str, str | int] = {"code": code, "message": message}
    headers: dict[str, str] = {}
    if retry_after_seconds is not None:
        error["retryAfterSeconds"] = retry_after_seconds
        headers["Retry-After"] = str(retry_after_seconds)
    return JSONResponse(
        status_code=status_code,
        content={"error": error},
        headers=headers,
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyze", response_model=WatchAnalysis)
def analyze_watch(response: Response, image: UploadFile = File(...)):
    image_bytes = image.file.read(MAX_IMAGE_BYTES + 1)
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return _error_response(
            413,
            "image_too_large",
            "The image is larger than 20 MB.",
        )

    if not os.getenv("GEMINI_API_KEY"):
        logger.error("GEMINI_API_KEY is not configured")
        return _error_response(
            500,
            "configuration_error",
            "The analysis service is not configured.",
        )

    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    key = _cache_key(image_bytes, model)
    cached = analysis_cache.get(key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached

    try:
        result = analyze_image(image_bytes, model=model)
    except ValueError as exc:
        return _error_response(400, "invalid_image", str(exc))
    except ValidationError:
        logger.exception("Gemini returned an invalid structured response")
        return _error_response(
            502,
            "invalid_model_response",
            "The analysis service returned an invalid response.",
        )
    except errors.ClientError as exc:
        if exc.code == 429:
            retry_after = _retry_after_seconds(exc.message)
            logger.warning("Gemini rate limit reached; retry after %s", retry_after)
            return _error_response(
                429,
                "rate_limited",
                "Gemini's free quota is temporarily busy.",
                retry_after_seconds=retry_after,
            )
        logger.exception("Gemini rejected the analysis request")
        return _error_response(
            502,
            "analysis_service_error",
            "The analysis service could not process the image.",
        )
    except errors.ServerError:
        logger.exception("Gemini service error")
        return _error_response(
            502,
            "analysis_service_error",
            "The analysis service is temporarily unavailable.",
        )
    except Exception:
        logger.exception("Unexpected watch analysis failure")
        return _error_response(
            500,
            "internal_error",
            "An unexpected error occurred while analyzing the image.",
        )

    analysis_cache.set(key, result)
    response.headers["X-Cache"] = "MISS"
    return result
