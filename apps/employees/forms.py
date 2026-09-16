from django import forms

from apps.payroll.models import (
    DeductionCode,
    EarningCode,
    EmployeeDeduction,
    EmployeeEarning,
)

from .models import Employee


class _DateInput(forms.DateInput):
    input_type = "date"


class EmployeeForm(forms.ModelForm):
    """In-app add / edit for the employee master (Recommendation 6.1).

    Model-level ``Employee.clean()`` does the real validation (mandatory Staff ID
    / Position, numeric bank account of the right length, a payment method,
    leaver date not before join date); this form just surfaces it per field.
    """

    class Meta:
        model = Employee
        fields = [
            "staff_id", "full_legal_name", "national_id", "email", "tin", "nssf_number",
            "business_unit", "department", "position", "engagement_type",
            "monthly_gross_salary", "monthly_expense_allowance",
            "bank_name", "bank_branch_code", "bank_account_number", "mobile_money_number",
            "date_joined", "date_left", "status",
        ]
        widgets = {
            "date_joined": _DateInput(),
            "date_left": _DateInput(),
        }

    fieldsets = [
        ("Identity", ["staff_id", "full_legal_name", "national_id", "email", "tin", "nssf_number"]),
        ("Placement", ["business_unit", "department", "position", "engagement_type"]),
        ("Pay bases", ["monthly_gross_salary", "monthly_expense_allowance"]),
        ("Disbursement", ["bank_name", "bank_branch_code", "bank_account_number", "mobile_money_number"]),
        ("Lifecycle", ["date_joined", "date_left", "status"]),
    ]

    def iter_fieldsets(self):
        for title, names in self.fieldsets:
            yield title, [self[name] for name in names]


class EmployeeDeductionForm(forms.ModelForm):
    class Meta:
        model = EmployeeDeduction
        fields = [
            "code", "amount", "run_scope", "recurrence", "opening_balance",
            "number_of_runs", "note", "effective_from", "effective_to", "is_active",
        ]
        widgets = {"effective_from": _DateInput(), "effective_to": _DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].queryset = DeductionCode.objects.filter(is_active=True)
        self.fields["run_scope"].label = "Apply on"
        self.fields["run_scope"].help_text = "Which pay run this deduction is taken on."
        self.fields["opening_balance"].help_text = "Required only for loan-type codes (Hire purchase, Fuel/Advance)."
        self.fields["number_of_runs"].help_text = (
            "Instalment-style deductions: spread across exactly N runs, then stop automatically "
            "(counted at disbursement). Leave blank alongside the date range for an open-ended deduction."
        )
        if self.instance and self.instance.pk and self.instance.runs_applied:
            self.fields["number_of_runs"].help_text += f" Already taken on {self.instance.runs_applied} run(s)."


class EmployeeEarningForm(forms.ModelForm):
    class Meta:
        model = EmployeeEarning
        fields = ["code", "amount", "recurrence", "note", "effective_from", "effective_to", "is_active"]
        widgets = {"effective_from": _DateInput(), "effective_to": _DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].queryset = EarningCode.objects.filter(is_active=True)


COMPONENT_FORMS = {
    "deduction": (EmployeeDeductionForm, "deductions", "deduction"),
    "earning": (EmployeeEarningForm, "earnings", "earning"),
}
