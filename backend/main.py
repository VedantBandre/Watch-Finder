"""FastAPI entry point for the watch analysis service."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import time
from collections import OrderedDict
from threading import Lock

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Response, UploadFile
from fastapi.responses import JSONResponse
from google.genai import errors
from pydantic import ValidationError

from backend.analyzer import (
    MAX_IMAGE_BYTES,
    PROMPT_VERSION,
    analyze_image,
)
from backend.model_registry import AUTO_MODEL, MODEL_BY_ID, MODEL_OPTIONS
from backend.models import (
    AnalysisModelMetadata,
    AnalyzeResponse,
    ModelOptionStatus,
    ModelsResponse,
    UnavailableModel,
    WatchAnalysis,
)


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


class ModelAvailability:
    """Track quota-limited models for the lifetime of this backend process."""

    def __init__(self) -> None:
        self._blocked_until: dict[str, float | None] = {}
        self._lock = Lock()

    def mark_unavailable(self, model: str, retry_after_seconds: int | None) -> None:
        blocked_until = (
            time.monotonic() + retry_after_seconds
            if retry_after_seconds is not None
            else None
        )
        with self._lock:
            self._blocked_until[model] = blocked_until

    def mark_available(self, model: str) -> None:
        with self._lock:
            self._blocked_until.pop(model, None)

    def snapshot(self) -> dict[str, int | None]:
        now = time.monotonic()
        with self._lock:
            expired = [
                model
                for model, blocked_until in self._blocked_until.items()
                if blocked_until is not None and blocked_until <= now
            ]
            for model in expired:
                self._blocked_until.pop(model)
            return {
                model: (
                    None
                    if blocked_until is None
                    else max(1, math.ceil(blocked_until - now))
                )
                for model, blocked_until in self._blocked_until.items()
            }

    def clear(self) -> None:
        with self._lock:
            self._blocked_until.clear()


model_availability = ModelAvailability()


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
    unavailable: list[UnavailableModel] | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    headers: dict[str, str] = {}
    if retry_after_seconds is not None:
        error["retryAfterSeconds"] = retry_after_seconds
        headers["Retry-After"] = str(retry_after_seconds)
    if unavailable is not None:
        error["unavailable"] = [
            item.model_dump(by_alias=True, exclude_none=True) for item in unavailable
        ]
    return JSONResponse(
        status_code=status_code,
        content={"error": error},
        headers=headers,
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _unavailable_models() -> list[UnavailableModel]:
    unavailable = model_availability.snapshot()
    return [
        UnavailableModel(id=option.id, retry_after_seconds=unavailable[option.id])
        for option in MODEL_OPTIONS
        if option.id in unavailable
    ]


@app.get("/api/models", response_model=ModelsResponse, response_model_exclude_none=True)
def models() -> ModelsResponse:
    unavailable = model_availability.snapshot()
    return ModelsResponse(
        default=AUTO_MODEL,
        models=[
            ModelOptionStatus(
                id=option.id,
                label=option.label,
                priority=option.priority,
                available=option.id not in unavailable,
                retry_after_seconds=unavailable.get(option.id),
            )
            for option in MODEL_OPTIONS
        ],
    )


def _success_response(
    analysis: WatchAnalysis,
    requested: str,
    used: str,
) -> AnalyzeResponse:
    return AnalyzeResponse(
        analysis=analysis,
        model=AnalysisModelMetadata(
            requested=requested,
            used=used,
            unavailable=_unavailable_models(),
        ),
    )


@app.post(
    "/api/analyze",
    response_model=AnalyzeResponse,
    response_model_exclude_none=True,
)
def analyze_watch(
    response: Response,
    image: UploadFile = File(...),
    model: str = Form(AUTO_MODEL),
):
    if model != AUTO_MODEL and model not in MODEL_BY_ID:
        return _error_response(
            400,
            "invalid_model",
            "Choose Auto or one of the supported Gemini models.",
        )

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

    requested_models = (
        [option.id for option in MODEL_OPTIONS]
        if model == AUTO_MODEL
        else [model]
    )
    blocked = model_availability.snapshot()
    available_models = [item for item in requested_models if item not in blocked]

    for candidate_model in available_models:
        cached = analysis_cache.get(_cache_key(image_bytes, candidate_model))
        if cached is not None:
            response.headers["X-Cache"] = "HIT"
            return _success_response(cached, model, candidate_model)

    for candidate_model in available_models:
        try:
            result = analyze_image(image_bytes, model=candidate_model)
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
                model_availability.mark_unavailable(candidate_model, retry_after)
                logger.warning(
                    "Gemini model %s reached its quota; retry after %s",
                    candidate_model,
                    retry_after,
                )
                if model == AUTO_MODEL:
                    continue
                unavailable = _unavailable_models()
                return _error_response(
                    429,
                    "rate_limited",
                    "The selected Gemini model has reached its free quota.",
                    retry_after_seconds=retry_after,
                    unavailable=unavailable,
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

        model_availability.mark_available(candidate_model)
        analysis_cache.set(_cache_key(image_bytes, candidate_model), result)
        response.headers["X-Cache"] = "MISS"
        return _success_response(result, model, candidate_model)

    unavailable = _unavailable_models()
    retry_delays = [
        item.retry_after_seconds
        for item in unavailable
        if item.retry_after_seconds is not None
    ]
    return _error_response(
        429,
        "rate_limited",
        "All available Gemini models have reached their free quota.",
        retry_after_seconds=min(retry_delays) if retry_delays else None,
        unavailable=unavailable,
    )
