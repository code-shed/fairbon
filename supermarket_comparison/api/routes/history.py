"""Price history and anonymised search statistics."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...storage import Repository

router = APIRouter(tags=["history"])


def get_repository(request: Request) -> Repository:
    """Return the application's repository, creating it lazily.

    Kept separate from the aggregator dependency so tests can override it with
    an in-memory database.
    """

    state: Any = request.app.state
    repository = getattr(state, "repository", None)
    if repository is None:
        repository = Repository()
        state.repository = repository
    return repository


@router.get(
    "/products/history",
    summary="Price history of one product",
)
async def product_history(
    repository: Annotated[Repository, Depends(get_repository)],
    ean: Annotated[
        str | None,
        Query(min_length=8, max_length=14, description="EAN/GTIN of the product"),
    ] = None,
    name: Annotated[
        str | None,
        Query(min_length=2, description="Product name (for offers without EAN)"),
    ] = None,
    brand: Annotated[str | None, Query(description="Restrict to one brand")] = None,
    quantity: Annotated[
        float | None, Query(ge=0, description="Package quantity")
    ] = None,
    unit: Annotated[
        str | None, Query(description="Package unit (kg, l, stueck)")
    ] = None,
    store: Annotated[
        str | None,
        Query(description="Restrict to one store, e.g. ``lidl``"),
    ] = None,
    days: Annotated[int, Query(ge=1, le=3650)] = 90,
) -> dict[str, Any]:
    """Return every recorded price change for a product.

    Leaflet offers have no EAN, so ``name`` is matched against the normalised
    product name.  The series stays empty until the product has been observed
    by at least one search — results are persisted automatically.
    """

    if not ean and not name:
        raise HTTPException(status_code=422, detail="Provide either 'ean' or 'name'.")

    points = await repository.aprice_history(
        ean=ean, name=name, brand=brand, quantity=quantity,
        unit=unit, store=store, days=days,
    )
    prices = [point["price"] for point in points]
    return {
        "ean": ean,
        "name": name,
        "store": store,
        "days": days,
        "points": points,
        "count": len(points),
        "min": min(prices) if prices else None,
        "max": max(prices) if prices else None,
        "currency": "EUR",
        "note": (
            "History is written by this instance only; it fills up as the "
            "same product is observed again and its price changes."
        ),
    }


@router.get(
    "/products/price-insights",
    summary="Price statistics and buy verdict for one product",
)
async def price_insights(
    repository: Annotated[Repository, Depends(get_repository)],
    name: Annotated[
        str | None,
        Query(min_length=2, description="Product name (offers usually have no EAN)"),
    ] = None,
    brand: Annotated[str | None, Query(description="Restrict to one brand")] = None,
    quantity: Annotated[
        float | None, Query(ge=0, description="Package quantity")
    ] = None,
    unit: Annotated[
        str | None, Query(description="Package unit (kg, l, stueck)")
    ] = None,
    ean: Annotated[str | None, Query(min_length=8, max_length=14)] = None,
    store: Annotated[str | None, Query(max_length=32)] = None,
    days: Annotated[
        int,
        Query(ge=0, le=3650, description="0 = all recorded history"),
    ] = 365,
) -> dict[str, Any]:
    """Return the recorded series plus low/high/average and a buy verdict.

    The verdict is deliberately conservative: with fewer than three
    observations it says the history is still building instead of pretending
    to know what "cheap" means.
    """

    if not ean and not name:
        raise HTTPException(status_code=422, detail="Provide either 'ean' or 'name'.")

    window = 3650 if days == 0 else days
    points = await repository.aprice_history(
        ean=ean, name=name, brand=brand, quantity=quantity,
        unit=unit, store=store, days=window,
    )

    prices = [float(point["price"]) for point in points]
    current = prices[-1] if prices else None
    low = min(prices) if prices else None
    high = max(prices) if prices else None
    average = round(sum(prices) / len(prices), 2) if prices else None

    if not prices:
        verdict = {
            "level": "unknown",
            "label": "Noch keine Preisdaten",
            "reason": "Für dieses Produkt wurde noch kein Preis aufgezeichnet.",
        }
    elif len(prices) < 3:
        verdict = {
            "level": "building",
            "label": "Preishistorie im Aufbau",
            "reason": (
                "Erst " + str(len(prices)) + " Messpunkt(e) – der Harvester "
                "ergänzt jede Woche neue Preise."
            ),
        }
    elif current is not None and low is not None and current <= low * 1.02:
        verdict = {
            "level": "top",
            "label": "Top-Preis",
            "reason": "Aktuell auf oder nahe dem historischen Tiefstpreis.",
        }
    elif current is not None and average is not None and current < average * 0.98:
        verdict = {
            "level": "good",
            "label": "Guter Preis",
            "reason": "Aktuell unter dem Durchschnitt der aufgezeichneten Preise.",
        }
    else:
        verdict = {
            "level": "expensive",
            "label": "Teurer als üblich",
            "reason": "Aktuell über dem Durchschnitt – abwarten kann sich lohnen.",
        }

    stores: dict[str, dict[str, Any]] = {}
    for point in points:
        stores[point["store"]] = {
            "store": point["store"],
            "price": point["price"],
            "unit_price": point["unit_price"],
            "date": point["changed_at"],
        }

    return {
        "name": name,
        "ean": ean,
        "store_filter": store,
        "days": days,
        "currency": "EUR",
        "points": points,
        "count": len(points),
        "stats": {
            "current": current,
            "low": low,
            "high": high,
            "average": average,
        },
        "verdict": verdict,
        "stores": sorted(stores.values(), key=lambda item: item["price"]),
        "note": (
            "Alle Werte stammen aus den in dieser Instanz aufgezeichneten "
            "Preisen (Angebote und Community-Standardpreise)."
        ),
    }


@router.get("/stats/trends", tags=["stats"])
async def search_trends(
    repository: Annotated[Repository, Depends(get_repository)],
    days: Annotated[int, Query(ge=1, le=3650)] = 30,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    postal_code: Annotated[
        str | None,
        Query(min_length=4, max_length=5, description="Filter by postal code"),
    ] = None,
) -> dict[str, Any]:
    """Aggregated, anonymised search terms — overall or for one postal code."""

    if postal_code:
        items = await repository.aregional_queries(
            postal_code=postal_code, days=days, limit=limit
        )
    else:
        items = await repository.atop_queries(days=days, limit=limit)
    return {
        "days": days,
        "postal_code": postal_code,
        "items": items,
        "privacy": (
            "No IP addresses, session ids or user agents are stored; only the "
            "normalised search term, the postal code and a timestamp."
        ),
    }


@router.get("/stats/summary", tags=["stats"])
async def stats_summary(
    repository: Annotated[Repository, Depends(get_repository)],
) -> dict[str, Any]:
    """Row counts of the local price/statistics database."""

    return await repository.astats_summary()


__all__ = ["get_repository", "router"]
