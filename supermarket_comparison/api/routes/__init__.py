"""API route modules (imported directly by ``api.main``)."""

from __future__ import annotations

from . import (
    admin_db,
    basket,
    crowd,
    export,
    history,
    images,
    products,
    receipts,
    stores,
    system,
)

__all__ = [
    "admin_db",
    "basket",
    "crowd",
    "export",
    "history",
    "images",
    "products",
    "receipts",
    "stores",
    "system",
]
