from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase

from apps.employees.models import Employee
from apps.organization.models import BusinessUnit
from apps.payroll.models import PayRun, RunType
from apps.payroll.payslips import email_payslip, get_payslip_bundle, payslip_bundles_for_run, render_payslip_pdf
from apps.payroll.services import approve_run, calculate_run, disburse_run, review_run
from apps.payroll.statutory_exports import nssf_return_csv, paye_return_csv


class Phase34TestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference")
        cls.admin = User.objects.create_superuser("boss", "b@x.test", "x")
        cls.reviewer = User.objects.create_user("rev", "r@x.test", "x")
        cls.approver = User.objects.create_user("app2", "a2@x.test", "x")
        cls.disburser = User.objects.create_user("dis", "d@x.test", "x")
        unit = BusinessUnit.objects.first()
        cls.emp = Employee.objects.create(
            staff_id="A-001", full_legal_name="Test Person", position="Reporter",
            business_unit=unit, monthly_gross_salary=Decimal("3000000"),
            bank_name="Stanbic", bank_account_number="0140012345678",
            email="test@nextmedia.test", tin="1000000001", nssf_number="NSSF123",
            date_joined=date(2023, 1, 1),
        )
        cls.pay_run = PayRun.objects.create(
            run_type=RunType.SALARY, period_year=2026, period_month=6,
            pay_date=date(2026, 6, 27), created_by=cls.admin,
        )
        calculate_run(cls.pay_run, actor=cls.admin)
        cls.line = cls.pay_run.lines.get(staff_id="A-001")
        # Payslips are gated on disbursement (Item 2) - take the run all the
        # way through the four-officer chain so payslip tests see the ready state.
        review_run(cls.pay_run, actor=cls.reviewer)
        approve_run(cls.pay_run, actor=cls.approver)
        disburse_run(cls.pay_run, actor=cls.disburser)
        cls.line.refresh_from_db()


class PdfPayslipTests(Phase34TestBase):
    def test_single_payslip_is_pdf(self):
        bundle = get_payslip_bundle(self.line)
        self.assertTrue(bundle.ready)
        pdf = render_payslip_pdf(bundle)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_bulk_payslip_is_pdf(self):
        pdf = render_payslip_pdf(payslip_bundles_for_run(self.pay_run))
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_email_payslip_attaches_pdf(self):
        to = email_payslip(get_payslip_bundle(self.line))
        self.assertEqual(to, "test@nextmedia.test")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].attachments), 1)
        self.assertEqual(mail.outbox[0].attachments[0][2], "application/pdf")

    def test_email_without_address_raises(self):
        self.line.email = ""
        self.line.save()
        with self.assertRaises(ValueError):
            email_payslip(get_payslip_bundle(self.line))

    def test_email_before_disbursement_raises(self):
        undisbursed = PayRun.objects.create(
            run_type=RunType.SALARY, period_year=2026, period_month=7,
            pay_date=date(2026, 7, 27), created_by=self.admin,
        )
        calculate_run(undisbursed, actor=self.admin)
        line = undisbursed.lines.get(staff_id="A-001")
        with self.assertRaises(ValueError):
            email_payslip(get_payslip_bundle(line))


class StatutoryExportTests(Phase34TestBase):
    def test_paye_return_has_totals_and_tin(self):
        csv_text = paye_return_csv(self.pay_run)
        self.assertIn("1000000001", csv_text)
        self.assertIn("TOTAL PAYE", csv_text)
        self.assertIn("802000.00", csv_text)  # PAYE on 3,000,000

    def test_nssf_return_splits_15pc(self):
        csv_text = nssf_return_csv(self.pay_run)
        self.assertIn("NSSF123", csv_text)
        self.assertIn("150000.00", csv_text)  # employee 5%
        self.assertIn("300000.00", csv_text)  # employer 10%
        self.assertIn("450000.00", csv_text)  # total 15%


class ReportViewTests(Phase34TestBase):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_report_index_renders(self):
        r = self.client.get("/reports/?year=2026")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Salary cost by business unit")

    def test_employee_ytd_renders(self):
        r = self.client.get("/reports/ytd/?year=2026")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Test Person")

    def test_employee_ytd_detail_renders(self):
        r = self.client.get(f"/reports/ytd/{self.emp.pk}/?year=2026")
        self.assertEqual(r.status_code, 200)


class UnitLogoPayslipTests(Phase34TestBase):
    def test_pdf_embeds_the_unit_logo_when_set(self):
        import io
        from PIL import Image
        from django.core.files.base import ContentFile
        from apps.organization.models import BusinessUnit
        from apps.payroll.payslips import get_payslip_bundle, render_payslip_pdf

        buf = io.BytesIO(); Image.new("RGBA", (40, 20), (255, 0, 0, 255)).save(buf, "PNG")
        bu = BusinessUnit.objects.get(pk=self.line.employee.business_unit_id)
        bu.logo.save("t.png", ContentFile(buf.getvalue()), save=True)

        pdf = render_payslip_pdf(get_payslip_bundle(self.line))
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn(b"/XObject", pdf)  # an image was embedded

    def test_screen_payslip_shows_unit_name_without_logo(self):
        self.client.force_login(self.admin)
        r = self.client.get(f"/payroll/payslip/{self.line.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.line.business_unit_name)
