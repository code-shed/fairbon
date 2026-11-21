"""Service layer (aggregation, orchestration)."""

from __future__ import annotations

from .aggregator import Aggregator, default_scrapers

__all__ = ["Aggregator", "default_scrapers"]
