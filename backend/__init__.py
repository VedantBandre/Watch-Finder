"""Reusable backend functionality for the ChronoDesk watch analyzer."""

from backend.analyzer import analyze_image
from backend.models import WatchAnalysis

__all__ = ["WatchAnalysis", "analyze_image"]
