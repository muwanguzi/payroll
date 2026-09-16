import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

from apps.organization.models import BusinessUnit, Department


class EngagementType(models.TextChoices):
    PAYROLL_STAFF = "PAYROLL_STAFF", "Payroll staff"
    CONTRACTOR = "CONTRACTOR", "Independent contractor"
    WAGE = "WAGE", "Wage staff"


class EmployeeStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"


class EmployeeQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status=EmployeeStatus.ACTIVE)

    def active_on(self, period_date):
        return self.filter(
            models.Q(date_joined__lte=period_date)
            & (models.Q(date_left__isnull=True) | models.Q(date_left__gte=period_date))
        )

    def missing_tin(self):
        return self.filter(tin="")

    def missing_nssf_number(self):
        return self.filter(nssf_number="")


class Employee(models.Model):
    """The single source of truth for a person (Recommendation 6.1).

    Every screen, pay run and bank file reads from this one record instead of
    re-typing name / ID / bank details on four separate sheets - which is what
    produced the name-spelling drift called out in Section 5.2 of the review.
    """

    # --- Identity ---------------------------------------------------------
    staff_id = models.CharField(
        "Staff ID",
        max_length=20,
        unique=True,
        help_text="Mandatory (Recommendation 6.11). Matching is always by ID, never by name.",
    )
    full_legal_name = models.CharField(max_length=200)
    national_id = models.CharField("National ID", max_length=30, blank=True)
    email = models.EmailField(blank=True, help_text="Used to email payslips.")
    tin = models.CharField("TIN", max_length=20, blank=True, help_text="URA Tax Identification Number, for PAYE returns.")
    nssf_number = models.CharField("NSSF number", max_length=20, blank=True)

    # --- Placement ------------------------------------------------------
    position = models.CharField(max_length=150, help_text="Mandatory field (Recommendation 6.11).")
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="employees"
    )
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="employees"
    )
    engagement_type = models.CharField(
        max_length=20, choices=EngagementType.choices, default=EngagementType.PAYROLL_STAFF
    )

    # --- Pay bases (mirrors the single "Salary" / "Expense Allowance" columns) ---
    monthly_gross_salary = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Contractual monthly gross - the base for the month-end Salary run.",
    )
    monthly_expense_allowance = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Gross allowance - the base for the mid-month Expense Allowance run.",
    )

    # --- Disbursement details -----------------------------------------
    bank_name = models.CharField(max_length=120, blank=True)
    bank_branch_code = models.CharField(max_length=20, blank=True)
    bank_account_number = models.CharField(max_length=30, blank=True)
    mobile_money_number = models.CharField(max_length=20, blank=True)

    # --- Lifecycle ---------------------------------------------------
    date_joined = models.DateField()
    date_left = models.DateField(null=True, blank=True, help_text="Leaver date. A leaver is deactivated, never deleted.")
    status = models.CharField(max_length=10, choices=EmployeeStatus.choices, default=EmployeeStatus.ACTIVE)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()
    objects = EmployeeQuerySet.as_manager()

    class Meta:
        ordering = ["full_legal_name"]

    def __str__(self):
        return f"{self.full_legal_name} [{self.staff_id}]"

    # -- validation --------------------------------------------------------
    def clean(self):
        errors = {}

        if self.staff_id:
            self.staff_id = self.staff_id.strip()
        if not self.staff_id:
            errors["staff_id"] = "Staff ID is mandatory."
        if not (self.position or "").strip():
            errors["position"] = "Position is mandatory."

        acct = (self.bank_account_number or "").strip()
        if acct:
            if not acct.isdigit():
                errors["bank_account_number"] = "Account number must be numeric."
            else:
                lo = settings.PAYROLL_BANK_ACCT_MIN_LEN
                hi = settings.PAYROLL_BANK_ACCT_MAX_LEN
                if not (lo <= len(acct) <= hi):
                    errors["bank_account_number"] = (
                        f"Account number must be {lo}-{hi} digits (got {len(acct)})."
                    )

        mm = (self.mobile_money_number or "").strip()
        if mm and not re.fullmatch(r"[0-9+]{9,15}", mm):
            errors["mobile_money_number"] = "Enter a valid phone number (digits, optional leading +)."

        if not acct and not mm:
            errors["bank_account_number"] = "Provide a bank account number or a mobile money number."

        if self.date_left and self.date_joined and self.date_left < self.date_joined:
            errors["date_left"] = "Leaver date cannot be before the join date."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Keep status and leaver date consistent.
        if self.date_left and self.status == EmployeeStatus.ACTIVE:
            self.status = EmployeeStatus.INACTIVE
        super().save(*args, **kwargs)

    # -- helpers ---------------------------------------------------------
    def is_active_on(self, period_date):
        if self.date_joined and self.date_joined > period_date:
            return False
        if self.date_left and self.date_left < period_date:
            return False
        return True

    @property
    def payment_reference(self):
        return self.bank_account_number or self.mobile_money_number or ""

    @property
    def has_valid_account(self):
        try:
            self.clean()
        except ValidationError:
            return False
        return True

    @property
    def missing_tin(self):
        return not (self.tin or "").strip()

    @property
    def missing_nssf_number(self):
        return not (self.nssf_number or "").strip()
