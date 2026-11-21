"""Category heuristics shared by the image resolver, cleanup and the UI."""

from __future__ import annotations

from typing import Final

from .matcher import fold_umlauts

__all__ = ["LOOSE_PRODUCE_WORDS", "is_loose_produce"]

#: Loose fruit and vegetables: a catalogue photo is usually the wrong product
#: (a ginger *shot* instead of ginger root), so they get the category icon.
LOOSE_PRODUCE_WORDS: Final[frozenset[str]] = frozenset(
    {
        "ingwer",
        "banane",
        "bananen",
        "apfel",
        "aepfel",
        "kartoffel",
        "kartoffeln",
        "zwiebel",
        "zwiebeln",
        "tomate",
        "tomaten",
        "gurke",
        "gurken",
        "paprika",
        "salat",
        "karotte",
        "karotten",
        "moehre",
        "moehren",
        "zucchini",
        "avocado",
        "zitrone",
        "zitronen",
        "orange",
        "orangen",
        "birne",
        "birnen",
        "traube",
        "trauben",
        "champignon",
        "pilze",
        "obst",
        "gemuese",
        "spinat",
        "brokkoli",
        "blumenkohl",
        "lauch",
        "porree",
        "radieschen",
        "kohlrabi",
        "kuerbis",
    }
)


def is_loose_produce(name: str) -> bool:
    """Whether *name* describes loose fruit/vegetables."""

    folded = fold_umlauts(name or "").casefold()
    words = set(folded.replace("-", " ").split())
    return bool(words & LOOSE_PRODUCE_WORDS)
