# Architecture: DACH Supermarket Price Comparison System

## Overview
A modular, high-performance system built in **Python 3.12+** using **FastAPI**, **Pydantic v2**, **httpx**, and **uv** for dependency management. The system aggregates current product offerings, promotional discounts, and regular prices from major German supermarkets (Lidl, Edeka, Rewe, plus aggregator fallback/enrichment via Marktguru and Open Food Facts - Open Prices API), normalizes them into a unified data schema, calculates unit prices (per kg/l), and exposes everything through a clean FastAPI REST API with Swagger documentation (`/docs`).

---

## System Components

```
┌─────────────────────────────────────────────────────────────┐
│                       FastAPI Server                        │
│                 (REST API / Swagger Docs)                   │
└──────┬──────────────┬──────────────┬──────────────┬─────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
┌──────────────┐┌──────────────┐┌──────────────┐┌──────────────┐
│ Lidl Client  ││ Edeka Client ││ Rewe Client  ││Marktguru/OFF │
└──────┬───────┘└──────┬───────┘└──────┬───────┘└──────┬───────┘
       │              │              │              │
       └──────────────┴──────┬───────┴──────────────┘
                             │
                             ▼
              ┌─────────────────────────────┐
              │  Data Normalization Engine  │
              │  - Schema Validation        │
              │  - Unit & Quantity Parser   │
              │  - Unit Price Calculation   │
              │  - Semantic Matching        │
              └──────────────┬──────────────┘
                             │
                             ▼
              ┌─────────────────────────────┐
              │     Unified Data Model      │
              │   (Store, EAN, Price, etc.) │
              └─────────────────────────────┘
```

---

## Modules & Directory Structure

- `supermarket_comparison/`
  - `__init__.py`
  - `config.py` - Environment configuration and settings
  - `models/`
    - `__init__.py`
    - `product.py` - Pydantic schemas for raw and normalized products, offers, and stores
  - `scrapers/`
    - `__init__.py`
    - `base.py` - Abstract base class for supermarket clients
    - `marktguru.py` - Verified Marktguru offer search client (`/api/v1/offers/search`, `x-apikey`)
    - `retailer.py` - `RetailerScraper`: per-store adapter over the Marktguru feed
    - `lidl.py`, `rewe.py`, `edeka.py`, `aldi.py`, `penny.py`, `netto.py`, `kaufland.py` - thin retailer adapters (store filter + cached `retailers` id)
    - `openfoodfacts.py` - Open Prices REST API client (`prices.openfoodfacts.org`, EAN lookups only)
  - `normalization/`
    - `__init__.py`
    - `normalizer.py` - Unit conversion, quantity extraction, unit price calculation (kg/l)
    - `matcher.py` - Product matching & deduplication across stores using EAN and text similarity
  - `api/`
    - `__init__.py`
    - `deps.py` - Shared FastAPI dependencies (aggregator injection)
    - `main.py` - FastAPI app initialization, CORS, routing, HTML UI
    - `templates/index.html` - Self-contained German search UI served at `/`
    - `routes/`
      - `__init__.py`
      - `products.py` - Search, compare, and offer endpoints
      - `stores.py` - Store lookup endpoints by PLZ
  - `services/`
    - `__init__.py`
    - `aggregator.py` - Orchestrates parallel fetching from multiple store scrapers & merging
  - `tests/`
    - `__init__.py`
    - `test_normalizer.py`
    - `test_scrapers.py`
    - `test_matcher.py`
    - `test_aggregator.py`
    - `test_api.py`

---

## Unified Data Model (Pydantic Schema)

```python
class NormalizedProduct(BaseModel):
    id: str
    store: str  # lidl, edeka, rewe, marktguru, openfoodfacts
    name: str
    brand: Optional[str] = None
    ean: Optional[str] = None
    price: float  # Current price in EUR
    old_price: Optional[float] = None  # Regular price before discount
    discount_percent: Optional[float] = None
    unit: str  # kg, l, stueck, g, ml, etc.
    quantity: float  # Numerical amount (e.g., 500.0 for 500g)
    unit_price: Optional[float] = None  # Price per 1kg or 1l
    category: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    image_url: Optional[str] = None
    store_branch_id: Optional[str] = None
```
