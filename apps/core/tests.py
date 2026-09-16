from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase

from apps.employees.models import Employee, EngagementType
from apps.organization.models import BusinessUnit
from apps.payroll.models import PayRun, RunType

from .audit import build_audit_entries


class AuditTrailTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference")
        cls.admin = User.objects.create_superuser("boss", "b@x.test", "x")

        def mk(username, role):
            user = User.objects.create_user(username, f"{username}@x.test", "x")
            user.groups.add(Group.objects.get(name=role))
            return user

        cls.hhc = mk("hhc_u", "Head of Human Capital")
        cls.cpo = mk("cpo_u", "Chief People Officer")
        cls.cao = mk("cao_u", "Chief Audit Officer")
        cls.cfo = mk("cfo_u", "Chief Finance Officer")
        cls.unit = BusinessUnit.objects.first()


class AuditTrailAccessTests(AuditTrailTestBase):
    def test_only_the_chief_audit_officer_and_superuser_can_view_it(self):
        for user, allowed in [
            (self.cao, True), (self.admin, True),
            (self.hhc, False), (self.cpo, False), (self.cfo, False),
        ]:
            self.client.force_login(user)
            r = self.client.get("/audit/")
            self.assertEqual(r.status_code, 200 if allowed else 302, msg=user.username)

    def test_anonymous_is_redirected_to_login(self):
        r = self.client.get("/audit/")
        self.assertEqual(r.status_code, 302)


class AuditTrailContentTests(AuditTrailTestBase):
    def test_employee_creation_is_captured_with_the_acting_user(self):
        self.client.force_login(self.hhc)
        self.client.post("/employees/new/", {
            "staff_id": "AUD-001", "full_legal_name": "Audit Person", "position": "Tester",
            "business_unit": self.unit.pk, "engagement_type": EngagementType.PAYROLL_STAFF,
            "monthly_gross_salary": "1000000", "monthly_expense_allowance": "100000",
            "bank_name": "Stanbic", "bank_account_number": "0140099999999",
            "date_joined": "2026-01-01", "status": "ACTIVE",
        })
        entries, _ = build_audit_entries(model_key="employee", limit=50)
        hit = next((e for e in entries if "AUD-001" in e["title"]), None)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["action"], "created")
        self.assertEqual(hit["actor"], "hhc_u")

    def test_pay_run_status_change_is_captured_as_a_diff(self):
        run = PayRun.objects.create(
            run_type=RunType.SALARY, period_year=2026, period_month=8,
            pay_date=date(2026, 8, 27), business_unit=self.unit, created_by=self.hhc,
        )
        run.status = "CALCULATED"
        run._history_user = self.hhc
        run.save(update_fields=["status"])

        entries, _ = build_audit_entries(model_key="payrun", limit=50)
        hit = next((e for e in entries if e["actor"] == "hhc_u" and e["action"] == "updated"), None)
        self.assertIsNotNone(hit)
        fields_changed = {c["field"] for c in hit["changes"]}
        self.assertIn("status", fields_changed)

    def test_filters_narrow_the_timeline(self):
        Employee.objects.create(
            staff_id="AUD-002", full_legal_name="Second Person", position="Tester",
            business_unit=self.unit, engagement_type=EngagementType.PAYROLL_STAFF,
            monthly_gross_salary=Decimal("1000000"), monthly_expense_allowance=Decimal("0"),
            bank_name="Stanbic", bank_account_number="0140088888888",
            date_joined=date(2026, 1, 1),
        )
        all_entries, _ = build_audit_entries(limit=200)
        deletes_only, _ = build_audit_entries(action="deleted", limit=200)
        self.assertGreater(len(all_entries), 0)
        self.assertEqual(deletes_only, [])
