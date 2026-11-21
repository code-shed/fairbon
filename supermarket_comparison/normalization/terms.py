"""Split free-text shopping lists into individual search terms.

Users type or dictate lists in very different shapes::

    "Nutella, Butter, Milch"
    "Nutella Butter Milch"
    "Ich brauche Butter und Nutella"
    "Butter\nMilch\nKaffee"
    "rote Linsen, frische Milch"

The parser therefore

1. removes filler phrases ("ich brauche", "bitte", "noch", …),
2. protects known multi-word product names ("Coca Cola", "Gut und Günstig"),
3. splits on explicit separators (comma, semicolon, newline, "und", "sowie",
   "plus", "&", "+", "/"),
4. and, when there is no separator at all, applies a German noun heuristic:
   every capitalised word starts a new term, a lowercase word is glued to the
   following capitalised one ("rote Linsen"), and an all-lowercase list is
   split word by word (dictated lists usually arrive that way).

The JavaScript UI mirrors these rules one-to-one so the preview chips match
what the API stores.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["MAX_TERMS", "split_terms"]

#: Upper bound for one shopping list (matches the basket API validation).
MAX_TERMS: Final = 20

#: Filler phrases that carry no product meaning.  Removed as whole words.
_FILLERS: Final = (
    "ich brauche",
    "ich brauch",
    "ich möchte",
    "ich moechte",
    "ich möchte gerne",
    "ich will",
    "ich hätte gerne",
    "ich haette gerne",
    "wir brauchen",
    "wir benötigen",
    "wir benoetigen",
    "brauche",
    "benötige",
    "benoetige",
    "kaufe",
    "kauf",
    "besorge",
    "hole",
    "besorg",
    "bitte",
    "danke",
    "noch",
    "dann",
    "außerdem",
    "ausserdem",
    "zusätzlich",
    "zusaetzlich",
    "und zwar",
    "dazu",
    "für",
    "fuer",
    "nur",
    "auch",
    "mal",
    "eben",
    "schnell",
    "ein paar",
    "paar",
    "mir",
    "mich",
    "uns",
    "dir",
    "ich",
    "wir",
)

#: Multi-word product names that must not be torn apart by the splitter.
_MULTIWORD: Final = (
    "gut und günstig",
    "gut und guenstig",
    "gut & günstig",
    "coca cola",
    "coca-cola",
    "red bull",
    "häagen dazs",
    "haagen dazs",
    "ben & jerry",
    "fritz kola",
    "fritz-kola",
    "club mate",
    "hohes c",
    "monster energy",
    "dr. oetker",
    "dr oetker",
    "ja!",
)

#: Separators that explicitly delimit list entries.
_SEPARATOR_RE: Final = re.compile(
    r"[,;\n\r]+"
    r"|\s+(?:und|sowie|plus|und\s+dann|sowie\s+auch)\s+"
    r"|\s*[&+]\s*"
    r"|\s+/\s*",
    re.IGNORECASE,
)

_WORD_RE: Final = re.compile(r"\S+")
_WS_RE: Final = re.compile(r"\s+")

_PLACEHOLDER: Final = "\u0001{}\u0001"
_PLACEHOLDER_RE: Final = re.compile("\u0001(\\d+)\u0001")


def _strip_fillers(text: str) -> str:
    result = text
    for filler in sorted(_FILLERS, key=len, reverse=True):
        pattern = r"(?<![\wäöüß])" + re.escape(filler) + r"(?![\wäöüß])"
        result = re.sub(pattern, " ", result, flags=re.IGNORECASE)
    return _WS_RE.sub(" ", result).strip(" ,;.-")


def _protect_multiword(text: str) -> tuple[str, list[str]]:
    stored: list[str] = []
    result = text
    for phrase in sorted(_MULTIWORD, key=len, reverse=True):
        pattern = re.compile(
            r"(?<![\wäöüß-])" + re.escape(phrase) + r"(?![\wäöüß-])",
            re.IGNORECASE,
        )
        while pattern.search(result):
            match = pattern.search(result)
            assert match is not None
            stored.append(match.group(0))
            placeholder = _PLACEHOLDER.format(len(stored) - 1)
            result = result[: match.start()] + placeholder + result[match.end() :]
    return result, stored


def _restore_placeholders(text: str, stored: list[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return stored[index] if index < len(stored) else ""

    return _PLACEHOLDER_RE.sub(replace, text)


def _is_capitalized(word: str) -> bool:
    stripped = word.lstrip("„\"'(")
    return bool(stripped) and stripped[0].isupper()


def _split_without_separator(text: str) -> list[str]:
    """German noun heuristic for input without any explicit separator."""

    words = [word for word in _WORD_RE.findall(text) if word]
    if not words:
        return []
    if len(words) == 1:
        return words

    if not any(_is_capitalized(word) for word in words):
        # A dictated list is typically lower-case: split word by word.
        return words

    terms: list[str] = []
    index = 0
    while index < len(words):
        word = words[index]
        following = words[index + 1] if index + 1 < len(words) else None
        if not _is_capitalized(word) and following and _is_capitalized(following):
            # "rote Linsen" -> one product
            terms.append(f"{word} {following}")
            index += 2
            continue
        terms.append(word)
        index += 1
    return terms


def _clean_term(term: str) -> str:
    value = _WS_RE.sub(" ", term).strip()
    value = value.strip(" ,;.:!?")
    return value


def split_terms(text: str) -> list[str]:
    """Return the individual search terms contained in *text*.

    The order is preserved, duplicates are removed case-insensitively and the
    result is capped at :data:`MAX_TERMS`.
    """

    raw = _WS_RE.sub(" ", str(text or "")).strip()
    if not raw:
        return []

    protected, stored = _protect_multiword(raw)
    cleaned = _strip_fillers(protected)

    if _SEPARATOR_RE.search(cleaned):
        raw_parts = _SEPARATOR_RE.split(cleaned)
    else:
        raw_parts = [cleaned]

    terms: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        # Each chunk may itself be a bare list ("Nutella Milch") or a phrase
        # ("rote Linsen"): the noun heuristic decides per chunk.
        for chunk in _split_without_separator(part):
            value = _clean_term(_restore_placeholders(chunk, stored))
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            terms.append(value)
            if len(terms) >= MAX_TERMS:
                return terms
    return terms
