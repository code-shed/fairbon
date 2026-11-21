"""FastAPI dependencies shared by the route modules."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from ..services.aggregator import Aggregator


def get_aggregator(request: Request) -> Aggregator:
    """Return the application's aggregator, creating it lazily.

    Keeping the aggregator on ``app.state`` makes it easy to inject a fake or
    a pre-configured instance in tests via ``dependency_overrides``.
    """

    state: Any = request.app.state
    aggregator = getattr(state, "aggregator", None)
    if aggregator is None:
        aggregator = Aggregator()
        state.aggregator = aggregator
    return aggregator


__all__ = ["get_aggregator"]
