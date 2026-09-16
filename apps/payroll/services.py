"""Pay-run calculation and lifecycle (Recommendations 6.2, 6.4, 6.6, 6.9).

``calculate_run`` is idempotent: it wipes and rebuilds a run's lines from the
employee master + statutory engine, so re-running it never drifts. Loan
balances are only *projected* here (``balance_after`` on the line item); the
real decrement happens once, in ``disburse_run``.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.employees.models import Employee
from apps.statutory.engine import compute_nssf, compute_paye

from .notifications import notify_transition

from .models import (
    EmployeeDeduction,
    PayRun,
    PayRunLine,
    PayRunLineItem,
    RunStatus,
    RunType,
)

ZERO = Decimal("0.00")


class TransitionError(Exception):
    pass


def _relevant_employees(pay_run: PayRun):
    qs = Employee.objects.active_on(pay_run.pay_date).select_related("business_unit")
    if pay_run.business_unit_id:
        qs = qs.filter(business_unit_id=pay_run.business_unit_id)
    return qs.order_by("business_unit__sequence", "business_unit__name", "full_legal_name")


@transaction.atomic
def calculate_run(pay_run: PayRun, actor=None) -> PayRun:
    if pay_run.status in {RunStatus.APPROVED, RunStatus.DISBURSED}:
        raise TransitionError("An approved run cannot be recalculated. Reopen it first.")

    pay_run.lines.all().delete()

    is_expense = pay_run.run_type == RunType.EXPENSE_ALLOWANCE

    for emp in _relevant_employees(pay_run):
        line = PayRunLine(
            pay_run=pay_run,
            employee=emp,
            employee_name=emp.full_legal_name,
            staff_id=emp.staff_id,
            position=emp.position,
            business_unit_code=emp.business_unit.code,
            business_unit_name=emp.business_unit.name,
            bank_name=emp.bank_name,
            payment_reference=emp.payment_reference,
            account_valid=emp.has_valid_account and bool(emp.payment_reference),
            email=emp.email,
            tin=emp.tin,
            nssf_number=emp.nssf_number,
        )

        items: list[PayRunLineItem] = []

        # --- earnings -------------------------------------------------
        if is_expense:
            base = emp.monthly_expense_allowance or ZERO
            base_label = "Expense allowance"
        else:
            base = emp.monthly_gross_salary or ZERO
            base_label = "Basic salary"
        line.basic_amount = base
        items.append(
            PayRunLineItem(item_type=PayRunLineItem.ItemType.EARNING, code="BASIC", label=base_label, amount=base)
        )

        additional = ZERO
        chargeable = base if not is_expense else ZERO  # basic salary is taxable
        nssf_base = base if not is_expense else ZERO
        for ee in emp.earnings.select_related("code"):
            if not ee.applies_on(pay_run.pay_date):
                continue
            code = ee.code
            if is_expense and not code.applies_to_expense:
                continue
            if not is_expense and not code.applies_to_salary:
                continue
            additional += ee.amount
            if not is_expense and code.is_taxable:
                chargeable += ee.amount
            if not is_expense and code.subject_to_nssf:
                nssf_base += ee.amount
            items.append(
                PayRunLineItem(
                    item_type=PayRunLineItem.ItemType.EARNING,
                    code=code.code, label=code.name, amount=ee.amount,
                )
            )
        line.additional_earnings = additional
        line.gross_pay = (base + additional).quantize(ZERO)

        # --- statutory (Salary run only) ---------------------------
        if not is_expense:
            line.chargeable_income = chargeable.quantize(ZERO)
            paye = compute_paye(chargeable, pay_run.pay_date)
            nssf = compute_nssf(nssf_base, pay_run.pay_date)
            line.paye = paye.amount
            line.paye_band = paye.band_label
            line.nssf_employee = nssf.employee
            line.nssf_employer = nssf.employer
            if paye.amount:
                items.append(PayRunLineItem(
                    item_type=PayRunLineItem.ItemType.STATUTORY, code="PAYE",
                    label=f"PAYE ({paye.band_label})", amount=paye.amount))
            if nssf.employee:
                items.append(PayRunLineItem(
                    item_type=PayRunLineItem.ItemType.STATUTORY, code="NSSF_EE",
                    label="NSSF employee (5%)", amount=nssf.employee))
            if nssf.employer:
                items.append(PayRunLineItem(
                    item_type=PayRunLineItem.ItemType.STATUTORY, code="NSSF_ER",
                    label="NSSF employer (10%)", amount=nssf.employer))

        # --- recurring / one-off deductions ------------------------
        total_ded = ZERO
        for d in emp.deductions.select_related("code"):
            if not d.code.is_active or not d.applies_to_run(pay_run.run_type):
                continue
            if not d.applies_on(pay_run.pay_date):
                continue
            instalment = d.instalment_for_run()
            if instalment <= ZERO:
                continue
            total_ded += instalment
            balance_after = None
            if d.code.is_loan and d.balance is not None:
                balance_after = (d.balance - instalment).quantize(ZERO)
            items.append(
                PayRunLineItem(
                    item_type=PayRunLineItem.ItemType.DEDUCTION,
                    code=d.code.code, label=d.code.name, amount=instalment,
                    balance_after=balance_after,
                )
            )
        line.total_deductions = total_ded.quantize(ZERO)

        line.recompute_totals()
        line.save()
        for it in items:
            it.line = line
        PayRunLineItem.objects.bulk_create(items)

    pay_run.status = RunStatus.CALCULATED
    pay_run.calculated_at = timezone.now()
    pay_run.reviewed_by = pay_run.reviewed_at = None
    pay_run.approved_by = pay_run.approved_at = None
    pay_run.save(update_fields=["status", "calculated_at", "reviewed_by", "reviewed_at", "approved_by", "approved_at"])
    notify_transition(pay_run, "calculated", actor)
    return pay_run


@transaction.atomic
def review_run(pay_run: PayRun, actor) -> PayRun:
    if pay_run.status != RunStatus.CALCULATED:
        raise TransitionError("Only a calculated run can be marked reviewed.")
    if not pay_run.is_balanced:
        raise TransitionError("Run has variance lines - fix the data and recalculate before review.")
    if pay_run.created_by_id and pay_run.created_by_id == getattr(actor, "id", None):
        raise TransitionError(
            "The reviewer must be different from the person who prepared the run (segregation of duties)."
        )
    pay_run.status = RunStatus.REVIEWED
    pay_run.reviewed_by = actor
    pay_run.reviewed_at = timezone.now()
    pay_run.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    notify_transition(pay_run, "reviewed", actor)
    return pay_run


@transaction.atomic
def approve_run(pay_run: PayRun, actor) -> PayRun:
    if pay_run.status != RunStatus.REVIEWED:
        raise TransitionError("Only a reviewed run can be approved.")
    if pay_run.reviewed_by_id == getattr(actor, "id", None):
        raise TransitionError("The approver must be different from the reviewer (segregation of duties).")
    pay_run.status = RunStatus.APPROVED
    pay_run.approved_by = actor
    pay_run.approved_at = timezone.now()
    pay_run.save(update_fields=["status", "approved_by", "approved_at"])
    notify_transition(pay_run, "approved", actor)
    return pay_run


@transaction.atomic
def reopen_run(pay_run: PayRun, actor) -> PayRun:
    if pay_run.status == RunStatus.DISBURSED:
        raise TransitionError("A disbursed run cannot be reopened.")
    pay_run.status = RunStatus.CALCULATED if pay_run.lines.exists() else RunStatus.DRAFT
    pay_run.reviewed_by = pay_run.reviewed_at = None
    pay_run.approved_by = pay_run.approved_at = None
    pay_run.save(update_fields=["status", "reviewed_by", "reviewed_at", "approved_by", "approved_at"])
    return pay_run


@transaction.atomic
def disburse_run(pay_run: PayRun, actor) -> PayRun:
    """Mark the run disbursed and apply deduction bookkeeping exactly once:
    loan balances decrement, and instalment-style deductions (``number_of_runs``)
    count this run towards their cap - both only here, never at calculate time,
    since calculate is idempotent and can run many times before approval."""
    if pay_run.status != RunStatus.APPROVED:
        raise TransitionError("Only an approved run can be disbursed.")
    if pay_run.approved_by_id and pay_run.approved_by_id == getattr(actor, "id", None):
        raise TransitionError(
            "The disbursing officer must be different from the approver (segregation of duties)."
        )

    deduction_items = PayRunLineItem.objects.filter(
        line__pay_run=pay_run, item_type=PayRunLineItem.ItemType.DEDUCTION,
    ).select_related("line__employee")

    for item in deduction_items:
        d = (
            EmployeeDeduction.objects.select_for_update()
            .filter(employee=item.line.employee, code__code=item.code)
            .first()
        )
        if not d:
            continue
        update_fields = []
        if d.code.is_loan and d.balance is not None:
            d.balance = max(ZERO, (d.balance - item.amount))
            update_fields += ["balance"]
            if d.balance <= ZERO:
                d.is_active = False
                if "is_active" not in update_fields:
                    update_fields += ["is_active"]
        if d.number_of_runs is not None:
            d.runs_applied += 1
            update_fields += ["runs_applied"]
            if d.runs_applied >= d.number_of_runs and d.is_active:
                d.is_active = False
                if "is_active" not in update_fields:
                    update_fields += ["is_active"]
        if update_fields:
            d.save(update_fields=update_fields)

    pay_run.status = RunStatus.DISBURSED
    pay_run.disbursed_at = timezone.now()
    pay_run.save(update_fields=["status", "disbursed_at"])
    notify_transition(pay_run, "disbursed", actor)
    return pay_run
