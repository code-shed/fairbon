"""Aggregator service.

The aggregator fans out a request to all selected supermarket clients with
:func:`asyncio.gather`, isolates failures so one broken source cannot break
the response, normalises the merged result and applies matching/deduplication.

Milestone 8 adds relevance-aware search (:meth:`Aggregator.search_ranked`)
and a basket optimiser (:meth:`Aggregator.optimize_basket`) that compares unit
prices only inside the same unit family.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING, Any, Self

from ..config import get_settings
from ..models import (
    BasketItemResult,
    BasketLine,
    BasketOption,
    BasketPlan,
    NormalizedProduct,
    QuickFilter,
    RankedItem,
    RankedSearchResult,
    RelevanceInfo,
    StoreBranch,
    StoreGroup,
    ValidityInfo,
)
from ..normalization.matcher import (
    ProductGroup,
    deduplicate,
    filter_by_query,
    group_products,
    normalize_ean,
    title_similarity,
)
from ..normalization.relevance import (
    ScoredProduct,
    apply_exclusions,
    quick_filters,
    rank_products,
)
from ..scrapers.openfoodfacts import OpenFoodFactsScraper
from .validity import classify, is_today

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..scrapers.base import BaseScraper

_UNIT_FAMILIES = ("kg", "l", "stueck")


def default_scrapers() -> list[BaseScraper]:
    """Return the default price sources — currently Open Food Facts only."""

    return [
        OpenFoodFactsScraper(),
    ]


def _validity_info(product: NormalizedProduct) -> ValidityInfo:
    if product.is_standard_price:
        return ValidityInfo(
            state="standard",
            label="Standardpreis",
            starts=product.valid_from[:10] if product.valid_from else None,
            ends=None,
        )
    validity = classify(product.valid_from, product.valid_to)
    return ValidityInfo(
        state=validity.state,
        label=validity.label,
        starts=validity.starts.isoformat() if validity.starts else None,
        ends=validity.ends.isoformat() if validity.ends else None,
    )


def _relevance_info(scored: ScoredProduct) -> RelevanceInfo:
    return RelevanceInfo(
        tier=scored.tier,
        score=scored.score,
        matched_as=scored.matched_as,
        matched_terms=list(scored.matched_terms),
        counter_terms=list(scored.counter_terms),
    )


def _same_family(left: NormalizedProduct, right: NormalizedProduct) -> bool:
    return left.unit == right.unit and left.unit in _UNIT_FAMILIES


def _compare_offers(left: NormalizedProduct, right: NormalizedProduct) -> int:
    """Compare two offers of the same item.

    Unit prices are only comparable inside the same unit family (kg/l/piece);
    across families the absolute price is used.
    """

    if _same_family(left, right) and (
        left.unit_price is not None and right.unit_price is not None
    ):
        left_key = (left.unit_price, left.price, left.name)
        right_key = (right.unit_price, right.price, right.name)
        return (left_key > right_key) - (left_key < right_key)
    left_key = (left.price, left.name, left.store)
    right_key = (right.price, right.name, right.store)
    return (left_key > right_key) - (left_key < right_key)


def _cheapest(offers: Iterable[NormalizedProduct]) -> NormalizedProduct | None:
    best: NormalizedProduct | None = None
    for offer in offers:
        if best is None or _compare_offers(offer, best) < 0:
            best = offer
    return best


class Aggregator:
    """Queries several scrapers concurrently and merges their offers."""

    def __init__(
        self,
        scrapers: Sequence[BaseScraper] | None = None,
        *,
        threshold: float = 0.85,
        repository: Any | None = None,
        standard_prices: Any | None = None,
        max_results: int | None = None,
    ) -> None:
        self.scrapers: list[BaseScraper] = (
            list(scrapers) if scrapers is not None else default_scrapers()
        )
        self.threshold = threshold
        self.last_errors: dict[str, Exception] = {}
        self.repository = repository
        self.max_results = int(max_results or get_settings().max_results)
        self._standard = standard_prices
        self._owns_standard = standard_prices is None

    # -- standard prices (permanent assortment) ---------------------------
    @property
    def standard_prices(self) -> Any:
        """Lazily created :class:`StandardPriceService`."""

        if self._standard is None:
            from .standard_prices import StandardPriceService

            self._standard = StandardPriceService()
        return self._standard

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close all owned HTTP clients."""

        await asyncio.gather(
            *(scraper.aclose() for scraper in self.scrapers),
            return_exceptions=True,
        )
        if self._owns_standard and self._standard is not None:
            await self._standard.aclose()
            self._standard = None

    close = aclose

    @property
    def supported_stores(self) -> list[str]:
        """Store identifiers of the configured scrapers."""

        return [scraper.store for scraper in self.scrapers]

    def _select(self, stores: Sequence[str] | str | None) -> list[BaseScraper]:
        if not stores:
            return list(self.scrapers)

        if isinstance(stores, str):
            parts: list[str] = stores.split(",")
        else:
            parts = [part for item in stores for part in str(item).split(",")]
        wanted = {part.strip().lower() for part in parts if part.strip()}
        return [scraper for scraper in self.scrapers if scraper.store in wanted]

    @staticmethod
    def _supported_kwargs(method: Callable[..., Any], **kwargs: Any) -> dict[str, Any]:
        """Filter kwargs to those accepted by *method*.

        This keeps custom/legacy scraper implementations usable even when
        they only implement the original ``postal_code``/``query`` signature.
        """

        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):  # pragma: no cover - builtins
            return kwargs
        if any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            return kwargs
        return {name: value for name, value in kwargs.items() if name in parameters}

    async def _fetch_offers(
        self,
        scraper: BaseScraper,
        *,
        query: str | None,
        postal_code: str | None,
        ean: str | None,
        errors: dict[str, Exception] | None = None,
        limit: int | None = None,
    ) -> list[NormalizedProduct]:
        target = self.last_errors if errors is None else errors
        try:
            return await scraper.fetch_offers(
                **self._supported_kwargs(
                    scraper.fetch_offers,
                    postal_code=postal_code,
                    query=query,
                    ean=ean,
                    limit=limit,
                )
            )
        except Exception as exc:
            target[scraper.store] = exc
            return []

    async def _fetch_stores(
        self,
        scraper: BaseScraper,
        *,
        postal_code: str | None,
        limit: int,
    ) -> list[StoreBranch]:
        try:
            return await scraper.fetch_stores(
                **self._supported_kwargs(
                    scraper.fetch_stores,
                    postal_code=postal_code,
                    limit=limit,
                )
            )
        except Exception as exc:
            self.last_errors[scraper.store] = exc
            return []

    async def _search_products(
        self,
        *,
        query: str,
        postal_code: str | None,
        stores: Sequence[str] | str | None,
        ean: str | None = None,
        limit: int | None = None,
        include_standard: bool = False,
        include_community: bool = True,
        errors: dict[str, Exception] | None = None,
    ) -> list[NormalizedProduct]:
        """Fan out, filter and deduplicate without sorting by relevance."""

        if not query or not query.strip():
            return []

        # Store chips must not abort the search: community (and standard)
        # prices are local sources without any scraper, and no scraper ever
        # matches the chain ids the UI sends.  Unmatched scrapers simply do
        # not fan out; the chips filter the results instead.
        selected = self._select(stores)

        tasks: list[Any] = [
            self._fetch_offers(
                scraper,
                query=query,
                postal_code=postal_code,
                ean=ean,
                errors=errors,
                limit=limit,
            )
            for scraper in selected
        ]

        batches = await asyncio.gather(*tasks)
        products = [product for batch in batches for product in batch]
        products = filter_by_query(products, query)

        if include_standard and get_settings().standard_prices_enabled:
            products.extend(
                await self._fetch_standard(
                    query=query,
                    postal_code=postal_code,
                    stores=stores,
                    errors=errors,
                )
            )

        # Community prices come from the local database and are always
        # merged: they are the cheapest way to fill the standard-price gap.
        if include_community:
            products.extend(
                await self._fetch_community(
                    query=query,
                    postal_code=postal_code,
                    stores=stores,
                    errors=errors,
                )
            )

        return deduplicate(products, threshold=self.threshold)

    async def _fetch_community(
        self,
        *,
        query: str,
        postal_code: str | None,
        stores: Sequence[str] | str | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> list[NormalizedProduct]:
        """Community-contributed shelf prices (local database, no network)."""

        target = self.last_errors if errors is None else errors
        repository = self.repository
        if repository is None:
            try:
                from ..storage import Repository

                repository = Repository()
                self.repository = repository
            except Exception as exc:  # pragma: no cover - DB unavailable
                target["community"] = exc
                return []

        try:
            from ..storage import to_products

            aggregated = await asyncio.to_thread(
                repository.community.aggregated_for_query,
                query=query,
                postal_code=postal_code,
            )
            products = to_products(aggregated)
            wanted = _store_filter(stores)
            if wanted:
                # Unchecked chain chips hide their community rows.
                products = [
                    product for product in products if product.store in wanted
                ]
            return products
        except Exception as exc:  # pragma: no cover - defensive
            target["community"] = exc
            return []

    async def _fetch_standard(
        self,
        *,
        query: str,
        postal_code: str | None,
        stores: Sequence[str] | str | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> list[NormalizedProduct]:
        """Fetch permanent-assortment prices (Open Food Facts / Open Prices)."""

        target = self.last_errors if errors is None else errors
        try:
            offers = await self.standard_prices.search(query, postal_code=postal_code)
        except Exception as exc:  # network/API problems must not break search
            target["standard"] = exc
            return []

        wanted = _store_filter(stores)
        if wanted:
            offers = [offer for offer in offers if offer.store in wanted]
        return offers

    async def _persist(
        self,
        *,
        query: str,
        postal_code: str | None,
        products: Sequence[NormalizedProduct],
        stores: Sequence[str] | str | None = None,
    ) -> None:
        """Store offers plus an anonymised search event; never raises."""

        repository = self.repository
        if repository is None:
            try:
                from ..storage import Repository

                repository = Repository()
                self.repository = repository
            except Exception:
                return

        try:
            await repository.arecord_offers(products)
            await repository.arecord_search(
                query=query,
                postal_code=postal_code,
                result_count=len(products),
                stores=_store_filter(stores) or sorted({p.store for p in products}),
            )
        except Exception:
            # Persistence is best effort: a locked or read-only database must
            # not turn a successful search into an error.
            return

    def _cap_limit(self, limit: int | None) -> int | None:
        if limit is None:
            return None
        return max(1, min(int(limit), self.max_results))

    async def search(
        self,
        *,
        query: str,
        postal_code: str | None = None,
        stores: Sequence[str] | str | None = None,
        limit: int | None = None,
        precise: bool = True,
        include_standard: bool = False,
    ) -> list[NormalizedProduct]:
        """Search all selected stores concurrently and rank the offers.

        With ``precise=True`` (the default) only exact/compound/category hits
        are returned; modifier hits such as *Buttermilch* for *Butter* are
        dropped.  ``include_standard`` merges the permanent assortment.
        """

        self.last_errors = {}
        capped = self._cap_limit(limit)
        products = await self._search_products(
            query=query,
            postal_code=postal_code,
            stores=stores,
            limit=capped,
            include_standard=include_standard,
        )
        scored = rank_products(products, query, include_imprecise=not precise)
        if capped is not None:
            scored = _reserve_standard_slots(scored, capped, include_standard)
        result = [item.product for item in scored]

        await self._persist(
            query=query, postal_code=postal_code, products=result, stores=stores
        )
        return result

    async def search_ranked(
        self,
        *,
        query: str,
        postal_code: str | None = None,
        stores: Sequence[str] | str | None = None,
        limit: int | None = 20,
        precise: bool = True,
        exclude: Sequence[str] | str | None = None,
        today_only: bool = False,
        include_standard: bool = False,
        offers_only: bool = False,
    ) -> RankedSearchResult:
        """Return ranked offers plus quick filters and source diagnostics."""

        self.last_errors = {}
        capped = self._cap_limit(limit) if limit is not None else None
        products = await self._search_products(
            query=query,
            postal_code=postal_code,
            stores=stores,
            limit=capped,
            include_standard=include_standard,
        )

        # Chips are derived from the *unfiltered* candidate set: an excluded
        # term must stay visible so the UI can render it as an active chip and
        # let the user undo the exclusion.
        filters = quick_filters(rank_products(products, query, include_imprecise=True))

        exclusions = _split_terms(exclude)
        if exclusions:
            products = apply_exclusions(products, exclusions)
        if offers_only:
            products = [p for p in products if p.offer_type != "standard"]
        if today_only:
            products = [
                product
                for product in products
                if is_today(product.valid_from, product.valid_to)
            ]

        total_found = len(products)
        scored = rank_products(products, query, include_imprecise=not precise)

        sources: dict[str, int] = {}
        for product in products:
            sources[product.store] = sources.get(product.store, 0) + 1

        if capped is not None:
            scored[:] = _reserve_standard_slots(scored, capped, include_standard)

        await self._persist(
            query=query,
            postal_code=postal_code,
            products=[item.product for item in scored],
            stores=stores,
        )

        return RankedSearchResult(
            query=query,
            postal_code=postal_code,
            total_found=total_found,
            total_returned=len(scored),
            items=[
                RankedItem(
                    product=item.product,
                    relevance=_relevance_info(item),
                    validity=_validity_info(item.product),
                )
                for item in scored
            ],
            quick_filters=[QuickFilter(**item) for item in filters],
            sources=sources,
            errors={store: str(exc) for store, exc in self.last_errors.items()},
        )

    async def optimize_basket(
        self,
        *,
        items: Sequence[str],
        postal_code: str | None = None,
        stores: Sequence[str] | str | None = None,
        max_stores: int = 2,
        today_only: bool = False,
        include_standard: bool = False,
    ) -> BasketPlan:
        """Find the cheapest split and the cheapest ``max_stores`` plan."""

        max_stores = max(1, min(int(max_stores), 5))

        async def _resolve(
            item: str,
        ) -> tuple[str, list[NormalizedProduct], dict[str, Exception]]:
            errors: dict[str, Exception] = {}
            products = await self._search_products(
                query=item,
                postal_code=postal_code,
                stores=stores,
                include_standard=include_standard,
                errors=errors,
            )
            scored = rank_products(products, item, include_imprecise=False)
            return item, [entry.product for entry in scored], errors

        resolved = await asyncio.gather(*(_resolve(item) for item in items))

        candidates: dict[str, dict[str, NormalizedProduct]] = {}
        statuses: list[BasketItemResult] = []
        unmatched: list[str] = []
        merged_errors: dict[str, Exception] = {}

        for item, offers, errors in resolved:
            merged_errors.update(errors)
            if today_only:
                offers = [
                    offer
                    for offer in offers
                    if is_today(offer.valid_from, offer.valid_to)
                ]
            per_store: dict[str, NormalizedProduct] = {}
            for offer in offers:
                current = per_store.get(offer.store)
                if current is None or _compare_offers(offer, current) < 0:
                    per_store[offer.store] = offer
            if per_store:
                candidates[item] = per_store
                statuses.append(BasketItemResult(query=item, status="matched"))
            else:
                statuses.append(BasketItemResult(query=item, status="unmatched"))
                unmatched.append(item)

        baseline_total, baseline_partial = _single_store_baseline(candidates)
        option_a = _option_from_choice(
            label="Bester Split",
            choice=_best_split(candidates),
            candidates=candidates,
            baseline_total=baseline_total,
            baseline_partial=baseline_partial,
        )
        option_b = _option_limited(
            candidates=candidates,
            max_stores=max_stores,
            baseline_total=baseline_total,
            baseline_partial=baseline_partial,
        )

        plan = BasketPlan(
            postal_code=postal_code,
            items=statuses,
            option_a=option_a,
            option_b=option_b,
            unmatched=unmatched,
            errors={store: str(exc) for store, exc in merged_errors.items()},
        )

        # Sharing text is generated here so WhatsApp/clipboard exports are
        # identical for every client and covered by unit tests.
        from .sharing import format_plan_text, whatsapp_url

        text = format_plan_text(plan)
        plan.share_text = text
        plan.whatsapp_url = whatsapp_url(text)
        return plan

    async def compare(
        self,
        *,
        ean: str | None = None,
        query: str | None = None,
        postal_code: str | None = None,
        stores: Sequence[str] | str | None = None,
        limit: int | None = None,
    ) -> list[NormalizedProduct]:
        """Return the best offer per store for one product.

        When *ean* is supplied only exact EAN matches are considered.  With a
        free-text *query* the most similar product group is selected.
        """

        if not ean and not (query and query.strip()):
            raise ValueError("either 'ean' or 'query' is required")

        wanted_ean = normalize_ean(ean) if ean else None
        if ean and wanted_ean is None:
            return []

        self.last_errors = {}
        selected = self._select(stores)
        if not selected:
            return []

        batches = await asyncio.gather(
            *(
                self._fetch_offers(
                    scraper,
                    query=query,
                    postal_code=postal_code,
                    ean=ean,
                )
                for scraper in selected
            )
        )
        products = [product for batch in batches for product in batch]

        if ean:
            products = [
                product
                for product in products
                if normalize_ean(product.ean) == wanted_ean
            ]
            if not products:
                return []

        if query:
            products = filter_by_query(products, query)
        if not products:
            return []

        groups = group_products(products, threshold=self.threshold)
        if not groups:
            return []

        if query:

            def score(group: ProductGroup) -> float:
                return max(
                    title_similarity(offer.name, query) for offer in group.offers
                )

            group = max(groups, key=lambda item: (score(item), -item.min_price))
        else:
            group = groups[0]

        best_by_store: dict[str, NormalizedProduct] = {}
        for offer in group.offers:
            current = best_by_store.get(offer.store)
            if current is None or offer.price < current.price:
                best_by_store[offer.store] = offer

        comparison = sorted(
            best_by_store.values(), key=lambda product: (product.price, product.store)
        )
        return comparison[:limit] if limit is not None else comparison

    async def search_stores(
        self,
        *,
        postal_code: str,
        store: Sequence[str] | str | None = None,
        limit: int = 50,
    ) -> list[StoreBranch]:
        """Look up branches near *postal_code* across the selected stores."""

        self.last_errors = {}
        selected = self._select(store)
        if not selected or not postal_code or not postal_code.strip():
            return []

        batches = await asyncio.gather(
            *(
                self._fetch_stores(scraper, postal_code=postal_code, limit=limit)
                for scraper in selected
            )
        )

        seen: set[tuple[str, str]] = set()
        branches: list[StoreBranch] = []
        for branch in (item for batch in batches for item in batch):
            key = (branch.store, branch.branch_id)
            if key in seen:
                continue
            seen.add(key)
            branches.append(branch)

        branches.sort(
            key=lambda branch: (
                branch.distance_km if branch.distance_km is not None else float("inf"),
                branch.store,
                branch.city,
                branch.name,
            )
        )
        return branches[:limit]


def _reserve_standard_slots(
    ranked: list[ScoredProduct], limit: int, enabled: bool
) -> list[ScoredProduct]:
    """Keep permanent shelf prices visible when a small limit is requested.

    Standard prices usually rank in tier 2 (brand/category match) and would
    otherwise be cut off by the leaflet offers.  When the caller asked for the
    whole assortment, reserve up to a quarter of the page for them.
    """

    if not enabled or limit <= 0:
        return ranked[:limit]

    selected = ranked[:limit]
    if any(item.product.offer_type == "standard" for item in selected):
        return selected

    standard = [item for item in ranked if item.product.offer_type == "standard"]
    if not standard:
        return selected

    quota = min(len(standard), max(1, limit // 4))
    merged = selected[: max(0, limit - quota)] + standard[:quota]
    merged.sort(key=lambda item: (-item.tier, item.price_key))
    return merged


def _split_terms(value: Sequence[str] | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    else:
        parts = [part for item in value for part in str(item).split(",")]
    return [part.strip() for part in parts if part.strip()]


def _store_filter(value: Sequence[str] | str | None) -> list[str]:
    """Normalise a ``stores`` argument to a list of store slugs."""

    return [part.strip().lower() for part in _split_terms(value) if part.strip()]


def _best_split(
    candidates: dict[str, dict[str, NormalizedProduct]],
) -> dict[str, NormalizedProduct]:
    assignment: dict[str, NormalizedProduct] = {}
    for item, per_store in candidates.items():
        best = _cheapest(per_store.values())
        if best is not None:
            assignment[item] = best
    return assignment


def _build_option(
    *,
    label: str,
    assignment: dict[str, NormalizedProduct],
    baseline_total: float | None,
    baseline_partial: bool = False,
) -> BasketOption:
    grouped: dict[str, list[BasketLine]] = {}
    for item, offer in assignment.items():
        grouped.setdefault(offer.store, []).append(
            BasketLine(item=item, product=offer, store=offer.store)
        )

    store_groups: list[StoreGroup] = []
    for store in sorted(grouped):
        lines = grouped[store]
        subtotal = round(sum(line.product.price for line in lines), 2)
        store_groups.append(StoreGroup(store=store, lines=lines, subtotal=subtotal))

    total = round(sum(group.subtotal for group in store_groups), 2)
    savings = (
        max(0.0, round(baseline_total - total, 2))
        if baseline_total is not None and not baseline_partial
        else 0.0
    )
    return BasketOption(
        label=label,
        stores=store_groups,
        total=total,
        merchants=len(store_groups),
        covers_all=True,
        missing_items=[],
        savings=savings,
        baseline_total=(
            round(baseline_total, 2) if baseline_total is not None else None
        ),
        baseline_partial=baseline_partial,
    )


def _option_from_choice(
    *,
    label: str,
    choice: dict[str, NormalizedProduct],
    candidates: dict[str, dict[str, NormalizedProduct]],
    baseline_total: float | None,
    baseline_partial: bool = False,
) -> BasketOption:
    option = _build_option(
        label=label,
        assignment=choice,
        baseline_total=baseline_total,
        baseline_partial=baseline_partial,
    )
    missing = [item for item in candidates if item not in choice]
    option.covers_all = not missing
    option.missing_items = missing
    return option


def _option_limited(
    *,
    candidates: dict[str, dict[str, NormalizedProduct]],
    max_stores: int,
    baseline_total: float | None,
    baseline_partial: bool = False,
) -> BasketOption:
    stores = sorted({store for per_store in candidates.values() for store in per_store})
    if not stores:
        return _build_option(
            label=f"Max. {max_stores} Märkte",
            assignment={},
            baseline_total=baseline_total,
            baseline_partial=baseline_partial,
        )

    best_assignment: dict[str, NormalizedProduct] | None = None
    best_key: tuple[int, float, int] | None = None

    upper = min(max_stores, len(stores))
    for size in range(1, upper + 1):
        for combo in itertools.combinations(stores, size):
            assignment: dict[str, NormalizedProduct] = {}
            for item, per_store in candidates.items():
                offers = [per_store[store] for store in combo if store in per_store]
                best = _cheapest(offers)
                if best is not None:
                    assignment[item] = best
            coverage = len(assignment)
            total = round(sum(offer.price for offer in assignment.values()), 2)
            key = (-coverage, total, len(combo))
            if best_key is None or key < best_key:
                best_key = key
                best_assignment = assignment

    assignment = best_assignment or {}
    option = _build_option(
        label=f"Max. {max_stores} Märkte",
        assignment=assignment,
        baseline_total=baseline_total,
        baseline_partial=baseline_partial,
    )
    missing = [item for item in candidates if item not in assignment]
    option.covers_all = not missing
    option.missing_items = missing
    return option


def _single_store_baseline(
    candidates: dict[str, dict[str, NormalizedProduct]],
) -> tuple[float | None, bool]:
    """Cheapest total at a single store; flags partial coverage."""

    if not candidates:
        return None, False

    stores = sorted({store for per_store in candidates.values() for store in per_store})
    best_full: float | None = None

    for store in stores:
        covered = [item for item, per_store in candidates.items() if store in per_store]
        if len(covered) != len(candidates):
            continue
        total = round(sum(candidates[item][store].price for item in covered), 2)
        if best_full is None or total < best_full:
            best_full = total

    if best_full is not None:
        return best_full, False
    # No single store covers the whole list: a partial sum is not a valid
    # comparison baseline, so report no baseline instead of a misleading one.
    return None, True


__all__ = ["Aggregator", "default_scrapers"]
