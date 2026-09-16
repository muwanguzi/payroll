from django.contrib import admin
from unfold.decorators import display

from apps.core.admin_base import ModelAdmin, TabularInline

from .models import NssfConfig, PayeBand, PayeTable


class PayeBandInline(TabularInline):
    model = PayeBand
    extra = 0
    tab = True


@admin.register(PayeTable)
class PayeTableAdmin(ModelAdmin):
    list_display = ("name", "residency", "effective_from", "active_badge")
    list_filter = ("residency", "is_active")
    inlines = (PayeBandInline,)
    save_on_top = True

    @display(description="Status", label={"Active": "success", "Inactive": "info"})
    def active_badge(self, obj):
        return "Active" if obj.is_active else "Inactive"


@admin.register(NssfConfig)
class NssfConfigAdmin(ModelAdmin):
    list_display = ("name", "effective_from", "employee_rate", "employer_rate", "active_badge")
    list_filter = ("is_active",)

    @display(description="Status", label={"Active": "success", "Inactive": "info"})
    def active_badge(self, obj):
        return "Active" if obj.is_active else "Inactive"
