import io
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase

from apps.organization.models import BusinessUnit

from .imports import apply_plan, build_plan
from .models import Employee, EmployeeStatus


class BulkUpdateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference")
        cls.unit = BusinessUnit.objects.first()
        cls.e1 = Employee.objects.create(
            staff_id="A-001", full_legal_name="Alice A", position="Reporter",
            business_unit=cls.unit, monthly_gross_salary=Decimal("1000000"),
            bank_account_number="0140012345678", date_joined=date(2023, 1, 1),
        )
        cls.e2 = Employee.objects.create(
            staff_id="A-002", full_legal_name="Bob B", position="Editor",
            business_unit=cls.unit, monthly_gross_salary=Decimal("2000000"),
            bank_account_number="0140099999999", date_joined=date(2023, 1, 1),
        )

    def plan(self, text):
        return build_plan(io.StringIO(text))

    def test_previews_only_changed_fields(self):
        p = self.plan("staff_id,monthly_gross_salary\nA-001,1500000\nA-002,2000000\n")
        self.assertEqual(len(p.valid_rows), 1)          # A-002 unchanged
        self.assertEqual(len(p.noop_rows), 1)
        field, old, new = p.valid_rows[0].changes[0]
        self.assertEqual(field, "monthly_gross_salary")
        self.assertEqual(new, Decimal("1500000.00"))

    def test_apply_writes_values(self):
        p = self.plan("staff_id,monthly_gross_salary,status\nA-001,1500000,INACTIVE\n")
        summary = apply_plan(p)
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.monthly_gross_salary, Decimal("1500000.00"))
        self.assertEqual(self.e1.status, EmployeeStatus.INACTIVE)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(summary["fields"], 2)

    def test_unknown_staff_id_is_an_error_row(self):
        p = self.plan("staff_id,monthly_gross_salary\nZ-999,123\n")
        self.assertEqual(len(p.error_rows), 1)
        self.assertIn("no employee", p.error_rows[0].error)

    def test_bad_number_is_rejected(self):
        p = self.plan("staff_id,monthly_gross_salary\nA-001,abc\n")
        self.assertEqual(len(p.error_rows), 1)

    def test_missing_staff_id_column(self):
        p = self.plan("name,salary\nAlice,10\n")
        self.assertTrue(p.header_error)

    def test_bulk_update_view_flow(self):
        hr = User.objects.create_user("hr1", "hr@x.test", "x")
        hr.groups.add(Group.objects.get(name="HR Data Entry"))
        self.client.force_login(hr)
        upload = SimpleUploadedFile("u.csv", b"staff_id,monthly_gross_salary\nA-001,1750000\n", content_type="text/csv")
        r = self.client.post("/employees/bulk-update/", {"file": upload})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "1750000")
        r2 = self.client.post("/employees/bulk-update/", {"confirm": "1"})
        self.assertEqual(r2.status_code, 302)
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.monthly_gross_salary, Decimal("1750000.00"))

    def test_bulk_update_forbidden_without_role(self):
        u = User.objects.create_user("nobody", "n@x.test", "x")
        self.client.force_login(u)
        r = self.client.get("/employees/bulk-update/")
        self.assertEqual(r.status_code, 302)  # redirected away


class EmployeeFormViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference")
        cls.unit = BusinessUnit.objects.first()
        cls.hr = User.objects.create_user("hr9", "hr9@x.test", "x")
        cls.hr.groups.add(Group.objects.get(name="HR Data Entry"))
        cls.plain = User.objects.create_user("plain9", "p9@x.test", "x")

    def test_create_employee(self):
        self.client.force_login(self.hr)
        r = self.client.post("/employees/new/", {
            "staff_id": "N-100", "full_legal_name": "Grace K", "position": "Producer",
            "business_unit": self.unit.pk, "engagement_type": "PAYROLL_STAFF",
            "monthly_gross_salary": "2500000", "monthly_expense_allowance": "0",
            "bank_name": "Stanbic", "bank_account_number": "0140012345678",
            "date_joined": "2026-01-15", "status": "ACTIVE",
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Employee.objects.filter(staff_id="N-100").exists())

    def test_create_surfaces_validation(self):
        self.client.force_login(self.hr)
        r = self.client.post("/employees/new/", {
            "staff_id": "N-101", "full_legal_name": "No Position", "position": "",
            "business_unit": self.unit.pk, "engagement_type": "PAYROLL_STAFF",
            "monthly_gross_salary": "0", "monthly_expense_allowance": "0",
            "bank_account_number": "0140012345678",
            "date_joined": "2026-01-15", "status": "ACTIVE",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "mandatory")
        self.assertFalse(Employee.objects.filter(staff_id="N-101").exists())

    def test_edit_employee(self):
        emp = Employee.objects.create(
            staff_id="N-200", full_legal_name="Old Name", position="Editor",
            business_unit=self.unit, monthly_gross_salary=Decimal("1000000"),
            bank_account_number="0140012345678", date_joined=date(2023, 1, 1),
        )
        self.client.force_login(self.hr)
        data = {
            "staff_id": "N-200", "full_legal_name": "New Name", "position": "Senior Editor",
            "business_unit": self.unit.pk, "engagement_type": "PAYROLL_STAFF",
            "monthly_gross_salary": "1400000", "monthly_expense_allowance": "0",
            "bank_account_number": "0140012345678", "date_joined": "2023-01-01", "status": "ACTIVE",
        }
        r = self.client.post(f"/employees/{emp.pk}/edit/", data)
        self.assertEqual(r.status_code, 302)
        emp.refresh_from_db()
        self.assertEqual(emp.full_legal_name, "New Name")
        self.assertEqual(emp.monthly_gross_salary, Decimal("1400000.00"))

    def test_forbidden_without_role(self):
        self.client.force_login(self.plain)
        self.assertEqual(self.client.get("/employees/new/").status_code, 302)


class MissingTinBadgeTests(TestCase):
    """Item 1: a visible flag on the employee record when TIN is blank."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference")
        unit = BusinessUnit.objects.first()
        cls.hr = User.objects.create_user("hr_tin", "hr_tin@x.test", "x")
        cls.hr.groups.add(Group.objects.get(name="HR Data Entry"))
        cls.with_tin = Employee.objects.create(
            staff_id="T-001", full_legal_name="Has TIN", position="Reporter",
            business_unit=unit, tin="1000000001", nssf_number="NSSF1",
            monthly_gross_salary=Decimal("1000000"),
            bank_account_number="0140012345678", date_joined=date(2023, 1, 1),
        )
        cls.without_tin = Employee.objects.create(
            staff_id="T-002", full_legal_name="No TIN", position="Reporter",
            business_unit=unit, monthly_gross_salary=Decimal("1000000"),
            bank_account_number="0140012345679", date_joined=date(2023, 1, 1),
        )

    def test_model_flags(self):
        self.assertFalse(self.with_tin.missing_tin)
        self.assertTrue(self.without_tin.missing_tin)
        self.assertTrue(self.without_tin.missing_nssf_number)

    def test_queryset_helpers(self):
        self.assertIn(self.without_tin, Employee.objects.missing_tin())
        self.assertNotIn(self.with_tin, Employee.objects.missing_tin())

    def test_badge_on_employee_detail(self):
        self.client.force_login(self.hr)
        r = self.client.get(f"/employees/{self.without_tin.pk}/")
        self.assertContains(r, "Missing TIN")
        r2 = self.client.get(f"/employees/{self.with_tin.pk}/")
        self.assertNotContains(r2, "Missing TIN")

    def test_badge_on_employee_list(self):
        self.client.force_login(self.hr)
        r = self.client.get("/employees/")
        self.assertContains(r, 'title="No TIN on file"')


class ReverseGrossCalculatorTests(TestCase):
    """Item 3: HR can enter a target Net Pay and get Gross back (additive tool)."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference")
        cls.hr = User.objects.create_user("hr_rg", "hr_rg@x.test", "x")
        cls.hr.groups.add(Group.objects.get(name="HR Data Entry"))
        cls.plain = User.objects.create_user("plain_rg", "plain_rg@x.test", "x")

    def test_computes_gross_from_net(self):
        self.client.force_login(self.hr)
        r = self.client.get("/employees/reverse-gross/?net=500000")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Gross salary")
        self.assertContains(r, "id_monthly_gross_salary")

    def test_blank_net_shows_nothing(self):
        self.client.force_login(self.hr)
        r = self.client.get("/employees/reverse-gross/")
        self.assertNotContains(r, "Gross salary")

    def test_invalid_net_shows_an_error(self):
        self.client.force_login(self.hr)
        r = self.client.get("/employees/reverse-gross/?net=not-a-number")
        self.assertContains(r, "valid net pay")

    def test_forbidden_without_role(self):
        self.client.force_login(self.plain)
        r = self.client.get("/employees/reverse-gross/?net=500000")
        self.assertEqual(r.status_code, 403)

    def test_calculator_appears_on_the_employee_form(self):
        self.client.force_login(self.hr)
        r = self.client.get("/employees/new/")
        self.assertContains(r, "Reverse-calculate from Net Pay")


class ComponentViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference")
        unit = BusinessUnit.objects.first()
        cls.hr = User.objects.create_user("hrc", "hrc@x.test", "x")
        cls.hr.groups.add(Group.objects.get(name="HR Data Entry"))
        cls.emp = Employee.objects.create(
            staff_id="C-1", full_legal_name="Comp Person", position="Reporter",
            business_unit=unit, monthly_gross_salary=Decimal("2000000"),
            bank_account_number="0140012345678", date_joined=date(2023, 1, 1),
        )

    def test_add_deduction(self):
        from apps.payroll.models import DeductionCode

        self.client.force_login(self.hr)
        sacco = DeductionCode.objects.get(code="SACCO")
        r = self.client.post(f"/employees/{self.emp.pk}/deduction/new/", {
            "code": sacco.pk, "amount": "150000", "run_scope": "SALARY",
            "recurrence": "RECURRING", "is_active": "on",
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.emp.deductions.count(), 1)
        self.assertEqual(self.emp.deductions.get().run_scope, "SALARY")

    def test_scope_incompatible_with_code_is_rejected(self):
        from apps.payroll.models import DeductionCode

        self.client.force_login(self.hr)
        penalty = DeductionCode.objects.get(code="PENALTY")  # salary-run only
        r = self.client.post(f"/employees/{self.emp.pk}/deduction/new/", {
            "code": penalty.pk, "amount": "50000", "run_scope": "EXPENSE",
            "recurrence": "RECURRING", "is_active": "on",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Salary run")
        self.assertEqual(self.emp.deductions.count(), 0)

    def test_loan_without_opening_balance_rejected(self):
        from apps.payroll.models import DeductionCode

        self.client.force_login(self.hr)
        hp = DeductionCode.objects.get(code="HIRE_PURCHASE")
        r = self.client.post(f"/employees/{self.emp.pk}/deduction/new/", {
            "code": hp.pk, "amount": "300000", "run_scope": "BOTH",
            "recurrence": "RECURRING", "is_active": "on",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "opening balance")
        self.assertEqual(self.emp.deductions.count(), 0)

    def test_delete_component(self):
        from apps.payroll.models import DeductionCode, EmployeeDeduction

        d = EmployeeDeduction.objects.create(
            employee=self.emp, code=DeductionCode.objects.get(code="FOOD"), amount=Decimal("50000")
        )
        self.client.force_login(self.hr)
        r = self.client.post(f"/employees/{self.emp.pk}/deduction/{d.pk}/delete/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.emp.deductions.count(), 0)


class BulkImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference")
        cls.unit = BusinessUnit.objects.first()
        cls.hr = User.objects.create_user("hri", "hri@x.test", "x")
        cls.hr.groups.add(Group.objects.get(name="HR Data Entry"))

    def _plan(self, text):
        from .imports import build_create_plan

        return build_create_plan(io.StringIO(text))

    def test_valid_and_invalid_rows(self):
        code = self.unit.code
        text = (
            "staff_id,full_legal_name,position,business_unit,date_joined,bank_account_number\n"
            f"NEW-1,Alice New,Reporter,{code},2026-02-01,0140012345678\n"
            "NEW-2,Bad Unit,Reporter,ZZZ,2026-02-01,0140012345678\n"
            f"NEW-3,Bad Date,Reporter,{code},not-a-date,0140012345678\n"
        )
        p = self._plan(text)
        self.assertEqual(len(p.valid_rows), 1)
        self.assertEqual(len(p.error_rows), 2)

    def test_duplicate_staff_id_blocked(self):
        Employee.objects.create(
            staff_id="DUP-1", full_legal_name="Existing", position="X",
            business_unit=self.unit, bank_account_number="0140012345678",
            date_joined=date(2023, 1, 1),
        )
        p = self._plan(
            "staff_id,full_legal_name,position,business_unit,date_joined,bank_account_number\n"
            f"DUP-1,Clash,Reporter,{self.unit.code},2026-02-01,0140012345678\n"
        )
        self.assertEqual(len(p.error_rows), 1)
        self.assertIn("already exists", p.error_rows[0].error)

    def test_view_flow_creates(self):
        self.client.force_login(self.hr)
        csv = (
            "staff_id,full_legal_name,position,business_unit,date_joined,monthly_gross_salary,bank_account_number\n"
            f"IMP-1,Import One,Reporter,{self.unit.code},2026-03-01,1800000,0140012345678\n"
        ).encode()
        up = SimpleUploadedFile("new.csv", csv, content_type="text/csv")
        r = self.client.post("/employees/import/", {"file": up})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Import One")
        r2 = self.client.post("/employees/import/", {"confirm": "1"})
        self.assertEqual(r2.status_code, 302)
        self.assertTrue(Employee.objects.filter(staff_id="IMP-1").exists())
