"""Smart basket optimiser endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...models import BasketPlan
from ...normalization.terms import MAX_TERMS, split_terms
from ...services.aggregator import Aggregator
from ..deps import get_aggregator

router = APIRouter(prefix="/basket", tags=["basket"])


class ParseRequest(BaseModel):
    """Free-text shopping list to split into search terms."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    text: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "Free text such as 'Ich brauche Butter und Nutella' or "
            "'Nutella Butter Milch'. Comma, semicolon, newline, 'und' and "
            "whitespace are all accepted."
        ),
    )


class BasketRequest(BaseModel):
    """Validated body of ``POST /api/v1/basket/optimize``."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    items: list[str] = Field(
        default_factory=list,
        max_length=MAX_TERMS,
        description="1..20 shopping-list items (duplicates are removed)",
    )
    text: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "Alternative to `items`: free text that is split on commas, "
            "semicolons, newlines, 'und' or whitespace."
        ),
    )
    postal_code: str | None = Field(
        default=None,
        pattern=r"^\d{4,5}$",
        description="German/Austrian/Swiss postal code",
    )
    stores: list[str] | None = Field(
        default=None,
        description="Optional store filter, e.g. ``['lidl', 'rewe']``",
    )
    max_stores: int = Field(default=2, ge=1, le=5)
    today_only: bool = False
    include_standard: bool = Field(
        default=False,
        description="Also consider permanent shelf prices (Dauersortiment)",
    )

    @model_validator(mode="before")
    @classmethod
    def _fill_items_from_text(cls, data: object) -> object:
        """Accept a free-text list as an alternative to explicit items."""

        if not isinstance(data, dict):
            return data
        if data.get("items"):
            return data
        raw = data.get("text")
        if isinstance(raw, str) and raw.strip():
            parsed = split_terms(raw)
            if parsed:
                updated = dict(data)
                updated["items"] = parsed
                return updated
        return data

    @field_validator("items")
    @classmethod
    def _clean_items(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            text = (raw or "").strip()
            if not text:
                continue
            if len(text) > 60:
                raise ValueError("each item must be at most 60 characters")
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
        if not cleaned:
            raise ValueError("at least one non-empty item is required")
        return cleaned

    @model_validator(mode="after")
    def _require_items(self) -> BasketRequest:
        if not self.items:
            raise ValueError("at least one non-empty item is required")
        return self

    @field_validator("stores")
    @classmethod
    def _clean_stores(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [part.strip().lower() for part in value if part and part.strip()]
        return cleaned or None


@router.post(
    "/parse",
    summary="Split a free-text shopping list into search terms",
)
async def parse_shopping_list(body: ParseRequest) -> dict[str, object]:
    """Split arbitrary user input into individual product terms.

    Accepts ``"Nutella, Butter, Milch"`` as well as ``"Nutella Butter Milch"``
    or ``"Ich brauche Butter und Nutella"``.  The UI uses the same rules
    locally, this endpoint is the authoritative server-side implementation for
    API clients and voice assistants.
    """

    items = split_terms(body.text)
    return {
        "text": body.text,
        "items": items,
        "count": len(items),
        "comma_required": False,
    }


@router.post(
    "/optimize",
    response_model=BasketPlan,
    summary="Optimise a shopping list across stores",
)
async def optimize_basket(
    body: BasketRequest,
    aggregator: Annotated[Aggregator, Depends(get_aggregator)],
) -> BasketPlan:
    """Return the best split (option A) and the best limited-store plan (B).

    Unit prices are only compared within the same unit family (kg, l, piece);
    across families the absolute price decides.
    """

    return await aggregator.optimize_basket(
        items=body.items,
        postal_code=body.postal_code,
        stores=body.stores,
        max_stores=body.max_stores,
        today_only=body.today_only,
        include_standard=body.include_standard,
    )


__all__ = ["BasketRequest", "router"]
