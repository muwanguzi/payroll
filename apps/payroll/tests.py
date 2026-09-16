from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from apps.employees.models import Employee, EngagementType
from apps.organization.models import BusinessUnit

from .banking import generate_bank_file
from .models import (
    DeductionApprovalStatus,
    DeductionCode,
    EmployeeDeduction,
    PayRun,
    Recurrence,
    RunStatus,
    RunType,
)
from .services import (
    TransitionError,
    approve_run,
    calculate_run,
    disburse_run,
    review_run,
)


class PayRunTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference")
        cls.admin = User.objects.create_superuser("boss", "b@x.test", "x")
        cls.finance = User.objects.create_user("fin", "f@x.test", "x")
        cls.approver = User.objects.create_user("app", "a@x.test", "x")
        cls.unit = BusinessUnit.objects.first()
        cls.emp = Employee.objects.create(
            staff_id="A-001", full_legal_name="Test Person", position="Reporter",
            business_unit=cls.unit, engagement_type=EngagementType.PAYROLL_STAFF,
            monthly_gross_salary=Decimal("3000000"), monthly_expense_allowance=Decimal("400000"),
            bank_name="Stanbic", bank_account_number="0140012345678",
            date_joined=date(2023, 1, 1),
        )

    def make_run(self, run_type=RunType.SALARY, month=6):
        return PayRun.objects.create(
            run_type=run_type, period_year=2026, period_month=month,
            pay_date=date(2026, month, 27 if run_type == RunType.SALARY else 15),
            created_by=self.admin,
        )


class CalculationTests(PayRunTestBase):
    def test_salary_line_balances(self):
        run = self.make_run()
        calculate_run(run, actor=self.admin)
        line = run.lines.get(staff_id="A-001")
        # gross 3,000,000 -> PAYE 25,000 + 2,590,000*0.3 = 802,000 ; NSSF 5% = 150,000
        self.assertEqual(line.paye, Decimal("802000.00"))
        self.assertEqual(line.nssf_employee, Decimal("150000.00"))
        self.assertEqual(line.net_pay, Decimal("2048000.00"))
        self.assertEqual(line.variance, Decimal("0.00"))
        self.assertEqual(run.status, RunStatus.CALCULATED)

    def test_expense_run_has_no_statutory(self):
        run = self.make_run(RunType.EXPENSE_ALLOWANCE)
        calculate_run(run, actor=self.admin)
        line = run.lines.get(staff_id="A-001")
        self.assertEqual(line.paye, Decimal("0.00"))
        self.assertEqual(line.nssf_employee, Decimal("0.00"))
        self.assertEqual(line.gross_pay, Decimal("400000.00"))
        self.assertEqual(line.net_pay, Decimal("400000.00"))

    def test_recalculation_is_idempotent(self):
        run = self.make_run()
        calculate_run(run, actor=self.admin)
        first = run.lines.get(staff_id="A-001").net_pay
        calculate_run(run, actor=self.admin)
        self.assertEqual(run.lines.count(), 1)
        self.assertEqual(run.lines.get(staff_id="A-001").net_pay, first)

    def test_deduction_reduces_net(self):
        sacco = DeductionCode.objects.get(code="SACCO")
        EmployeeDeduction.objects.create(
            employee=self.emp, code=sacco, amount=Decimal("100000"), recurrence=Recurrence.RECURRING
        )
        run = self.make_run()
        calculate_run(run, actor=self.admin)
        line = run.lines.get(staff_id="A-001")
        self.assertEqual(line.total_deductions, Decimal("100000.00"))
        self.assertEqual(line.net_pay, Decimal("1948000.00"))
        self.assertEqual(line.variance, Decimal("0.00"))

    def test_leaver_excluded(self):
        self.emp.date_left = date(2026, 1, 1)
        self.emp.save()
        run = self.make_run()
        calculate_run(run, actor=self.admin)
        self.assertFalse(run.lines.filter(staff_id="A-001").exists())


class WorkflowTests(PayRunTestBase):
    def test_segregation_of_duties(self):
        run = self.make_run()
        calculate_run(run, actor=self.admin)
        review_run(run, actor=self.finance)
        with self.assertRaises(TransitionError):
            approve_run(run, actor=self.finance)  # same person cannot approve
        approve_run(run, actor=self.approver)
        self.assertEqual(run.status, RunStatus.APPROVED)

    def test_cannot_review_with_variance(self):
        run = self.make_run()
        calculate_run(run, actor=self.admin)
        run.lines.update(variance=Decimal("1.00"))
        with self.assertRaises(TransitionError):
            review_run(run, actor=self.finance)

    def test_loan_balance_decrements_once_on_disburse(self):
        hp = DeductionCode.objects.get(code="HIRE_PURCHASE")
        d = EmployeeDeduction.objects.create(
            employee=self.emp, code=hp, amount=Decimal("500000"),
            opening_balance=Decimal("1200000"), balance=Decimal("1200000"),
        )
        run = self.make_run()
        calculate_run(run, actor=self.admin)
        calculate_run(run, actor=self.admin)  # twice - must not double count
        review_run(run, actor=self.finance)
        approve_run(run, actor=self.approver)
        disburse_run(run, actor=self.admin)
        d.refresh_from_db()
        self.assertEqual(d.balance, Decimal("700000.00"))


class BankFileTests(PayRunTestBase):
    def test_blocks_on_bad_account_and_status(self):
        bad = Employee.objects.create(
            staff_id="A-002", full_legal_name="No Account", position="Intern",
            business_unit=self.unit, monthly_gross_salary=Decimal("1000000"),
            mobile_money_number="0770000000", date_joined=date(2024, 1, 1),
        )
        bad.bank_account_number = "12AB"  # invalid, saved directly
        Employee.objects.filter(pk=bad.pk).update(bank_account_number="12AB")
        run = self.make_run()
        calculate_run(run, actor=self.admin)
        result = generate_bank_file(run)
        self.assertFalse(result.ok)
        self.assertTrue(any("A-002" in e for e in result.errors))

    def test_clean_run_produces_csv(self):
        run = self.make_run()
        calculate_run(run, actor=self.admin)
        review_run(run, actor=self.finance)
        approve_run(run, actor=self.approver)
        result = generate_bank_file(run)
        self.assertTrue(result.ok)
        self.assertIn("A-001", result.csv_text)
        self.assertEqual(result.row_count, 1)


class ComparisonTests(PayRunTestBase):
    def test_previous_run_and_deltas(self):
        from .comparison import compare_runs

        june = self.make_run(month=6)
        calculate_run(june, actor=self.admin)
        july = self.make_run(month=7)
        # bump salary before the second run
        self.emp.monthly_gross_salary = Decimal("3500000")
        self.emp.save()
        # add a new joiner for July
        Employee.objects.create(
            staff_id="A-002", full_legal_name="New Joiner", position="Intern",
            business_unit=self.unit, monthly_gross_salary=Decimal("1200000"),
            bank_account_number="0140011112222", date_joined=date(2026, 7, 1),
        )
        calculate_run(july, actor=self.admin)

        self.assertEqual(july.previous_run.pk, june.pk)
        cmp = compare_runs(july, july.previous_run)
        self.assertEqual(cmp["headcount"], 1)
        self.assertIn("New Joiner", cmp["joiners"])
        self.assertGreater(cmp["gross"], 0)

    def test_no_previous_run_returns_none(self):
        from .comparison import compare_runs

        june = self.make_run(month=6)
        calculate_run(june, actor=self.admin)
        self.assertIsNone(compare_runs(june, june.previous_run))


class BulkPayslipEmailTests(PayRunTestBase):
    def test_emails_only_lines_with_address(self):
        from django.core import mail

        from .payslips import email_run_payslips

        self.emp.email = "test@nextmedia.test"
        self.emp.save()
        Employee.objects.create(
            staff_id="A-009", full_legal_name="No Email", position="Runner",
            business_unit=self.unit, monthly_gross_salary=Decimal("1000000"),
            bank_account_number="0140055556666", date_joined=date(2023, 1, 1),
        )
        run = self.make_run()
        calculate_run(run, actor=self.admin)
        # Payslips are gated on disbursement (Item 2) - progress through the
        # four-officer chain before emailing is expected to work.
        review_run(run, actor=self.finance)
        approve_run(run, actor=self.approver)
        disburse_run(run, actor=self.admin)
        res = email_run_payslips(run)
        self.assertEqual(res.sent, 1)
        self.assertEqual(len(res.skipped), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_emails_nothing_before_disbursement(self):
        from .payslips import email_run_payslips

        self.emp.email = "test@nextmedia.test"
        self.emp.save()
        run = self.make_run()
        calculate_run(run, actor=self.admin)
        res = email_run_payslips(run)
        self.assertEqual(res.sent, 0)
        self.assertEqual(len(res.skipped), 1)
        self.assertIn("not yet disbursed", res.skipped[0][2])


class NotificationTests(PayRunTestBase):
    def test_calculate_notifies_the_reviewer_role(self):
        from django.contrib.auth.models import Group
        from django.core import mail

        reviewer = User.objects.create_user("cpo1", "cpo@nextmedia.test", "x")
        reviewer.groups.add(Group.objects.get(name="Chief People Officer"))

        run = self.make_run()
        calculate_run(run, actor=self.admin)
        self.assertTrue(any("awaiting review" in m.subject for m in mail.outbox))
        self.assertIn("cpo@nextmedia.test", [addr for m in mail.outbox for addr in m.to])


class RunEditDeleteTests(PayRunTestBase):
    def test_edit_notes_and_paydate(self):
        run = self.make_run()
        self.finance.groups.add(__import__("django.contrib.auth.models", fromlist=["Group"]).Group.objects.get(name="Head of Human Capital"))
        self.client.force_login(self.finance)
        r = self.client.post(f"/payroll/runs/{run.pk}/edit/", {"pay_date": "2026-06-28", "notes": "late run"})
        self.assertEqual(r.status_code, 302)
        run.refresh_from_db()
        self.assertEqual(str(run.pay_date), "2026-06-28")
        self.assertEqual(run.notes, "late run")

    def test_delete_draft_run(self):
        run = self.make_run()
        self.finance.groups.add(__import__("django.contrib.auth.models", fromlist=["Group"]).Group.objects.get(name="Head of Human Capital"))
        self.client.force_login(self.finance)
        r = self.client.post(f"/payroll/runs/{run.pk}/delete/")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PayRun.objects.filter(pk=run.pk).exists())

    def test_cannot_delete_approved_run(self):
        from django.contrib.auth.models import Group

        run = self.make_run()
        calculate_run(run, actor=self.admin)
        review_run(run, actor=self.finance)
        approve_run(run, actor=self.approver)
        self.finance.groups.add(Group.objects.get(name="Head of Human Capital"))
        self.client.force_login(self.finance)
        self.client.post(f"/payroll/runs/{run.pk}/delete/")
        self.assertTrue(PayRun.objects.filter(pk=run.pk).exists())


class RunCreateViewTests(PayRunTestBase):
    def setUp(self):
        from django.contrib.auth.models import Group
        self.finance.groups.add(Group.objects.get(name="Head of Human Capital"))
        self.client.force_login(self.finance)

    def test_create_with_explicit_pay_date(self):
        r = self.client.post("/payroll/runs/new/", {
            "run_type": RunType.SALARY, "period_year": "2026", "period_month": "9",
            "pay_date": "2026-09-26", "notes": "manual date",
        })
        self.assertEqual(r.status_code, 302)
        run = PayRun.objects.get(run_type=RunType.SALARY, period_year=2026, period_month=9)
        self.assertEqual(str(run.pay_date), "2026-09-26")
        self.assertIn("26 SEPTEMBER 2026", run.title)

    def test_create_without_pay_date_uses_default(self):
        r = self.client.post("/payroll/runs/new/", {
            "run_type": RunType.EXPENSE_ALLOWANCE, "period_year": "2026", "period_month": "9",
        })
        self.assertEqual(r.status_code, 302)
        run = PayRun.objects.get(run_type=RunType.EXPENSE_ALLOWANCE, period_year=2026, period_month=9)
        self.assertEqual(str(run.pay_date), "2026-09-15")


class PerUnitRunTests(PayRunTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.unit2 = BusinessUnit.objects.exclude(pk=cls.unit.pk).first()
        cls.emp2 = Employee.objects.create(
            staff_id="B-001", full_legal_name="Other Unit Person", position="Editor",
            business_unit=cls.unit2, monthly_gross_salary=Decimal("2000000"),
            bank_account_number="0140044445555", date_joined=date(2023, 1, 1),
        )

    def test_unit_scoped_run_only_calculates_that_unit(self):
        run = PayRun.objects.create(
            run_type=RunType.SALARY, business_unit=self.unit,
            period_year=2026, period_month=8, pay_date=date(2026, 8, 27), created_by=self.admin,
        )
        calculate_run(run, actor=self.admin)
        self.assertTrue(run.lines.filter(staff_id="A-001").exists())
        self.assertFalse(run.lines.filter(staff_id="B-001").exists())
        self.assertIn(self.unit.name.upper(), run.title)

    def test_same_period_runs_for_different_units_coexist(self):
        r1 = PayRun.objects.create(run_type=RunType.SALARY, business_unit=self.unit,
                                   period_year=2026, period_month=8, pay_date=date(2026, 8, 27), created_by=self.admin)
        r2 = PayRun.objects.create(run_type=RunType.SALARY, business_unit=self.unit2,
                                   period_year=2026, period_month=8, pay_date=date(2026, 8, 27), created_by=self.admin)
        self.assertNotEqual(r1.pk, r2.pk)

    def test_create_view_scope_each_makes_one_run_per_unit(self):
        from django.contrib.auth.models import Group
        self.finance.groups.add(Group.objects.get(name="Head of Human Capital"))
        self.client.force_login(self.finance)
        n_units = BusinessUnit.objects.filter(is_active=True).count()
        r = self.client.post("/payroll/runs/new/", {
            "run_type": RunType.SALARY, "business_unit": "each",
            "period_year": "2026", "period_month": "8",
        })
        self.assertEqual(r.status_code, 302)
        made = PayRun.objects.filter(run_type=RunType.SALARY, period_year=2026, period_month=8,
                                     business_unit__isnull=False).count()
        self.assertEqual(made, n_units)

    def test_previous_run_is_unit_scoped(self):
        from .comparison import compare_runs
        july = PayRun.objects.create(run_type=RunType.SALARY, business_unit=self.unit,
                                     period_year=2026, period_month=7, pay_date=date(2026, 7, 27), created_by=self.admin)
        calculate_run(july, actor=self.admin)
        # a group run in June must NOT be picked as the previous run for a unit-scoped August run
        june_group = self.make_run(month=6)
        calculate_run(june_group, actor=self.admin)
        august = PayRun.objects.create(run_type=RunType.SALARY, business_unit=self.unit,
                                       period_year=2026, period_month=8, pay_date=date(2026, 8, 27), created_by=self.admin)
        calculate_run(august, actor=self.admin)
        self.assertEqual(august.previous_run.pk, july.pk)


class DeductionScopeTests(PayRunTestBase):
    def test_salary_scoped_deduction_skipped_on_expense_run(self):
        from apps.payroll.models import DeductionScope
        sacco = DeductionCode.objects.get(code="SACCO")  # applies to both runs
        EmployeeDeduction.objects.create(
            employee=self.emp, code=sacco, amount=Decimal("100000"),
            run_scope=DeductionScope.SALARY,
        )
        sal = self.make_run(RunType.SALARY, month=6)
        calculate_run(sal, actor=self.admin)
        self.assertEqual(sal.lines.get(staff_id="A-001").total_deductions, Decimal("100000.00"))

        exp = self.make_run(RunType.EXPENSE_ALLOWANCE, month=6)
        calculate_run(exp, actor=self.admin)
        self.assertEqual(exp.lines.get(staff_id="A-001").total_deductions, Decimal("0.00"))

    def test_expense_scoped_deduction_only_on_expense_run(self):
        from apps.payroll.models import DeductionScope
        sacco = DeductionCode.objects.get(code="SACCO")
        EmployeeDeduction.objects.create(
            employee=self.emp, code=sacco, amount=Decimal("70000"),
            run_scope=DeductionScope.EXPENSE,
        )
        sal = self.make_run(RunType.SALARY, month=6)
        calculate_run(sal, actor=self.admin)
        self.assertEqual(sal.lines.get(staff_id="A-001").total_deductions, Decimal("0.00"))
        exp = self.make_run(RunType.EXPENSE_ALLOWANCE, month=6)
        calculate_run(exp, actor=self.admin)
        self.assertEqual(exp.lines.get(staff_id="A-001").total_deductions, Decimal("70000.00"))

    def test_code_capability_still_wins(self):
        # Penalty is salary-only; scope BOTH must not force it onto the expense run
        from apps.payroll.models import DeductionScope
        penalty = DeductionCode.objects.get(code="PENALTY")
        EmployeeDeduction.objects.create(
            employee=self.emp, code=penalty, amount=Decimal("40000"),
            run_scope=DeductionScope.BOTH,
        )
        exp = self.make_run(RunType.EXPENSE_ALLOWANCE, month=6)
        calculate_run(exp, actor=self.admin)
        self.assertEqual(exp.lines.get(staff_id="A-001").total_deductions, Decimal("0.00"))


class FourOfficerChainTests(PayRunTestBase):
    """Head of Human Capital -> Chief People Officer -> Chief Audit Officer -> Chief Finance Officer."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from django.contrib.auth.models import Group
        def mk(u, role):
            usr = User.objects.create_user(u, f"{u}@x.test", "x")
            usr.groups.add(Group.objects.get(name=role))
            return usr
        cls.hhc = mk("hhc_u", "Head of Human Capital")
        cls.cpo = mk("cpo_u", "Chief People Officer")
        cls.cao = mk("cao_u", "Chief Audit Officer")
        cls.cfo = mk("cfo_u", "Chief Finance Officer")

    def test_only_hhc_can_create_a_run(self):
        self.client.force_login(self.cpo)
        r = self.client.post("/payroll/runs/new/", {"run_type": RunType.SALARY, "period_year": "2026", "period_month": "9"})
        self.assertEqual(r.status_code, 302)  # bounced with an error message
        self.assertFalse(PayRun.objects.filter(period_month=9, period_year=2026).exists())

        self.client.force_login(self.hhc)
        r = self.client.post("/payroll/runs/new/", {"run_type": RunType.SALARY, "period_year": "2026", "period_month": "9"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(PayRun.objects.filter(period_month=9, period_year=2026).exists())

    def test_each_step_gated_to_its_officer(self):
        run = self.make_run()
        run.created_by = self.hhc
        run.save(update_fields=["created_by"])

        self.client.force_login(self.hhc)
        self.client.post(f"/payroll/runs/{run.pk}/calculate/")
        run.refresh_from_db(); self.assertEqual(run.status, RunStatus.CALCULATED)

        # CAO cannot review
        self.client.force_login(self.cao)
        self.client.post(f"/payroll/runs/{run.pk}/review/")
        run.refresh_from_db(); self.assertEqual(run.status, RunStatus.CALCULATED)

        # CPO reviews
        self.client.force_login(self.cpo)
        self.client.post(f"/payroll/runs/{run.pk}/review/")
        run.refresh_from_db(); self.assertEqual(run.status, RunStatus.REVIEWED)

        # CFO cannot approve
        self.client.force_login(self.cfo)
        self.client.post(f"/payroll/runs/{run.pk}/approve/")
        run.refresh_from_db(); self.assertEqual(run.status, RunStatus.REVIEWED)

        # CAO approves
        self.client.force_login(self.cao)
        self.client.post(f"/payroll/runs/{run.pk}/approve/")
        run.refresh_from_db(); self.assertEqual(run.status, RunStatus.APPROVED)

        # CAO cannot also disburse (role + segregation)
        self.client.post(f"/payroll/runs/{run.pk}/disburse/")
        run.refresh_from_db(); self.assertEqual(run.status, RunStatus.APPROVED)

        # CFO disburses
        self.client.force_login(self.cfo)
        self.client.post(f"/payroll/runs/{run.pk}/disburse/")
        run.refresh_from_db(); self.assertEqual(run.status, RunStatus.DISBURSED)

    def test_reviewer_cannot_be_the_preparer(self):
        run = self.make_run()
        calculate_run(run, actor=self.hhc)  # preparer
        run.created_by = self.hhc; run.save(update_fields=["created_by"])
        with self.assertRaises(TransitionError):
            review_run(run, actor=self.hhc)

    def test_disburser_cannot_be_the_approver(self):
        run = self.make_run()
        calculate_run(run, actor=self.hhc)
        review_run(run, actor=self.cpo)
        approve_run(run, actor=self.cao)
        with self.assertRaises(TransitionError):
            disburse_run(run, actor=self.cao)

    def test_only_cfo_gets_the_bank_file(self):
        run = self.make_run()
        calculate_run(run, actor=self.hhc)
        review_run(run, actor=self.cpo)
        approve_run(run, actor=self.cao)
        self.client.force_login(self.cao)
        self.assertEqual(self.client.get(f"/payroll/runs/{run.pk}/bank-file/").status_code, 302)
        self.client.force_login(self.cfo)
        self.assertEqual(self.client.get(f"/payroll/runs/{run.pk}/bank-file/").status_code, 200)


class NumberOfRunsDeductionTests(PayRunTestBase):
    """Item 4: an instalment-style deduction stops itself after N runs."""

    def _cycle(self, month):
        run = self.make_run(month=month)
        calculate_run(run, actor=self.admin)
        review_run(run, actor=self.finance)
        approve_run(run, actor=self.approver)
        disburse_run(run, actor=self.admin)
        return run

    def test_stops_after_the_configured_number_of_runs(self):
        code = DeductionCode.objects.get(code="SACCO")
        ded = EmployeeDeduction.objects.create(
            employee=self.emp, code=code, amount=Decimal("50000"),
            number_of_runs=2, approval_status=DeductionApprovalStatus.APPROVED,
        )

        run1 = self._cycle(6)
        self.assertEqual(run1.lines.get(employee=self.emp).total_deductions, Decimal("50000.00"))
        ded.refresh_from_db()
        self.assertEqual(ded.runs_applied, 1)
        self.assertTrue(ded.is_active)

        run2 = self._cycle(7)
        self.assertEqual(run2.lines.get(employee=self.emp).total_deductions, Decimal("50000.00"))
        ded.refresh_from_db()
        self.assertEqual(ded.runs_applied, 2)
        self.assertFalse(ded.is_active, "should stop itself once the run cap is reached")

        run3 = self._cycle(8)
        self.assertEqual(run3.lines.get(employee=self.emp).total_deductions, Decimal("0.00"))

    def test_open_ended_when_number_of_runs_is_blank(self):
        code = DeductionCode.objects.get(code="SACCO")
        EmployeeDeduction.objects.create(
            employee=self.emp, code=code, amount=Decimal("10000"),
            approval_status=DeductionApprovalStatus.APPROVED,
        )
        for month in (6, 7, 8):
            run = self._cycle(month)
            self.assertEqual(run.lines.get(employee=self.emp).total_deductions, Decimal("10000.00"))


class DeductionApprovalWorkflowTests(PayRunTestBase):
    """Item 5: per-deduction-type approval pages for the Chief Audit Officer."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from django.contrib.auth.models import Group
        cls.cao = User.objects.create_user("cao_dedu", "cao_dedu@x.test", "x")
        cls.cao.groups.add(Group.objects.get(name="Chief Audit Officer"))
        cls.hr = User.objects.create_user("hr_dedu", "hr_dedu@x.test", "x")
        cls.hr.groups.add(Group.objects.get(name="HR Data Entry"))

    def test_new_deductions_start_pending(self):
        code = DeductionCode.objects.get(code="SACCO")
        ded = EmployeeDeduction.objects.create(employee=self.emp, code=code, amount=Decimal("20000"))
        self.assertEqual(ded.approval_status, DeductionApprovalStatus.PENDING)

    def test_only_cao_can_view_the_review_pages(self):
        code = DeductionCode.objects.get(code="SACCO")
        self.client.force_login(self.hr)
        self.assertEqual(self.client.get("/payroll/deductions/approvals/").status_code, 302)
        self.assertEqual(self.client.get(f"/payroll/deductions/approvals/{code.code}/").status_code, 302)

        self.client.force_login(self.cao)
        self.assertEqual(self.client.get("/payroll/deductions/approvals/").status_code, 200)
        self.assertEqual(self.client.get(f"/payroll/deductions/approvals/{code.code}/").status_code, 200)

    def test_approve_action(self):
        code = DeductionCode.objects.get(code="SACCO")
        ded = EmployeeDeduction.objects.create(employee=self.emp, code=code, amount=Decimal("20000"))
        self.client.force_login(self.cao)
        self.client.post(f"/payroll/deductions/{ded.pk}/review/", {"action": "approve"})
        ded.refresh_from_db()
        self.assertEqual(ded.approval_status, DeductionApprovalStatus.APPROVED)
        self.assertEqual(ded.approval_reviewed_by_id, self.cao.id)

    def test_reject_requires_a_note(self):
        code = DeductionCode.objects.get(code="SACCO")
        ded = EmployeeDeduction.objects.create(employee=self.emp, code=code, amount=Decimal("20000"))
        self.client.force_login(self.cao)

        self.client.post(f"/payroll/deductions/{ded.pk}/review/", {"action": "reject"})
        ded.refresh_from_db()
        self.assertEqual(ded.approval_status, DeductionApprovalStatus.PENDING)

        self.client.post(f"/payroll/deductions/{ded.pk}/review/", {"action": "reject", "note": "duplicate entry"})
        ded.refresh_from_db()
        self.assertEqual(ded.approval_status, DeductionApprovalStatus.REJECTED)
        self.assertEqual(ded.approval_note, "duplicate entry")

    def test_rejected_deduction_stops_applying_to_new_runs(self):
        code = DeductionCode.objects.get(code="SACCO")
        ded = EmployeeDeduction.objects.create(
            employee=self.emp, code=code, amount=Decimal("20000"),
            approval_status=DeductionApprovalStatus.APPROVED,
        )
        run = self.make_run(month=6)
        calculate_run(run, actor=self.admin)
        self.assertEqual(run.lines.get(employee=self.emp).total_deductions, Decimal("20000.00"))

        ded.reject(actor=self.cao, note="not valid")
        run2 = self.make_run(month=7)
        calculate_run(run2, actor=self.admin)
        self.assertEqual(run2.lines.get(employee=self.emp).total_deductions, Decimal("0.00"))

    def test_pending_deduction_still_applies(self):
        code = DeductionCode.objects.get(code="SACCO")
        EmployeeDeduction.objects.create(employee=self.emp, code=code, amount=Decimal("20000"))
        run = self.make_run(month=6)
        calculate_run(run, actor=self.admin)
        self.assertEqual(run.lines.get(employee=self.emp).total_deductions, Decimal("20000.00"))


class MergedPayslipTests(PayRunTestBase):
    """Item 2: one payslip per employee per period, gated on Salary disbursement."""

    def test_merges_salary_and_expense_and_gates_on_disbursement(self):
        salary_run = self.make_run(run_type=RunType.SALARY, month=6)
        expense_run = self.make_run(run_type=RunType.EXPENSE_ALLOWANCE, month=6)
        calculate_run(salary_run, actor=self.admin)
        calculate_run(expense_run, actor=self.admin)
        salary_line = salary_run.lines.get(employee=self.emp)
        expense_line = expense_run.lines.get(employee=self.emp)

        self.client.force_login(self.admin)
        r = self.client.get(f"/payroll/payslip/{salary_line.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "unlock once it is marked")
        self.assertNotContains(r, "TOTAL NET PAY")

        review_run(salary_run, actor=self.finance)
        approve_run(salary_run, actor=self.approver)
        disburse_run(salary_run, actor=self.admin)

        r2 = self.client.get(f"/payroll/payslip/{salary_line.pk}/")
        self.assertContains(r2, "Salary net pay")
        self.assertContains(r2, "Expense allowance net pay")
        self.assertContains(r2, "TOTAL NET PAY")

        # Resolving from the expense line's own pk reaches the same merged bundle.
        r3 = self.client.get(f"/payroll/payslip/{expense_line.pk}/")
        self.assertContains(r3, "Salary net pay")

    def test_pdf_and_email_blocked_until_disbursed(self):
        salary_run = self.make_run(run_type=RunType.SALARY, month=6)
        calculate_run(salary_run, actor=self.admin)
        line = salary_run.lines.get(employee=self.emp)

        self.client.force_login(self.admin)
        r = self.client.get(f"/payroll/payslip/{line.pk}/pdf/")
        self.assertEqual(r.status_code, 302)

        review_run(salary_run, actor=self.finance)
        approve_run(salary_run, actor=self.approver)
        disburse_run(salary_run, actor=self.admin)

        r2 = self.client.get(f"/payroll/payslip/{line.pk}/pdf/")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2["Content-Type"], "application/pdf")
