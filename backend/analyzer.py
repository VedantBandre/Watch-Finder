"""Image preparation and Gemini integration for watch analysis."""

from __future__ import annotations

import base64
import io

from google import genai
from PIL import Image, ImageOps

from backend.models import WatchAnalysis


DEFAULT_MODEL = "gemini-3.7-flash"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
PROMPT_VERSION = "1"
SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


PROMPT = """
You are inspecting ONE watch photograph. The images after this instruction are
the original photo and, when present, detail crops of that same photo.

Work evidence-first:
1. Decide whether the subject is a watch.
2. Record only directly visible observations before identifying it.
3. Transcribe only text that is genuinely legible. Do not silently correct it.
4. Produce no more than three plausible candidates, ranked most likely first.
5. Do not invent an exact reference. Use "unknown" unless the visible evidence
   strongly distinguishes it from similar references.
6. Put observed matches and contradictions in separate lists.
7. Use "unknown" for facts the photo cannot establish, including movement,
   material, dimensions, authenticity, production year, and reference.
8. If variants cannot be distinguished, state what additional photo would help
   (for example caseback, clasp, crown side, or between the lugs).
9. Assess identification separately at brand, family, and exact-reference level.
   Mark a reference "supported" only if this image visibly distinguishes it
   from similar references; otherwise mark it "unresolved", even when one
   candidate is more likely than the others.

Be concise, skeptical, and useful to a watch specialist. Return only data that
fits the supplied JSON schema.
""".strip()


def _decode_image(image_bytes: bytes) -> Image.Image:
    if not image_bytes:
        raise ValueError("Image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Image is larger than 20 MB; resize it before testing.")

    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            image_format = source.format
            source.load()
            if image_format not in SUPPORTED_IMAGE_FORMATS:
                supported = ", ".join(sorted(SUPPORTED_IMAGE_FORMATS))
                raise ValueError(f"Unsupported image format. Use one of: {supported}.")
            return ImageOps.exif_transpose(source).convert("RGB")
    except ValueError:
        raise
    except (OSError, SyntaxError) as exc:
        raise ValueError(
            "Could not read the image. Use a valid JPEG, PNG, or WebP file."
        ) from exc


def _encode_jpeg(image: Image.Image, max_side: int) -> str:
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90, optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def _image_inputs(image_bytes: bytes, include_crop: bool) -> list[dict[str, str]]:
    image = _decode_image(image_bytes)
    inputs: list[dict[str, str]] = [
        {"type": "text", "text": "Original photograph:"},
        {
            "type": "image",
            "data": _encode_jpeg(image, max_side=1800),
            "mime_type": "image/jpeg",
        },
    ]

    if include_crop:
        width, height = image.size
        crop_width = max(1, int(width * 0.72))
        crop_height = max(1, int(height * 0.72))
        left = (width - crop_width) // 2
        top = (height - crop_height) // 2
        center = image.crop((left, top, left + crop_width, top + crop_height))
        inputs.extend(
            [
                {"type": "text", "text": "Center detail crop of the same photograph:"},
                {
                    "type": "image",
                    "data": _encode_jpeg(center, max_side=1800),
                    "mime_type": "image/jpeg",
                },
            ]
        )

    return inputs


def request_analysis_text(
    image_bytes: bytes,
    model: str = DEFAULT_MODEL,
    include_crop: bool = True,
) -> str:
    """Send an image to Gemini and return its raw structured-response text."""
    inputs = [{"type": "text", "text": PROMPT}]
    inputs.extend(_image_inputs(image_bytes, include_crop=include_crop))

    client = genai.Client()
    response = client.interactions.create(
        model=model,
        input=inputs,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": WatchAnalysis.model_json_schema(),
        },
    )
    return response.output_text


def analyze_image(
    image_bytes: bytes,
    model: str = DEFAULT_MODEL,
    include_crop: bool = True,
) -> WatchAnalysis:
    """Analyze an image and return a validated, candidate-limited result."""
    analysis = WatchAnalysis.model_validate_json(
        request_analysis_text(image_bytes, model=model, include_crop=include_crop)
    )
    if len(analysis.candidates) > 3:
        analysis.candidates = analysis.candidates[:3]
    return analysis
