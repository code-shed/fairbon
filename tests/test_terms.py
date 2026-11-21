"""Tests for the free-text shopping-list parser (no comma required)."""

from __future__ import annotations

import pytest

from supermarket_comparison.normalization.terms import MAX_TERMS, split_terms


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Nutella, Butter, Milch", ["Nutella", "Butter", "Milch"]),
        ("Nutella Butter Milch", ["Nutella", "Butter", "Milch"]),
        ("Ich brauche Butter und Nutella", ["Butter", "Nutella"]),
        ("butter milch nutella", ["butter", "milch", "nutella"]),
        ("Butter\nMilch\nKaffee", ["Butter", "Milch", "Kaffee"]),
        ("Butter; Milch; Kaffee", ["Butter", "Milch", "Kaffee"]),
        ("Butter sowie Milch", ["Butter", "Milch"]),
        ("Butter plus Milch", ["Butter", "Milch"]),
        ("Butter & Milch", ["Butter", "Milch"]),
        ("Butter + Milch", ["Butter", "Milch"]),
        ("Butter / Milch", ["Butter", "Milch"]),
        ("Nur Butter", ["Butter"]),
        ("Butter", ["Butter"]),
        ("", []),
        ("   ,  ;  ", []),
    ],
)
def test_split_terms(text: str, expected: list[str]) -> None:
    assert split_terms(text) == expected


def test_filler_phrases_are_removed() -> None:
    assert split_terms("Ich brauche bitte noch Butter und Milch") == ["Butter", "Milch"]
    assert split_terms("Wir benötigen Kaffee, Zucker") == ["Kaffee", "Zucker"]
    assert split_terms("Kaufe mir bitte Nutella") == ["Nutella"]


def test_adjectives_stay_with_their_noun() -> None:
    assert split_terms("rote Linsen, frische Milch") == ["rote Linsen", "frische Milch"]
    assert split_terms("frische Milch Butter") == ["frische Milch", "Butter"]


def test_multiword_products_are_protected() -> None:
    assert split_terms("Coca Cola und Red Bull") == ["Coca Cola", "Red Bull"]
    result = split_terms("Gut und Günstig Chips")
    assert result == ["Gut und Günstig Chips"]


def test_duplicates_are_removed_case_insensitively() -> None:
    assert split_terms("Butter, butter, BUTTER, Milch") == ["Butter", "Milch"]


def test_terms_are_capped() -> None:
    text = ", ".join(f"Artikel {index}" for index in range(50))
    terms = split_terms(text)
    assert len(terms) == MAX_TERMS


def test_whitespace_is_normalised() -> None:
    assert split_terms("  Butter    und \n\n Milch ") == ["Butter", "Milch"]
