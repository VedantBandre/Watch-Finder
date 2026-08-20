#!/usr/bin/env python3
"""Run a structured, evidence-first watch analysis with Gemini."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from backend.analyzer import DEFAULT_MODEL, analyze_image, request_analysis_text


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


def _read_image(path: Path) -> bytes:
    if not path.is_file():
        raise ValueError(f"Image not found: {path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Could not read {path}: {exc}") from exc


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
        image_bytes = _read_image(args.image)
        include_crop = not args.no_crop

        if args.raw:
            print(
                request_analysis_text(
                    image_bytes,
                    model=args.model,
                    include_crop=include_crop,
                )
            )
            return 0

        analysis = analyze_image(
            image_bytes,
            model=args.model,
            include_crop=include_crop,
        )
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
            "If the model is unavailable on your account, try: "
            "--model <available-model>",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
