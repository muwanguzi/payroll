"""Create demo login accounts and give a sample of employees real pay figures
so a pay run produces meaningful numbers. Development convenience only.
"""

import random
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.employees.models import Employee
from apps.payroll.models import DeductionCode, EmployeeDeduction, Recurrence

USERS = [
    ("hr", "HR Data Entry", "Hilda", "Rukundo"),
    ("hhc", "Head of Human Capital", "Harriet", "Kaggwa"),
    ("cpo", "Chief People Officer", "Peter", "Okello"),
    ("cao", "Chief Audit Officer", "Agnes", "Nakato"),
    ("cfo", "Chief Finance Officer", "Charles", "Mugisha"),
]


class Command(BaseCommand):
    help = "Create demo users (password: payroll123) and sample pay data."

    @transaction.atomic
    def handle(self, *args, **opts):
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@nextmedia.test", "payroll123")
            self.stdout.write(self.style.SUCCESS("superuser 'admin' / payroll123"))

        for username, role, first, last in USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last, "is_staff": True,
                          "email": f"{username}@nextmedia.test"},
            )
            if created:
                user.set_password("payroll123")
                user.save()
            group = Group.objects.filter(name=role).first()
            if group:
                user.groups.set([group])
            self.stdout.write(self.style.SUCCESS(f"user '{username}' / payroll123  ({role})"))

        rng = random.Random(42)
        sacco = DeductionCode.objects.filter(code="SACCO").first()
        hp = DeductionCode.objects.filter(code="HIRE_PURCHASE").first()
        employees = list(Employee.objects.all())
        for emp in employees:
            emp.monthly_gross_salary = Decimal(rng.randrange(900_000, 12_000_000, 50_000))
            emp.monthly_expense_allowance = Decimal(rng.randrange(150_000, 900_000, 25_000))
            if not emp.bank_name:
                emp.bank_name = rng.choice(["Stanbic", "Centenary", "DFCU", "Absa"])
            if not emp.bank_account_number:
                emp.bank_account_number = "".join(str(rng.randint(0, 9)) for _ in range(13))
            if not emp.email:
                slug = emp.full_legal_name.strip().lower().replace(" ", ".")
                emp.email = f"{slug}@nextmedia.test"
            if not emp.tin:
                emp.tin = str(rng.randrange(1000000000, 9999999999))
            if not emp.nssf_number:
                emp.nssf_number = f"NSSF{rng.randrange(100000, 999999)}"
            emp.save()

            if sacco and rng.random() < 0.6:
                EmployeeDeduction.objects.get_or_create(
                    employee=emp, code=sacco,
                    defaults={"amount": Decimal(rng.randrange(50_000, 300_000, 10_000)),
                              "recurrence": Recurrence.RECURRING},
                )
            if hp and rng.random() < 0.25:
                total = Decimal(rng.randrange(1_000_000, 6_000_000, 100_000))
                EmployeeDeduction.objects.get_or_create(
                    employee=emp, code=hp,
                    defaults={"amount": Decimal(rng.randrange(200_000, 600_000, 50_000)),
                              "recurrence": Recurrence.RECURRING,
                              "opening_balance": total, "balance": total},
                )
        self.stdout.write(self.style.SUCCESS(f"sample pay figures on {len(employees)} employees"))
