from django.contrib import admin
from unfold.decorators import display

from apps.core.admin_base import ModelAdmin, TabularInline

from .models import (
    DeductionCode,
    EarningCode,
    EmployeeDeduction,
    EmployeeEarning,
    PayRun,
    PayRunLine,
    PayRunLineItem,
)

_STATUS_LABELS = {
    "Draft": "info",
    "Calculated": "info",
    "Reviewed": "warning",
    "Approved": "success",
    "Disbursed": "success",
}


@admin.register(EarningCode)
class EarningCodeAdmin(ModelAdmin):
    list_display = ("code", "name", "is_taxable", "subject_to_nssf", "applies_to_salary", "applies_to_expense", "is_active")
    list_editable = ("is_active",)
    search_fields = ("code", "name")


@admin.register(DeductionCode)
class DeductionCodeAdmin(ModelAdmin):
    list_display = ("code", "name", "applies_to_salary", "applies_to_expense", "is_loan", "is_active")
    list_editable = ("is_active",)
    search_fields = ("code", "name")


@admin.register(EmployeeDeduction)
class EmployeeDeductionAdmin(ModelAdmin):
    money_fields = ("amount", "balance")
    list_display = (
        "employee", "code", "amount_amount", "run_scope", "recurrence", "balance_amount",
        "number_of_runs", "runs_applied", "approval_status", "is_active",
    )
    list_filter = ("code", "run_scope", "recurrence", "approval_status", "is_active")
    search_fields = ("employee__staff_id", "employee__full_legal_name")
    autocomplete_fields = ("employee", "code")
    readonly_fields = ("runs_applied", "approval_reviewed_by", "approval_reviewed_at")


@admin.register(EmployeeEarning)
class EmployeeEarningAdmin(ModelAdmin):
    money_fields = ("amount",)
    list_display = ("employee", "code", "amount_amount", "recurrence", "is_active")
    list_filter = ("code", "recurrence", "is_active")
    search_fields = ("employee__staff_id", "employee__full_legal_name")
    autocomplete_fields = ("employee", "code")


class PayRunLineItemInline(TabularInline):
    model = PayRunLineItem
    money_fields = ("amount", "balance_after")
    extra = 0
    can_delete = False
    tab = True
    fields = ("item_type", "code", "label", "amount_amount", "balance_after_amount")
    readonly_fields = fields


class PayRunLineInline(TabularInline):
    model = PayRunLine
    money_fields = ("gross_pay", "paye", "nssf_employee", "total_deductions", "net_pay", "variance")
    extra = 0
    can_delete = False
    show_change_link = True
    tab = True
    fields = ("employee_name", "business_unit_name", "gross_pay_amount", "paye_amount",
              "nssf_employee_amount", "total_deductions_amount", "net_pay_amount", "variance_amount")
    readonly_fields = fields


@admin.register(PayRun)
class PayRunAdmin(ModelAdmin):
    list_display = ("__str__", "business_unit", "run_type", "period_year", "period_month", "status_badge", "calculated_at")
    list_filter = ("run_type", "status", "period_year", "business_unit")
    autocomplete_fields = ("business_unit",)
    readonly_fields = ("status", "calculated_at", "reviewed_by", "reviewed_at", "approved_by", "approved_at", "disbursed_at")
    inlines = (PayRunLineInline,)

    @display(description="Status", label=_STATUS_LABELS)
    def status_badge(self, obj):
        return obj.get_status_display()


@admin.register(PayRunLine)
class PayRunLineAdmin(ModelAdmin):
    money_fields = ("gross_pay", "paye", "nssf_employee", "total_deductions", "net_pay", "variance")
    list_display = ("employee_name", "pay_run", "business_unit_name", "gross_pay_amount", "paye_amount",
                    "nssf_employee_amount", "total_deductions_amount", "net_pay_amount", "variance_amount")
    list_filter = ("pay_run", "business_unit_name")
    search_fields = ("employee_name", "staff_id")
    inlines = (PayRunLineItemInline,)

    def has_add_permission(self, request):
        return False
