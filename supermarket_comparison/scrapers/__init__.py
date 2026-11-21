"""Scraper clients — Open Food Facts (crowd-sourced EAN prices)."""

from __future__ import annotations

from .base import BaseScraper, slugify
from .openfoodfacts import OpenFoodFactsScraper

__all__ = [
    "BaseScraper",
    "OpenFoodFactsScraper",
    "slugify",
]
