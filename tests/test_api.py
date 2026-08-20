"""No-quota tests for the FastAPI boundary."""

from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch

from google.genai import errors
from httpx import ASGITransport, AsyncClient
from PIL import Image

from backend.main import analysis_cache, app, model_availability
from backend.model_registry import MODEL_OPTIONS
from backend.models import (
    Candidate,
    IdentificationAssessment,
    Observations,
    WatchAnalysis,
)


def sample_image() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (80, 80), "navy").save(output, format="JPEG")
    return output.getvalue()


def sample_analysis() -> WatchAnalysis:
    return WatchAnalysis(
        is_watch=True,
        observations=Observations(
            visible_text=["EXAMPLE"],
            dial="Black dial",
            case="Steel case",
            bezel="Black bezel",
            hands="Three hands",
            complications=[],
            bracelet_or_strap="Steel bracelet",
            condition="Good visible condition",
        ),
        candidates=[
            Candidate(
                brand="Example",
                model="Example Diver",
                reference="unknown",
                confidence="medium",
                matching_evidence=["Black dial"],
                conflicting_evidence=[],
            )
        ],
        identification_assessment=IdentificationAssessment(
            brand="identified",
            family="plausible",
            reference="unresolved",
        ),
        unknowns=["Exact reference"],
        recommended_next_photo="Caseback",
        caution="Reference is unresolved.",
    )


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        analysis_cache.clear()
        model_availability.clear()
        self.client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        )
        self.api_key = patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
        self.api_key.start()

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        self.api_key.stop()
        analysis_cache.clear()
        model_availability.clear()

    async def test_health(self) -> None:
        response = await self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    async def test_models_lists_fallback_order(self) -> None:
        response = await self.client.get("/api/models")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["default"], "auto")
        self.assertEqual(
            [item["id"] for item in response.json()["models"]],
            [option.id for option in MODEL_OPTIONS],
        )
        self.assertTrue(all(item["available"] for item in response.json()["models"]))

    async def test_success_is_cached(self) -> None:
        with patch("backend.main.analyze_image", return_value=sample_analysis()) as analyze:
            first = await self.client.post(
                "/api/analyze",
                files={"image": ("watch.jpg", sample_image(), "image/jpeg")},
            )
            second = await self.client.post(
                "/api/analyze",
                files={"image": ("renamed.jpg", sample_image(), "image/jpeg")},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["X-Cache"], "MISS")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.headers["X-Cache"], "HIT")
        self.assertEqual(second.json()["analysis"]["candidates"][0]["brand"], "Example")
        self.assertEqual(second.json()["model"]["used"], "gemini-3.7-flash")
        analyze.assert_called_once()

    async def test_auto_falls_back_only_after_rate_limit(self) -> None:
        quota_error = errors.ClientError(
            429,
            {"error": {"code": 429, "message": "Please retry in 30s."}},
        )

        def analyze_by_model(_image: bytes, model: str):
            if model == "gemini-3.7-flash":
                raise quota_error
            return sample_analysis()

        with patch("backend.main.analyze_image", side_effect=analyze_by_model) as analyze:
            response = await self.client.post(
                "/api/analyze",
                files={"image": ("watch.jpg", sample_image(), "image/jpeg")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model"]["requested"], "auto")
        self.assertEqual(response.json()["model"]["used"], "gemini-3.6-flash")
        self.assertEqual(
            response.json()["model"]["unavailable"],
            [{"id": "gemini-3.7-flash", "retryAfterSeconds": 30}],
        )
        self.assertEqual(analyze.call_count, 2)

    async def test_explicit_model_does_not_fallback(self) -> None:
        with patch("backend.main.analyze_image", return_value=sample_analysis()) as analyze:
            response = await self.client.post(
                "/api/analyze",
                files={"image": ("watch.jpg", sample_image(), "image/jpeg")},
                data={"model": "gemini-2.5-flash"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model"]["used"], "gemini-2.5-flash")
        self.assertEqual(analyze.call_args.kwargs["model"], "gemini-2.5-flash")

    async def test_unknown_model_is_rejected(self) -> None:
        response = await self.client.post(
            "/api/analyze",
            files={"image": ("watch.jpg", sample_image(), "image/jpeg")},
            data={"model": "made-up-model"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_model")

    async def test_auto_does_not_fallback_on_non_quota_error(self) -> None:
        service_error = errors.ServerError(
            503,
            {"error": {"code": 503, "message": "Service unavailable."}},
        )
        with patch("backend.main.analyze_image", side_effect=service_error) as analyze:
            response = await self.client.post(
                "/api/analyze",
                files={"image": ("watch.jpg", sample_image(), "image/jpeg")},
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "analysis_service_error")
        analyze.assert_called_once()

    async def test_invalid_image(self) -> None:
        response = await self.client.post(
            "/api/analyze",
            files={"image": ("bad.jpg", b"not an image", "image/jpeg")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_image")

    async def test_oversized_image(self) -> None:
        response = await self.client.post(
            "/api/analyze",
            files={"image": ("large.jpg", b"x" * (20 * 1024 * 1024 + 1), "image/jpeg")},
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "image_too_large")

    async def test_rate_limit_with_retry_delay(self) -> None:
        error = errors.ClientError(
            429,
            {
                "error": {
                    "code": 429,
                    "status": "RESOURCE_EXHAUSTED",
                    "message": "Quota exceeded. Please retry in 24.641478824s.",
                }
            },
        )
        with patch("backend.main.analyze_image", side_effect=error):
            response = await self.client.post(
                "/api/analyze",
                files={"image": ("watch.jpg", sample_image(), "image/jpeg")},
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "25")
        self.assertEqual(response.json()["error"]["retryAfterSeconds"], 25)
        self.assertEqual(len(response.json()["error"]["unavailable"]), 4)

    async def test_rate_limit_without_retry_delay(self) -> None:
        error = errors.ClientError(
            429,
            {
                "error": {
                    "code": 429,
                    "status": "RESOURCE_EXHAUSTED",
                    "message": "Daily quota exceeded.",
                }
            },
        )
        with patch("backend.main.analyze_image", side_effect=error):
            response = await self.client.post(
                "/api/analyze",
                files={"image": ("watch.jpg", sample_image(), "image/jpeg")},
            )

        self.assertEqual(response.status_code, 429)
        self.assertNotIn("Retry-After", response.headers)
        self.assertNotIn("retryAfterSeconds", response.json()["error"])
        self.assertEqual(len(response.json()["error"]["unavailable"]), 4)


if __name__ == "__main__":
    unittest.main()
