"""Template filters for money display (FCFA)."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

register = template.Library()


@register.filter(name="fcfa")
def fcfa(amount):
    """
    Format an amount for FCFA display: whole francs only, no decimal point.

    Examples: 7000.00 -> "7000", 12500 -> "12500", None -> "0"
    """
    if amount is None:
        return "0"
    try:
        d = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return "0"
    n = int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return str(n)
