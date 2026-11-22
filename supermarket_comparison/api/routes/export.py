"""1-click Excel/CSV export of personal receipts for bookkeeping.

Per the product spec the workbook has **two sheets**:

Sheet 1 — ``Rohdaten`` (tax-software friendly): a flat table starting at row 1
with no merged cells.  Every amount is a real number, never text.

Sheet 2 — ``Steuer-Zusammenfassung``: compact summary split by VAT band
(19 %, 7 %, 0 %) and by category.

Parameters
----------
* ``format=xlsx|csv``
* ``exclude_private=true`` filters out lines marked as private
  (useful for business-only exports).

Deposits (Pfand) are exported as their own column and summary column; they
are not part of the taxable base, so ``Netto``/``Steuer`` stay based on the
product price while ``Brutto`` and ``Pfand`` together reconcile with the
receipt total.
"""

from __future__ import annotations

import csv
import io
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from ...storage import Repository
from .history import get_repository

router = APIRouter(prefix="/receipts", tags=["receipts"])

#: Ordered, fixed columns of the rohdata sheet.
ROHDATA_COLUMNS: list[str] = [
    "Belegdatum",
    "Beleg-ID",
    "Händler",
    "Artikel",
    "Kategorie",
    "Privat/Geschäftlich",
    "MwSt-Satz (%)",
    "Netto",
    "Steuerbetrag",
    "Brutto",
    "Pfand",
    "Währung",
]

#: VAT bands shown in the summary.
VAT_BANDS: list[float] = [19.0, 7.0, 0.0]


def _receipts_with_items(
    repository: Repository, owner_token: str
) -> list[dict[str, Any]]:
    """All receipts + items of one owner (flat rows for the export)."""

    rows: list[dict[str, Any]] = []
    for receipt in repository.user_receipts_for(
        owner_token
    ):
        items = repository.user_receipt_items_for(int(receipt["id"]))
        for item in items:
            brutto_cents = int(item["price_cents"] or 0)
            vat_rate = float(item["vat_rate"] or 0.0)
            # netto = brutto / (1 + vat/100)
            netto_cents = round(brutto_cents / (1.0 + vat_rate / 100.0))
            tax_cents = brutto_cents - netto_cents
            rows.append(
                {
                    "receipt_date": receipt["receipt_date"],
                    "receipt_id": receipt["id"],
                    "store": receipt["store"],
                    "name": item["normalized_name"] or item["raw_text"] or "",
                    "category": item["category"] or "Sonstiges",
                    "private": bool(item["is_private"]),
                    "vat_rate": vat_rate,
                    "netto": netto_cents / 100.0,
                    "tax": tax_cents / 100.0,
                    "brutto": brutto_cents / 100.0,
                    "deposit": int(item["deposit_cents"] or 0) / 100.0,
                    "currency": receipt["currency"],
                }
            )
    return rows


def _xlsx_bytes(rows: list[dict[str, Any]], *, exclude_private: bool) -> bytes:
    """Render the two-sheet workbook and return the raw bytes."""

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    if exclude_private:
        rows = [row for row in rows if not row["private"]]

    wb = Workbook()

    # ---- Sheet 1: Rohdaten (flat, row 1 = header, no merged cells) ----
    ws = wb.active
    ws.title = "Rohdaten"
    header_font = Font(bold=True)
    header_fill = PatternFill(fill_type="solid", fgColor="DCEAD9")
    for col, title in enumerate(ROHDATA_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.font = header_font
        cell.fill = header_fill

    for r, row in enumerate(rows, start=2):
        ws.cell(row=r, column=1, value=row["receipt_date"])
        ws.cell(row=r, column=2, value=row["receipt_id"])
        ws.cell(row=r, column=3, value=row["store"])
        ws.cell(row=r, column=4, value=row["name"])
        ws.cell(row=r, column=5, value=row["category"])
        ws.cell(row=r, column=6, value="Privat" if row["private"] else "Geschäftlich")
        ws.cell(row=r, column=7, value=row["vat_rate"])
        ws.cell(row=r, column=8, value=round(row["netto"], 2))
        ws.cell(row=r, column=9, value=round(row["tax"], 2))
        ws.cell(row=r, column=10, value=round(row["brutto"], 2))
        ws.cell(row=r, column=11, value=round(row["deposit"], 2))
        ws.cell(row=r, column=12, value=row["currency"])

    for col in range(1, len(ROHDATA_COLUMNS) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16

    # ---- Sheet 2: Steuer-Zusammenfassung -------------------------------
    ws2 = wb.create_sheet("Steuer-Zusammenfassung")

    ws2.cell(row=1, column=1, value="MwSt-Satz")
    ws2.cell(row=1, column=2, value="Netto")
    ws2.cell(row=1, column=3, value="Steuer")
    ws2.cell(row=1, column=4, value="Brutto")
    ws2.cell(row=1, column=5, value="Pfand")
    for col in range(1, 6):
        cell = ws2.cell(row=1, column=col)
        cell.font = header_font
        cell.fill = header_fill

    def _row(cells: list[tuple[int, object]], r: int) -> None:
        for col, value in cells:
            ws2.cell(row=r, column=col, value=value)

    row_i = 2
    for band in VAT_BANDS:
        filtered = [r for r in rows if abs(r["vat_rate"] - band) < 0.01]
        if not filtered:
            continue
        _row(
            [
                (1, band),
                (2, round(sum(x["netto"] for x in filtered), 2)),
                (3, round(sum(x["tax"] for x in filtered), 2)),
                (4, round(sum(x["brutto"] for x in filtered), 2)),
                (5, round(sum(x["deposit"] for x in filtered), 2)),
            ],
            row_i,
        )
        row_i += 1

    row_i += 1  # blank row
    ws2.cell(row=row_i, column=1, value="Kategorie").font = header_font
    ws2.cell(row=row_i, column=2, value="Netto").font = header_font
    ws2.cell(row=row_i, column=3, value="Steuer").font = header_font
    ws2.cell(row=row_i, column=4, value="Brutto").font = header_font
    ws2.cell(row=row_i, column=5, value="Pfand").font = header_font
    row_i += 1
    categories: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        categories.setdefault(row["category"], []).append(row)
    for category, cat_rows in sorted(categories.items()):
        _row(
            [
                (1, category),
                (2, round(sum(x["netto"] for x in cat_rows), 2)),
                (3, round(sum(x["tax"] for x in cat_rows), 2)),
                (4, round(sum(x["brutto"] for x in cat_rows), 2)),
                (5, round(sum(x["deposit"] for x in cat_rows), 2)),
            ],
            row_i,
        )
        row_i += 1

    row_i += 1
    total_i = row_i
    ws2.cell(row=total_i, column=1, value="GESAMT").font = Font(bold=True)
    for col, key in ((2, "netto"), (3, "tax"), (4, "brutto"), (5, "deposit")):
        cell = ws2.cell(
            row=total_i, column=col, value=round(sum(x[key] for x in rows), 2)
        )
        cell.font = Font(bold=True)

    for col in range(1, 6):
        ws2.column_dimensions[get_column_letter(col)].width = 16

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _csv_text(rows: list[dict[str, Any]], *, exclude_private: bool) -> str:
    if exclude_private:
        rows = [row for row in rows if not row["private"]]
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(ROHDATA_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                row["receipt_date"],
                row["receipt_id"],
                row["store"],
                row["name"],
                row["category"],
                "Privat" if row["private"] else "Geschäftlich",
                _fmt(row["vat_rate"]),
                _fmt(row["netto"]),
                _fmt(row["tax"]),
                _fmt(row["brutto"]),
                _fmt(row["deposit"]),
                row["currency"],
            ]
        )
    return stream.getvalue()


def _fmt(value: float) -> str:
    # Real numbers preferred; CSV keeps a German-compatible decimal.
    return f"{value:.2f}".replace(".", ",")


@router.get("/export", summary="Receipts export (.xlsx / .csv)")
async def export_receipts(
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
    format: Annotated[str, Query(pattern="^(xlsx|csv)$")] = "xlsx",
    exclude_private: Annotated[bool, Query()] = False,
) -> Response:
    """Export all receipts of the anonymous owner as a two-sheet workbook."""

    owner_token = (request.headers.get("x-owner-token") or "").strip()
    if not owner_token:
        raise HTTPException(status_code=422, detail="X-Owner-Token fehlt.")

    rows = _receipts_with_items(repository, owner_token)

    if format == "csv":
        content = _csv_text(rows, exclude_private=exclude_private)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="bons.csv"',
            },
        )

    data = _xlsx_bytes(rows, exclude_private=exclude_private)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="bons.xlsx"',
        },
    )


__all__ = ["router"]
