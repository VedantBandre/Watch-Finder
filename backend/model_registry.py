"""Gemini models supported by the watch analyzer, in fallback order."""

from dataclasses import dataclass


AUTO_MODEL = "auto"


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    priority: int


MODEL_OPTIONS = (
    ModelOption("gemini-3.7-flash", "3.7 Flash", 1),
    ModelOption("gemini-3.6-flash", "3.6 Flash", 2),
    ModelOption("gemini-3.5-flash", "3.5 Flash", 3),
)

MODEL_BY_ID = {option.id: option for option in MODEL_OPTIONS}
