from django.contrib import admin
from unfold.decorators import display

from apps.core.admin_base import ModelAdmin, TabularInline
from apps.payroll.models import EmployeeDeduction, EmployeeEarning

from .models import Employee


class EmployeeDeductionInline(TabularInline):
    model = EmployeeDeduction
    extra = 0
    tab = True
    autocomplete_fields = ("code",)


class EmployeeEarningInline(TabularInline):
    model = EmployeeEarning
    extra = 0
    tab = True
    autocomplete_fields = ("code",)


@admin.register(Employee)
class EmployeeAdmin(ModelAdmin):
    money_fields = ("monthly_gross_salary",)
    list_display = ("staff_id", "full_legal_name", "business_unit", "position", "engagement_badge", "status_badge", "monthly_gross_salary_amount")
    list_filter = ("status", "engagement_type", "business_unit")
    search_fields = ("staff_id", "full_legal_name", "national_id", "bank_account_number", "tin")
    autocomplete_fields = ("business_unit", "department")
    inlines = (EmployeeEarningInline, EmployeeDeductionInline)
    list_filter_submit = True
    fieldsets = (
        ("Identity", {"fields": ("staff_id", "full_legal_name", "national_id", "email", "tin", "nssf_number")}),
        ("Placement", {"fields": ("business_unit", "department", "position", "engagement_type")}),
        ("Pay bases", {"fields": ("monthly_gross_salary", "monthly_expense_allowance")}),
        ("Disbursement", {"fields": ("bank_name", "bank_branch_code", "bank_account_number", "mobile_money_number")}),
        ("Lifecycle", {"fields": ("date_joined", "date_left", "status")}),
    )

    @display(description="Status", label={"Active": "success", "Inactive": "danger"})
    def status_badge(self, obj):
        return obj.get_status_display()

    @display(description="Engagement")
    def engagement_badge(self, obj):
        return obj.get_engagement_type_display()
