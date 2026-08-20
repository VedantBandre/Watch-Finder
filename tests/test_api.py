"""No-quota tests for the FastAPI boundary."""

from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch

from google.genai import errors
from httpx import ASGITransport, AsyncClient
from PIL import Image

from backend.main import analysis_cache, app
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

    async def test_health(self) -> None:
        response = await self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

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
        self.assertEqual(second.json()["candidates"][0]["brand"], "Example")
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


if __name__ == "__main__":
    unittest.main()
