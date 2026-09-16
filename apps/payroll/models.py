from __future__ import annotations

import calendar
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.employees.models import Employee

ZERO = Decimal("0.00")


class RunType(models.TextChoices):
    EXPENSE_ALLOWANCE = "EXPENSE_ALLOWANCE", "Expense Allowance (mid-month)"
    SALARY = "SALARY", "Salary (month-end)"


class RunStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    CALCULATED = "CALCULATED", "Calculated"
    REVIEWED = "REVIEWED", "Reviewed"
    APPROVED = "APPROVED", "Approved"
    DISBURSED = "DISBURSED", "Disbursed"


class Recurrence(models.TextChoices):
    RECURRING = "RECURRING", "Recurring"
    ONE_OFF = "ONE_OFF", "One-off"


# ---------------------------------------------------------------------------
# Configurable earning / deduction codes (Recommendation 6.5)
# ---------------------------------------------------------------------------
class EarningCode(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    is_taxable = models.BooleanField(default=True, help_text="Included in chargeable income for PAYE.")
    subject_to_nssf = models.BooleanField(default=True, help_text="Included in gross for NSSF.")
    applies_to_salary = models.BooleanField(default=True)
    applies_to_expense = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sequence = models.PositiveIntegerField(default=100)

    history = HistoricalRecords()

    class Meta:
        ordering = ["sequence", "code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class DeductionCode(models.Model):
    """Replicates the current recurring-deduction family as reusable codes
    rather than fixed worksheet columns (Recommendation 6.5)."""

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    applies_to_salary = models.BooleanField(default=True)
    applies_to_expense = models.BooleanField(default=True)
    is_loan = models.BooleanField(
        default=False,
        help_text="Carries a running balance that decreases each run and stops itself at zero.",
    )
    is_active = models.BooleanField(default=True)
    sequence = models.PositiveIntegerField(default=100)

    history = HistoricalRecords()

    class Meta:
        ordering = ["sequence", "code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


# ---------------------------------------------------------------------------
# Per-employee attachments (Recommendation 6.5)
# ---------------------------------------------------------------------------
class EmployeeEarning(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="earnings")
    code = models.ForeignKey(EarningCode, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    recurrence = models.CharField(max_length=12, choices=Recurrence.choices, default=Recurrence.RECURRING)
    is_active = models.BooleanField(default=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)

    history = HistoricalRecords()

    def __str__(self):
        return f"{self.employee.staff_id} / {self.code.code} {self.amount}"

    def applies_on(self, on_date):
        if not self.is_active:
            return False
        if self.effective_from and self.effective_from > on_date:
            return False
        if self.effective_to and self.effective_to < on_date:
            return False
        return True


class DeductionScope(models.TextChoices):
    BOTH = "BOTH", "Both runs"
    SALARY = "SALARY", "Salary run only"
    EXPENSE = "EXPENSE", "Expense Allowance run only"


class DeductionApprovalStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class EmployeeDeduction(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="deductions")
    code = models.ForeignKey(DeductionCode, on_delete=models.PROTECT)
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, help_text="Instalment amount per run."
    )
    run_scope = models.CharField(
        "Apply on", max_length=8, choices=DeductionScope.choices, default=DeductionScope.BOTH,
        help_text="Which pay run this deduction is taken on (within what the code allows).",
    )
    recurrence = models.CharField(max_length=12, choices=Recurrence.choices, default=Recurrence.RECURRING)
    opening_balance = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text="For loans: total owed at the start. Leave blank for open-ended deductions.",
    )
    balance = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text="Outstanding balance; decreases automatically each run.",
    )
    number_of_runs = models.PositiveIntegerField(
        "Number of runs", null=True, blank=True,
        help_text="Spread this deduction across exactly N pay runs (instalment-style, e.g. a loan "
                   "repayment plan), then stop automatically. Leave blank for open-ended.",
    )
    runs_applied = models.PositiveIntegerField(
        default=0, editable=False,
        help_text="How many runs this has been taken on so far. Maintained by the system at disbursement.",
    )
    is_active = models.BooleanField(default=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)

    # -- Per-type approval by the Chief Audit Officer -----------------------
    approval_status = models.CharField(
        max_length=10, choices=DeductionApprovalStatus.choices, default=DeductionApprovalStatus.PENDING,
    )
    approval_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_deductions", editable=False,
    )
    approval_reviewed_at = models.DateTimeField(null=True, blank=True, editable=False)
    approval_note = models.CharField(
        "Reviewer note", max_length=200, blank=True,
        help_text="Shown to whoever attached the deduction — required when rejecting.",
    )

    history = HistoricalRecords()

    class Meta:
        ordering = ["employee", "code"]

    def __str__(self):
        return f"{self.employee.staff_id} / {self.code.code} {self.amount}"

    def clean(self):
        errors = {}
        if self.code_id and self.code.is_loan and self.opening_balance is None:
            errors["opening_balance"] = "A loan-type deduction needs an opening balance."
        if self.code_id:
            code_runs = set()
            if self.code.applies_to_salary:
                code_runs.add("SALARY")
            if self.code.applies_to_expense:
                code_runs.add("EXPENSE")
            wanted = {"SALARY", "EXPENSE"} if self.run_scope == DeductionScope.BOTH else {self.run_scope}
            if code_runs and not (wanted & code_runs):
                allowed = " or ".join(sorted(code_runs)).replace("SALARY", "the Salary run").replace("EXPENSE", "the Expense Allowance run")
                errors["run_scope"] = f"{self.code.name} can only be taken on {allowed}."
        if self.number_of_runs is not None and self.number_of_runs < 1:
            errors["number_of_runs"] = "Must be at least 1 run."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.balance is None and self.opening_balance is not None:
            self.balance = self.opening_balance
        super().save(*args, **kwargs)

    def applies_on(self, on_date):
        if not self.is_active:
            return False
        if self.approval_status == DeductionApprovalStatus.REJECTED:
            return False
        if self.effective_from and self.effective_from > on_date:
            return False
        if self.effective_to and self.effective_to < on_date:
            return False
        if self.code.is_loan and (self.balance or ZERO) <= ZERO:
            return False
        if self.number_of_runs is not None and self.runs_applied >= self.number_of_runs:
            return False
        return True

    # -- approval workflow (Chief Audit Officer) -----------------------
    def approve(self, actor, note=""):
        self.approval_status = DeductionApprovalStatus.APPROVED
        self.approval_reviewed_by = actor
        self.approval_reviewed_at = timezone.now()
        self.approval_note = note
        self.save(update_fields=[
            "approval_status", "approval_reviewed_by", "approval_reviewed_at", "approval_note",
        ])

    def reject(self, actor, note=""):
        self.approval_status = DeductionApprovalStatus.REJECTED
        self.approval_reviewed_by = actor
        self.approval_reviewed_at = timezone.now()
        self.approval_note = note
        self.save(update_fields=[
            "approval_status", "approval_reviewed_by", "approval_reviewed_at", "approval_note",
        ])

    def applies_to_run(self, run_type):
        """True if this deduction is taken on the given run type - honouring both
        the per-employee ``run_scope`` and what the code itself allows."""
        if run_type == RunType.EXPENSE_ALLOWANCE:
            return (
                self.run_scope in (DeductionScope.BOTH, DeductionScope.EXPENSE)
                and self.code.applies_to_expense
            )
        return (
            self.run_scope in (DeductionScope.BOTH, DeductionScope.SALARY)
            and self.code.applies_to_salary
        )

    def instalment_for_run(self):
        """Amount to take this run, capped at the outstanding balance for loans."""
        if self.code.is_loan and self.balance is not None:
            return min(self.amount, self.balance)
        return self.amount


# ---------------------------------------------------------------------------
# Pay runs (Recommendation 6.3) and their computed lines (6.2 / 6.6)
# ---------------------------------------------------------------------------
class PayRun(models.Model):
    run_type = models.CharField(max_length=20, choices=RunType.choices)
    business_unit = models.ForeignKey(
        "organization.BusinessUnit", on_delete=models.PROTECT,
        null=True, blank=True, related_name="pay_runs",
        help_text="Scope the run to one business unit. Leave blank for a group-wide run.",
    )
    period_year = models.PositiveIntegerField()
    period_month = models.PositiveIntegerField()
    pay_date = models.DateField()
    status = models.CharField(max_length=12, choices=RunStatus.choices, default=RunStatus.DRAFT)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_runs",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_runs",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_runs",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)

    calculated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-period_year", "-period_month", "run_type", "business_unit__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["run_type", "period_year", "period_month", "business_unit"],
                name="uniq_run_per_period_unit",
            ),
            models.UniqueConstraint(
                fields=["run_type", "period_year", "period_month"],
                condition=models.Q(business_unit__isnull=True),
                name="uniq_group_run_per_period",
            ),
        ]

    def __str__(self):
        return self.title

    # -- derived title (Recommendation 6.6 - no hand-typed period string) --
    @property
    def period_label(self):
        return f"{calendar.month_name[self.period_month]} {self.period_year}"

    @property
    def scope_label(self):
        return self.business_unit.name if self.business_unit_id else "All business units"

    @property
    def title(self):
        day = self.pay_date.strftime("%d %B %Y").upper()
        unit = f"{self.business_unit.name.upper()} — " if self.business_unit_id else ""
        if self.run_type == RunType.EXPENSE_ALLOWANCE:
            return f"{unit}EXPENSE ALLOWANCES FOR THE MONTH ENDED {day}"
        return f"{unit}PAYROLL FOR THE MONTH ENDED {day}"

    @property
    def is_expense(self):
        return self.run_type == RunType.EXPENSE_ALLOWANCE

    STATUS_STEPS = [
        (RunStatus.DRAFT, "Draft"),
        (RunStatus.CALCULATED, "Calculated"),
        (RunStatus.REVIEWED, "Reviewed"),
        (RunStatus.APPROVED, "Approved"),
        (RunStatus.DISBURSED, "Disbursed"),
    ]

    @property
    def completed_steps(self):
        order = [k for k, _ in self.STATUS_STEPS]
        try:
            idx = order.index(self.status)
        except ValueError:
            return []
        return order[:idx]

    # -- totals computed by grouping, never by hard-coded rows (6.2) -----
    def unit_totals(self):
        rows = (
            self.lines.values("business_unit_code", "business_unit_name")
            .annotate(
                headcount=models.Count("id"),
                gross=models.Sum("gross_pay"),
                paye=models.Sum("paye"),
                nssf_employee=models.Sum("nssf_employee"),
                nssf_employer=models.Sum("nssf_employer"),
                deductions=models.Sum("total_deductions"),
                net=models.Sum("net_pay"),
            )
            .order_by("business_unit_name")
        )
        return list(rows)

    def totals(self):
        return self.lines.aggregate(
            headcount=models.Count("id"),
            gross=models.Sum("gross_pay"),
            paye=models.Sum("paye"),
            nssf_employee=models.Sum("nssf_employee"),
            nssf_employer=models.Sum("nssf_employer"),
            deductions=models.Sum("total_deductions"),
            net=models.Sum("net_pay"),
        )

    @property
    def variance_line_count(self):
        return self.lines.exclude(variance=ZERO).count()

    @property
    def invalid_account_count(self):
        return self.lines.filter(account_valid=False).count()

    @property
    def missing_tin_count(self):
        return self.lines.filter(tin="").count()

    @property
    def missing_nssf_number_count(self):
        return self.lines.filter(nssf_number="").count()

    @property
    def is_balanced(self):
        return self.variance_line_count == 0 and self.lines.exists()

    @property
    def can_generate_bank_file(self):
        return self.status in {RunStatus.APPROVED, RunStatus.DISBURSED} and self.is_balanced

    @property
    def previous_run(self):
        """The most recent earlier run of the same type and scope that has lines."""
        return (
            PayRun.objects.filter(run_type=self.run_type, business_unit=self.business_unit_id)
            .filter(
                models.Q(period_year__lt=self.period_year)
                | models.Q(period_year=self.period_year, period_month__lt=self.period_month)
            )
            .filter(lines__isnull=False)
            .distinct()
            .order_by("-period_year", "-period_month")
            .first()
        )


class PayRunLine(models.Model):
    pay_run = models.ForeignKey(PayRun, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="pay_lines")

    # Snapshot of the employee master at calculation time.
    employee_name = models.CharField(max_length=200)
    staff_id = models.CharField(max_length=20)
    position = models.CharField(max_length=150, blank=True)
    business_unit_code = models.CharField(max_length=16)
    business_unit_name = models.CharField(max_length=120)
    bank_name = models.CharField(max_length=120, blank=True)
    payment_reference = models.CharField(max_length=40, blank=True)
    account_valid = models.BooleanField(default=True)
    email = models.EmailField(blank=True)
    tin = models.CharField(max_length=20, blank=True)
    nssf_number = models.CharField(max_length=20, blank=True)

    # Money.
    basic_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    additional_earnings = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    gross_pay = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    chargeable_income = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    paye = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    paye_band = models.CharField(max_length=60, blank=True)
    nssf_employee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    nssf_employer = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    statutory_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_pay = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # Live arithmetic check (Recommendation 6.6): gross - (net + statutory + deductions).
    variance = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["business_unit_name", "employee_name"]
        constraints = [
            models.UniqueConstraint(fields=["pay_run", "employee"], name="uniq_line_per_run_employee")
        ]

    def __str__(self):
        return f"{self.employee_name} - {self.pay_run.period_label}"

    @property
    def missing_tin(self):
        return not (self.tin or "").strip()

    @property
    def missing_nssf_number(self):
        return not (self.nssf_number or "").strip()

    def recompute_totals(self):
        q = Decimal("0.01")
        d = lambda v: Decimal(v or 0)
        self.gross_pay = (d(self.basic_amount) + d(self.additional_earnings)).quantize(q)
        self.statutory_total = (d(self.paye) + d(self.nssf_employee)).quantize(q)
        self.net_pay = (
            self.gross_pay - self.statutory_total - d(self.total_deductions)
        ).quantize(q)
        self.variance = (
            self.gross_pay - (self.net_pay + self.statutory_total + d(self.total_deductions))
        ).quantize(q)


class PayRunLineItem(models.Model):
    class ItemType(models.TextChoices):
        EARNING = "EARNING", "Earning"
        STATUTORY = "STATUTORY", "Statutory"
        DEDUCTION = "DEDUCTION", "Deduction"

    line = models.ForeignKey(PayRunLine, on_delete=models.CASCADE, related_name="items")
    item_type = models.CharField(max_length=12, choices=ItemType.choices)
    code = models.CharField(max_length=30)
    label = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["item_type", "code"]

    def __str__(self):
        return f"{self.get_item_type_display()} {self.code}: {self.amount}"
