from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value):
    """Thousands-separated integer amount, e.g. 1,234,567. Blank for None."""
    if value in (None, ""):
        return ""
    try:
        return f"{Decimal(value):,.0f}"
    except (InvalidOperation, TypeError, ValueError):
        return value


@register.filter
def get_item(mapping, key):
    """dict lookup by a variable key, e.g. {{ mydict|get_item:somekey }}."""
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def pct(value):
    try:
        return f"{Decimal(value) * 100:.10f}".rstrip("0").rstrip(".") + "%"
    except (InvalidOperation, TypeError, ValueError):
        return value
