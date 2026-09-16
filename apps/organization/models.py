from django.db import models
from simple_history.models import HistoricalRecords


class BusinessUnit(models.Model):
    """A Next Media business unit / entity (NBS, Sanyuka, Next Radio, ...).

    Recommendation 6.2: the business unit is a *field* on the employee record,
    not a physical block of rows in a worksheet, so adding or removing an
    employee can never break a total elsewhere.
    """

    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=16, unique=True)
    logo = models.ImageField(
        upload_to="unit-logos/", blank=True, null=True,
        help_text="Shown on payslips for this unit's employees. PNG with transparency works best.",
    )
    is_active = models.BooleanField(default=True)
    sequence = models.PositiveIntegerField(default=100, help_text="Display order on reports.")
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["sequence", "name"]

    def __str__(self):
        return self.name


class Department(models.Model):
    name = models.CharField(max_length=120)
    business_unit = models.ForeignKey(
        BusinessUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="departments",
    )
    is_active = models.BooleanField(default=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "business_unit"], name="uniq_department_per_unit"
            )
        ]

    def __str__(self):
        if self.business_unit_id:
            return f"{self.name} ({self.business_unit.code})"
        return self.name
