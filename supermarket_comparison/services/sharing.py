"""Human-readable export of a basket plan (WhatsApp / clipboard).

The formatting lives in Python so it is covered by unit tests and identical for
every client.  The web UI simply uses the ``share_text`` and ``whatsapp_url``
fields that ``POST /api/v1/basket/optimize`` returns.
"""

from __future__ import annotations

from urllib.parse import quote

from ..models import BasketOption, BasketPlan

__all__ = ["format_plan_text", "format_price", "whatsapp_url"]


def format_price(value: float | None) -> str:
    """Format a price the German way: ``3.14`` -> ``3,14 €``."""

    if value is None:
        return "–"
    return f"{value:.2f}".replace(".", ",") + " €"


def _store_line(option: BasketOption) -> list[str]:
    lines: list[str] = []
    for index, group in enumerate(option.stores):
        if index:
            lines.append("")
        store_label = group.store.capitalize()
        lines.append(f"🏪 {store_label} – {format_price(group.subtotal)}")
        for line in group.lines:
            product = line.product
            amount = ""
            if product.quantity and product.unit in {"kg", "l"}:
                amount = (
                    f" ({round(product.quantity * 1000)} g)"
                    if product.unit == "kg"
                    else f" ({round(product.quantity * 1000)} ml)"
                )
            price = format_price(product.price)
            lines.append(f"  • {line.item}: {product.name}{amount} – {price}")
    return lines


def format_plan_text(
    plan: BasketPlan, *, app_name: str = "Supermarkt-Preisvergleich"
) -> str:
    """Return a WhatsApp/clipboard friendly summary of *plan*.

    Prefers option A (best split) and falls back to option B when option A has
    no stores.  Savings are only mentioned when a single-store baseline really
    exists — never invented.
    """

    option = plan.option_a if plan.option_a.stores else plan.option_b
    if option is None or not option.stores:
        return (
            "🛒 Smart Basket\n"
            "Keine passenden Angebote gefunden – bitte Postleitzahl oder "
            "Begriffe prüfen.\n\n"
            f"Erstellt mit {app_name}"
        )

    header = "🛒 Smart Basket"
    if plan.postal_code:
        header += f" · PLZ {plan.postal_code}"

    lines = [header, ""]
    lines.extend(_store_line(option))
    lines.append("")
    lines.append(f"💰 Gesamt: {format_price(option.total)}")

    if option.baseline_partial:
        lines.append(
            "ℹ️ Kein Einzelmarkt deckt alle Artikel ab – "
            "kein Einzelmarkt-Vergleich möglich."
        )
    elif option.savings and option.savings > 0:
        lines.append(
            f"✅ Ersparnis: {format_price(option.savings)} "
            "gegenüber günstigstem Einzelmarkt"
        )

    other = plan.option_b if option is plan.option_a else plan.option_a
    has_alternative = (
        other
        and other.stores
        and other.total
        and abs(other.total - option.total) > 0.001
    )
    if has_alternative:
        unit = "Markt" if other.merchants == 1 else "Märkten"
        total = format_price(other.total)
        lines.append(f"↔️ Alternative mit max. {other.merchants} {unit}: {total}")

    if plan.unmatched:
        lines.append(f"❓ Nicht gefunden: {', '.join(plan.unmatched)}")

    lines.append("")
    lines.append(f"Erstellt mit {app_name}")
    return "\n".join(lines)


def whatsapp_url(text: str) -> str:
    """Build a ``wa.me`` share link for *text*."""

    return "https://wa.me/?text=" + quote(text, safe="")
