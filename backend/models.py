"""Structured response models for watch analysis."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class ApiModel(BaseModel):
    """API-only base model with camelCase JSON aliases."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class UnavailableModel(ApiModel):
    id: str
    retry_after_seconds: int | None = Field(default=None, alias="retryAfterSeconds")


class AnalysisModelMetadata(ApiModel):
    requested: str
    used: str
    unavailable: list[UnavailableModel]


class AnalyzeResponse(ApiModel):
    analysis: WatchAnalysis
    model: AnalysisModelMetadata


class ModelOptionStatus(ApiModel):
    id: str
    label: str
    priority: int
    available: bool
    retry_after_seconds: int | None = Field(default=None, alias="retryAfterSeconds")


class ModelsResponse(ApiModel):
    default: str
    models: list[ModelOptionStatus]
