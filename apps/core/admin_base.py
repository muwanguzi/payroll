"""Shared admin base classes: Unfold styling + simple_history audit trail."""

from decimal import Decimal, InvalidOperation

from django.utils.safestring import mark_safe
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.admin import StackedInline as UnfoldStackedInline
from unfold.admin import TabularInline as UnfoldTabularInline


def fmt_money(value):
    """Thousands-separated amount, e.g. 1,234,567. Blank/None -> em dash."""
    if value in (None, ""):
        return "—"
    try:
        return f"{Decimal(value):,.0f}"
    except (InvalidOperation, TypeError, ValueError):
        return str(value)


def _money_method(field_name, label=None):
    """A `(self, obj)` admin display method that comma-formats a model field."""

    def _col(self, obj):
        return mark_safe(
            '<span style="font-variant-numeric:tabular-nums;white-space:nowrap">'
            f"{fmt_money(getattr(obj, field_name, None))}</span>"
        )

    _col.__name__ = f"{field_name}_amount"
    _col.short_description = label or field_name.replace("_", " ").capitalize()
    _col.admin_order_field = field_name
    return _col


class MoneyAdminMixin:
    """Set ``money_fields`` to model field names; each is exposed as a
    ``<field>_amount`` comma-formatted column usable in list_display,
    readonly_fields, or inline ``fields``."""

    money_fields: tuple = ()

    def __init__(self, *args, **kwargs):
        for name in self.money_fields:
            attr = f"{name}_amount"
            if not hasattr(type(self), attr):
                setattr(type(self), attr, _money_method(name))
        super().__init__(*args, **kwargs)


class ModelAdmin(MoneyAdminMixin, UnfoldModelAdmin, SimpleHistoryAdmin):
    """Unfold-themed ModelAdmin that also records history."""

    compressed_fields = True
    warn_unsaved_form = True
    list_filter_submit = True


class TabularInline(MoneyAdminMixin, UnfoldTabularInline):
    pass


class StackedInline(MoneyAdminMixin, UnfoldStackedInline):
    pass
