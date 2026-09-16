from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

TWO_DP = Decimal("0.01")


class Residency(models.TextChoices):
    RESIDENT = "RESIDENT", "Resident"
    NON_RESIDENT = "NON_RESIDENT", "Non-resident"


class PayeTable(models.Model):
    """A versioned, effective-dated PAYE band table (Recommendation 6.4).

    A rate change is one new table here, not a manual recompute across
    hundreds of rows. The pay-run engine picks the table whose
    ``effective_from`` is the latest one on or before the run's pay date.
    """

    name = models.CharField(max_length=120)
    residency = models.CharField(
        max_length=20, choices=Residency.choices, default=Residency.RESIDENT
    )
    effective_from = models.DateField()
    is_active = models.BooleanField(
        default=True, help_text="Uncheck to keep a historical or draft table without using it."
    )
    source_note = models.TextField(
        blank=True, help_text="Where these figures came from (e.g. URA PAYE rates page, date checked)."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-effective_from", "residency"]
        constraints = [
            models.UniqueConstraint(
                fields=["residency", "effective_from"], name="uniq_paye_table_version"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.get_residency_display()}, from {self.effective_from})"

    def tax_for(self, monthly_income):
        """Return (tax_amount, band_label) for a monthly chargeable income."""
        income = Decimal(monthly_income)
        if income <= 0:
            return Decimal("0.00"), "Below threshold"
        band = (
            self.bands.filter(lower_bound__lt=income)
            .filter(models.Q(upper_bound__isnull=True) | models.Q(upper_bound__gte=income))
            .order_by("-lower_bound")
            .first()
        )
        if band is None:
            return Decimal("0.00"), "Below threshold"
        tax = band.cumulative_base + (income - band.lower_bound) * band.marginal_rate
        tax = tax.quantize(TWO_DP, rounding=ROUND_HALF_UP)
        return tax, band.label

    def clean(self):
        if not self.pk:
            return
        bands = list(self.bands.order_by("sequence", "lower_bound"))
        if bands and bands[0].lower_bound != 0:
            raise ValidationError("The first band must start at 0.")


class PayeBand(models.Model):
    """One marginal band of a :class:`PayeTable`.

    ``cumulative_base`` is the tax already accumulated on all income up to
    ``lower_bound`` - so tax = cumulative_base + (income - lower_bound) * rate.
    The Uganda top-rate surcharge (extra 10% above UGX 10,000,000) is modelled
    as a final band whose marginal rate is 40%.
    """

    table = models.ForeignKey(PayeTable, on_delete=models.CASCADE, related_name="bands")
    sequence = models.PositiveIntegerField(default=1)
    lower_bound = models.DecimalField(max_digits=14, decimal_places=2)
    upper_bound = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text="Leave blank for the top (open-ended) band.",
    )
    marginal_rate = models.DecimalField(
        max_digits=6, decimal_places=4, help_text="As a fraction, e.g. 0.30 for 30%."
    )
    cumulative_base = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Tax accumulated on all income up to the lower bound of this band.",
    )

    class Meta:
        ordering = ["table", "sequence"]

    def __str__(self):
        return f"{self.table_id}: {self.label}"

    @property
    def label(self):
        rate = f"{self.marginal_rate * 100:.10f}".rstrip("0").rstrip(".")
        if self.upper_bound is None:
            return f"Above {self.lower_bound:,.0f} @ {rate}%"
        return f"{self.lower_bound:,.0f}-{self.upper_bound:,.0f} @ {rate}%"


class NssfConfig(models.Model):
    """Effective-dated NSSF rates (Recommendation 6.4).

    Uganda: 5% employee (deducted from pay) + 10% employer (cost, not a
    deduction) = 15% of gross.
    """

    name = models.CharField(max_length=120, default="NSSF standard rates")
    effective_from = models.DateField(unique=True)
    employee_rate = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.05"))
    employer_rate = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.10"))
    is_active = models.BooleanField(default=True)
    source_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-effective_from"]
        verbose_name = "NSSF configuration"
        verbose_name_plural = "NSSF configurations"

    def __str__(self):
        return f"{self.name} (from {self.effective_from})"

    def contributions_for(self, gross_pay):
        gross = Decimal(gross_pay)
        employee = (gross * self.employee_rate).quantize(TWO_DP, rounding=ROUND_HALF_UP)
        employer = (gross * self.employer_rate).quantize(TWO_DP, rounding=ROUND_HALF_UP)
        return employee, employer
