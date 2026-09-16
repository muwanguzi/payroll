from django.contrib import admin
from django.utils.html import format_html

from apps.core.admin_base import ModelAdmin

from .models import BusinessUnit, Department


@admin.register(BusinessUnit)
class BusinessUnitAdmin(ModelAdmin):
    list_display = ("logo_thumb", "name", "code", "sequence", "is_active")
    list_display_links = ("name",)
    list_editable = ("sequence", "is_active")
    search_fields = ("name", "code")
    list_filter = ("is_active",)
    fields = ("name", "code", "logo", "logo_preview", "sequence", "is_active")
    readonly_fields = ("logo_preview",)

    @admin.display(description="")
    def logo_thumb(self, obj):
        if obj.logo:
            return format_html(
                '<img src="{}" style="height:26px;max-width:80px;object-fit:contain;border-radius:4px">',
                obj.logo.url,
            )
        return "—"

    @admin.display(description="Current logo")
    def logo_preview(self, obj):
        if obj.logo:
            return format_html(
                '<img src="{}" style="height:64px;max-width:220px;object-fit:contain;'
                'background:#f4f4f4;padding:6px;border-radius:6px">',
                obj.logo.url,
            )
        return "No logo uploaded."


@admin.register(Department)
class DepartmentAdmin(ModelAdmin):
    list_display = ("name", "business_unit", "is_active")
    list_filter = ("business_unit", "is_active")
    search_fields = ("name",)
