#!/usr/bin/env python3
"""Run a structured, evidence-first watch analysis with Gemini."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from google import genai
from PIL import Image, ImageOps
from pydantic import BaseModel, Field, ValidationError


DEFAULT_MODEL = "gemini-3.7-flash"
MAX_IMAGE_BYTES = 20 * 1024 * 1024


class Observations(BaseModel):
    visible_text: list[str] = Field(
        description="Text actually legible in the image; never corrected or guessed."
    )
    dial: str = Field(description="Observed dial color, finish, indices, and layout.")
    case: str = Field(description="Observed case shape, color, and visible details.")
    bezel: str = Field(description="Observed bezel style, markings, and color.")
    hands: str = Field(description="Observed hand shapes, colors, and lume.")
    complications: list[str] = Field(description="Only complications visible in the image.")
    bracelet_or_strap: str = Field(description="Observed bracelet or strap details.")
    condition: str = Field(description="Only clearly visible condition notes.")


class Candidate(BaseModel):
    brand: str
    model: str
    reference: str = Field(
        description="Exact reference only if strongly supported; otherwise 'unknown'."
    )
    confidence: Literal["low", "medium", "high"]
    matching_evidence: list[str]
    conflicting_evidence: list[str]


class IdentificationAssessment(BaseModel):
    brand: Literal["identified", "uncertain"] = Field(
        description="Whether visible evidence supports the named brand."
    )
    family: Literal["identified", "plausible", "uncertain"] = Field(
        description="Strength of visible evidence for the named model family."
    )
    reference: Literal["supported", "unresolved"] = Field(
        description="Supported only when the image distinguishes the exact reference."
    )


class WatchAnalysis(BaseModel):
    is_watch: bool
    observations: Observations
    candidates: list[Candidate] = Field(
        description="At most three candidates, ordered most to least likely."
    )
    identification_assessment: IdentificationAssessment
    unknowns: list[str]
    recommended_next_photo: str
    caution: str = Field(
        description="Short warning about uncertainty or visually similar references."
    )


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze a watch photo with Gemini and print structured JSON."
    )
    parser.add_argument("image", type=Path, help="Path to a JPG, PNG, or WebP image")
    parser.add_argument(
        "--model",
        default=os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
        help=f"Gemini model (default: GEMINI_MODEL or {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--no-crop",
        action="store_true",
        help="Send only the resized full image, without a center detail crop",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the raw model response instead of validated, formatted JSON",
    )
    return parser.parse_args()


def encode_jpeg(image: Image.Image, max_side: int) -> str:
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90, optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def image_inputs(path: Path, include_crop: bool) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"Image not found: {path}")
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("Image is larger than 20 MB; resize it before testing.")

    try:
        with Image.open(path) as source:
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not read {path} as an image: {exc}") from exc

    inputs: list[dict[str, str]] = [
        {"type": "text", "text": "Original photograph:"},
        {
            "type": "image",
            "data": encode_jpeg(image, max_side=1800),
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
                    "data": encode_jpeg(center, max_side=1800),
                    "mime_type": "image/jpeg",
                },
            ]
        )

    return inputs


def main() -> int:
    load_dotenv()
    args = parse_args()

    if not os.getenv("GEMINI_API_KEY"):
        print(
            "Missing GEMINI_API_KEY. Copy .env.example to .env and add your key.",
            file=sys.stderr,
        )
        return 2

    try:
        inputs = [{"type": "text", "text": PROMPT}]
        inputs.extend(image_inputs(args.image, include_crop=not args.no_crop))

        client = genai.Client()
        response = client.interactions.create(
            model=args.model,
            input=inputs,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": WatchAnalysis.model_json_schema(),
            },
        )

        if args.raw:
            print(response.output_text)
            return 0

        analysis = WatchAnalysis.model_validate_json(response.output_text)
        if len(analysis.candidates) > 3:
            analysis.candidates = analysis.candidates[:3]
        print(json.dumps(analysis.model_dump(), indent=2, ensure_ascii=False))
        return 0
    except ValidationError as exc:
        print("Gemini returned JSON that did not match the expected schema:", file=sys.stderr)
        print(exc, file=sys.stderr)
        print("\nRetry with --raw to inspect the model response.", file=sys.stderr)
        return 1
    except Exception as exc:  # SDK errors vary by transport and API version.
        print(f"Analysis failed: {exc}", file=sys.stderr)
        print(
            f"If the model is unavailable on your account, try: --model <available-model>",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
