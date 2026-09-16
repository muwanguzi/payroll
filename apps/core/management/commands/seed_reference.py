"""Seed reference data: business units, earning/deduction codes, roles, and
the versioned Uganda PAYE / NSSF tables (Recommendations 6.1-6.5, 6.8).

Idempotent - safe to run repeatedly. Statutory figures are sourced from the
URA PAYE rates page and NSSF (5% employee / 10% employer). See docs/RESEARCH.md.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.organization.models import BusinessUnit
from apps.payroll.models import DeductionCode, EarningCode
from apps.statutory.models import NssfConfig, PayeBand, PayeTable, Residency

# name, code, logo file in templates/images/ (blank = generated placeholder)
BUSINESS_UNITS = [
    ("NBS", "NBS", "nbs-television.png"),
    ("NBS Sport", "NBSS", "nbs-sport.png"),
    ("Sanyuka", "SANY", "sanyuka-tv.png"),
    ("Next Radio", "NRAD", "next-radio.png"),
    ("Salaam", "SLM", "salam-tv.png"),
    ("Nile Post", "NILE", "nile-post.png"),
    ("Next Comm", "NCOM", "next-com.png"),
    ("Hillcom", "HILL", "hillcom.png"),
    ("United Media", "UM", "united-media.png"),
    ("Capital FM", "CAP", "capital.png"),
    ("Next Productions", "NPROD", "next-productions.png"),
    ("Next Creata", "NCREA", "next_creata.png"),
    ("Afro Mobile", "AFRO", ""),
    ("NPL", "NPL", ""),
    ("Master Card", "MC", ""),
]

DEDUCTION_CODES = [
    # code, name, salary?, expense?, is_loan
    ("SACCO", "SACCO", True, True, False),
    ("FOOD", "Food", True, True, False),
    ("MEDICARE", "Medicare", True, True, False),
    ("HIRE_PURCHASE", "Hire purchase", True, True, True),
    ("COST_SHARE", "Cost share", True, True, False),
    ("ID_REPLACEMENT", "ID replacement", True, True, False),
    ("FUEL_ADVANCE", "Fuel / Advance", False, True, True),
    ("PENALTY", "Penalty", True, False, False),
]

EARNING_CODES = [
    # code, name, taxable, nssf, salary?, expense?
    ("ACTING_ALLOWANCE", "Acting allowance", True, True, True, False),
    ("OVERTIME", "Overtime", True, True, True, False),
    ("BONUS", "Bonus", True, True, True, False),
    ("BACKPAY", "Back pay", True, True, True, False),
    ("EXTRA_ALLOWANCE", "Extra expense allowance", False, False, False, True),
]

# --- Uganda PAYE, monthly, resident individuals -------------------------
# (income_lower, income_upper|None, marginal_rate, cumulative_base)
PAYE_CURRENT = [
    (0, 235_000, "0.00", "0"),
    (235_000, 335_000, "0.10", "0"),
    (335_000, 410_000, "0.20", "10000"),
    (410_000, 10_000_000, "0.30", "25000"),
    (10_000_000, None, "0.40", "2902000"),  # 30% + 10% top-rate surcharge
]

# Proposed 2026/27 thresholds (tax-free band raised to 335,000). Loaded
# INACTIVE so Finance can activate it with one click when it is assented.
PAYE_2026_27 = [
    (0, 335_000, "0.00", "0"),
    (335_000, 410_000, "0.10", "0"),
    (410_000, 495_000, "0.20", "7500"),
    (495_000, 10_000_000, "0.30", "24500"),
    (10_000_000, None, "0.40", "2876000"),
]

_EMPLOYEE_ADMIN = [
    "employees.add_employee", "employees.change_employee", "employees.view_employee",
    "payroll.add_employeededuction", "payroll.change_employeededuction", "payroll.view_employeededuction",
    "payroll.add_employeeearning", "payroll.change_employeeearning", "payroll.view_employeeearning",
    "organization.view_businessunit", "organization.view_department",
]
_RUN_VIEW = [
    "payroll.view_payrun", "payroll.view_payrunline", "employees.view_employee",
    "statutory.view_payetable", "statutory.view_nssfconfig",
]

ROLE_PERMS = {
    # Data-entry clerks - the employee master only.
    "HR Data Entry": _EMPLOYEE_ADMIN,
    # Head of Human Capital - owns the employee master AND prepares pay runs.
    "Head of Human Capital": _EMPLOYEE_ADMIN + [
        "payroll.add_payrun", "payroll.change_payrun", "payroll.delete_payrun",
    ] + _RUN_VIEW,
    # Chief People Officer - reviews.
    "Chief People Officer": ["payroll.change_payrun"] + _RUN_VIEW,
    # Chief Audit Officer - approves.
    "Chief Audit Officer": ["payroll.change_payrun"] + _RUN_VIEW,
    # Chief Finance Officer - disburses, and owns the bank file / statutory returns.
    "Chief Finance Officer": ["payroll.change_payrun"] + _RUN_VIEW,
}


class Command(BaseCommand):
    help = "Seed business units, codes, roles and versioned PAYE/NSSF tables."

    @transaction.atomic
    def handle(self, *args, **options):
        from django.conf import settings
        from django.core.files import File

        logo_dir = settings.BASE_DIR / "templates" / "images"
        for i, (name, code, logo_file) in enumerate(BUSINESS_UNITS, start=1):
            bu, _ = BusinessUnit.objects.update_or_create(
                name=name, defaults={"code": code, "sequence": i * 10, "is_active": True}
            )
            src = logo_dir / logo_file if logo_file else None
            if src and src.exists() and not bu.logo:
                with src.open("rb") as fh:
                    bu.logo.save(f"{code.lower()}.png", File(fh), save=True)
        self.stdout.write(self.style.SUCCESS(f"{len(BUSINESS_UNITS)} business units"))

        for code, name, sal, exp, loan in DEDUCTION_CODES:
            DeductionCode.objects.update_or_create(
                code=code,
                defaults={"name": name, "applies_to_salary": sal, "applies_to_expense": exp, "is_loan": loan},
            )
        for i, (code, name, tax, nssf, sal, exp) in enumerate(EARNING_CODES, start=1):
            EarningCode.objects.update_or_create(
                code=code,
                defaults={
                    "name": name, "is_taxable": tax, "subject_to_nssf": nssf,
                    "applies_to_salary": sal, "applies_to_expense": exp, "sequence": i * 10,
                },
            )
        self.stdout.write(self.style.SUCCESS("earning / deduction codes"))

        self._paye_table(
            "Uganda PAYE (resident) - current", date(2023, 7, 1), PAYE_CURRENT, True,
            "URA PAYE rates (ura.go.ug/en/domestic-taxes/paye-rates). Threshold UGX 235,000; "
            "top-rate 10% surcharge above UGX 10,000,000 modelled as a 40% band.",
        )
        self._paye_table(
            "Uganda PAYE (resident) - proposed 2026/27", date(2026, 7, 1), PAYE_2026_27, False,
            "Proposed tax-free threshold UGX 335,000. Loaded inactive pending assent.",
        )

        NssfConfig.objects.update_or_create(
            effective_from=date(2022, 9, 1),
            defaults={
                "name": "NSSF standard (5% / 10%)",
                "employee_rate": Decimal("0.05"),
                "employer_rate": Decimal("0.10"),
                "is_active": True,
                "source_note": "NSSF Act 2022 - 15% of gross: 5% employee deduction, 10% employer contribution.",
            },
        )
        self.stdout.write(self.style.SUCCESS("PAYE tables + NSSF config"))

        for role, perms in ROLE_PERMS.items():
            group, _ = Group.objects.get_or_create(name=role)
            wanted = []
            for dotted in perms:
                app_label, codename = dotted.split(".")
                p = Permission.objects.filter(
                    content_type__app_label=app_label, codename=codename
                ).first()
                if p:
                    wanted.append(p)
            group.permissions.set(wanted)
        self.stdout.write(self.style.SUCCESS(
            "roles: HR Data Entry / Head of Human Capital / Chief People Officer / "
            "Chief Audit Officer / Chief Finance Officer"
        ))

    def _paye_table(self, name, eff, rows, active, note):
        table, _ = PayeTable.objects.update_or_create(
            residency=Residency.RESIDENT, effective_from=eff,
            defaults={"name": name, "is_active": active, "source_note": note},
        )
        table.bands.all().delete()
        for seq, (lo, hi, rate, base) in enumerate(rows, start=1):
            PayeBand.objects.create(
                table=table, sequence=seq, lower_bound=Decimal(lo),
                upper_bound=None if hi is None else Decimal(hi),
                marginal_rate=Decimal(rate), cumulative_base=Decimal(base),
            )
