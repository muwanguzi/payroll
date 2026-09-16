import calendar
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.core.permissions import in_role
from apps.organization.models import BusinessUnit
from django.conf import settings

from .banking import generate_bank_file
from .forms import PayRunEditForm
from .models import PayRun, PayRunLine, RunStatus, RunType
from .comparison import compare_runs
from .payslips import (
    email_payslip,
    email_run_payslips,
    get_payslip_bundle,
    payslip_bundles_for_run,
    render_payslip_pdf,
)
from .statutory_exports import available_for, nssf_return_csv, paye_return_csv
from .services import (
    TransitionError,
    approve_run,
    calculate_run,
    disburse_run,
    reopen_run,
    review_run,
)


@login_required
def run_list(request):
    runs = PayRun.objects.select_related("business_unit")
    unit = request.GET.get("unit", "")
    if unit == "all":
        runs = runs.filter(business_unit__isnull=True)
    elif unit:
        runs = runs.filter(business_unit__code=unit)
    return render(request, "payroll/run_list.html", {
        "runs": runs,
        "units": BusinessUnit.objects.filter(is_active=True),
        "unit": unit,
    })


@login_required
def run_create(request):
    if not in_role(request.user, *settings.ROLES_PREPARE):
        messages.error(request, "Only the Head of Human Capital can open a pay run.")
        return redirect("payroll:run_list")

    units = BusinessUnit.objects.filter(is_active=True)
    today = date.today()
    if request.method == "POST":
        run_type = request.POST.get("run_type")
        year = int(request.POST.get("period_year"))
        month = int(request.POST.get("period_month"))
        default_day = 15 if run_type == RunType.EXPENSE_ALLOWANCE else min(27, calendar.monthrange(year, month)[1])
        pay_date = parse_date(request.POST.get("pay_date", "") or "") or date(year, month, default_day)
        notes = request.POST.get("notes", "")
        scope = request.POST.get("business_unit", "")  # "", "all", or a unit id

        # scope = "each" → one Draft run per active business unit
        if scope == "each":
            targets = list(units)
            existing = set(
                PayRun.objects.filter(run_type=run_type, period_year=year, period_month=month)
                .values_list("business_unit_id", flat=True)
            )
            made = 0
            for bu in targets:
                if bu.id in existing:
                    continue
                PayRun.objects.create(
                    run_type=run_type, business_unit=bu, period_year=year, period_month=month,
                    pay_date=pay_date, created_by=request.user, notes=notes,
                )
                made += 1
            messages.success(
                request,
                f"Created {made} run(s), one per business unit. "
                f"{len(targets) - made} already existed." if made < len(targets) else f"Created {made} runs, one per business unit.",
            )
            return redirect("payroll:run_list")

        business_unit = None if scope in ("", "all") else units.filter(pk=scope).first()
        if PayRun.objects.filter(
            run_type=run_type, period_year=year, period_month=month, business_unit=business_unit
        ).exists():
            messages.error(request, "A run of that type already exists for that period and scope.")
            return redirect("payroll:run_create")

        run = PayRun.objects.create(
            run_type=run_type, business_unit=business_unit, period_year=year, period_month=month,
            pay_date=pay_date, created_by=request.user, notes=notes,
        )
        messages.success(request, f"Created {run.title}. Now calculate it.")
        return redirect("payroll:run_detail", pk=run.pk)

    context = {
        "run_types": RunType.choices,
        "units": units,
        "years": range(today.year - 1, today.year + 2),
        "months": [(i, calendar.month_name[i]) for i in range(1, 13)],
        "this_year": today.year,
        "this_month": today.month,
    }
    return render(request, "payroll/run_create.html", context)


@login_required
def run_detail(request, pk):
    run = get_object_or_404(PayRun, pk=pk)
    lines = run.lines.all()
    context = {
        "run": run,
        "lines": lines[:500],
        "line_count": lines.count(),
        "unit_totals": run.unit_totals(),
        "totals": run.totals(),
        "variance_lines": run.lines.exclude(variance=0),
        "invalid_accounts": run.lines.filter(account_valid=False),
        "missing_tin_lines": run.lines.filter(tin=""),
        "missing_nssf_lines": run.lines.filter(nssf_number=""),
        "RunStatus": RunStatus,
        "can_calc": in_role(request.user, *settings.ROLES_PREPARE),
        "can_review": in_role(request.user, *settings.ROLES_REVIEW),
        "can_approve": in_role(request.user, *settings.ROLES_APPROVE),
        "can_disburse": in_role(request.user, *settings.ROLES_DISBURSE),
        "can_reopen": in_role(request.user, *settings.ROLES_REOPEN),
        "statutory_returns_available": available_for(run),
        "comparison": compare_runs(run, run.previous_run) if lines.exists() else None,
    }
    return render(request, "payroll/run_detail.html", context)


def _guard(request, run, *roles):
    if not in_role(request.user, *roles):
        messages.error(request, "You do not have permission for that action.")
        return False
    return True


@login_required
@require_POST
def run_calculate(request, pk):
    run = get_object_or_404(PayRun, pk=pk)
    if not _guard(request, run, *settings.ROLES_PREPARE):
        return redirect("payroll:run_detail", pk=pk)
    try:
        calculate_run(run, actor=request.user)
        messages.success(request, f"Calculated {run.lines.count()} lines. {run.variance_line_count} variance(s).")
    except (TransitionError, Exception) as exc:  # surface config errors to the user
        messages.error(request, f"Calculation failed: {exc}")
    return redirect("payroll:run_detail", pk=pk)


@login_required
@require_POST
def run_review(request, pk):
    run = get_object_or_404(PayRun, pk=pk)
    if not _guard(request, run, *settings.ROLES_REVIEW):
        return redirect("payroll:run_detail", pk=pk)
    try:
        review_run(run, actor=request.user)
        messages.success(request, "Run marked reviewed.")
    except TransitionError as exc:
        messages.error(request, str(exc))
    return redirect("payroll:run_detail", pk=pk)


@login_required
@require_POST
def run_approve(request, pk):
    run = get_object_or_404(PayRun, pk=pk)
    if not _guard(request, run, *settings.ROLES_APPROVE):
        return redirect("payroll:run_detail", pk=pk)
    try:
        approve_run(run, actor=request.user)
        messages.success(request, "Run approved. Bank file can now be generated.")
    except TransitionError as exc:
        messages.error(request, str(exc))
    return redirect("payroll:run_detail", pk=pk)


@login_required
def run_edit(request, pk):
    run = get_object_or_404(PayRun, pk=pk)
    if not in_role(request.user, *settings.ROLES_PREPARE):
        messages.error(request, "Only the Head of Human Capital can edit a pay run.")
        return redirect("payroll:run_detail", pk=pk)
    if run.status in {RunStatus.APPROVED, RunStatus.DISBURSED}:
        messages.error(request, "An approved run cannot be edited — reopen it first.")
        return redirect("payroll:run_detail", pk=pk)

    form = PayRunEditForm(request.POST or None, instance=run)
    if request.method == "POST" and form.is_valid():
        pay_date_changed = "pay_date" in form.changed_data
        form.save()
        msg = "Pay run updated."
        if pay_date_changed and run.status == RunStatus.CALCULATED:
            msg += " The pay date changed — recalculate so statutory figures match."
        messages.success(request, msg)
        return redirect("payroll:run_detail", pk=pk)
    return render(request, "payroll/run_edit.html", {"form": form, "run": run})


@login_required
@require_POST
def run_delete(request, pk):
    run = get_object_or_404(PayRun, pk=pk)
    if not in_role(request.user, *settings.ROLES_PREPARE):
        messages.error(request, "Only the Head of Human Capital can delete a pay run.")
        return redirect("payroll:run_detail", pk=pk)
    if run.status not in {RunStatus.DRAFT, RunStatus.CALCULATED}:
        messages.error(request, "Only a draft or calculated run can be deleted.")
        return redirect("payroll:run_detail", pk=pk)
    title = run.title
    run.delete()
    messages.success(request, f"Deleted {title}.")
    return redirect("payroll:run_list")


@login_required
@require_POST
def run_reopen(request, pk):
    run = get_object_or_404(PayRun, pk=pk)
    if not _guard(request, run, *settings.ROLES_REOPEN):
        return redirect("payroll:run_detail", pk=pk)
    try:
        reopen_run(run, actor=request.user)
        messages.success(request, "Run reopened.")
    except TransitionError as exc:
        messages.error(request, str(exc))
    return redirect("payroll:run_detail", pk=pk)


@login_required
@require_POST
def run_disburse(request, pk):
    run = get_object_or_404(PayRun, pk=pk)
    if not _guard(request, run, *settings.ROLES_DISBURSE):
        return redirect("payroll:run_detail", pk=pk)
    try:
        disburse_run(run, actor=request.user)
        messages.success(request, "Run marked disbursed. Loan balances updated.")
    except TransitionError as exc:
        messages.error(request, str(exc))
    return redirect("payroll:run_detail", pk=pk)


@login_required
def run_bank_file(request, pk):
    run = get_object_or_404(PayRun, pk=pk)
    if not _guard(request, run, *settings.ROLES_DISBURSE):
        return redirect("payroll:run_detail", pk=pk)
    unit = request.GET.get("unit") or None
    result = generate_bank_file(run, business_unit_code=unit)

    if request.GET.get("download") == "1" and result.ok:
        fname = f"bank-{slugify(run.get_run_type_display())}-{run.period_year}-{run.period_month:02d}"
        if unit:
            fname += f"-{slugify(unit)}"
        resp = HttpResponse(result.csv_text, content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="{fname}.csv"'
        return resp

    return render(request, "payroll/bank_file.html", {
        "run": run, "result": result, "unit": unit,
        "units": run.lines.values_list("business_unit_code", "business_unit_name").distinct(),
    })


@login_required
def payslip(request, pk):
    """A merged payslip (Salary + Expense Allowance for the period, Item 2).
    Resolved from any one line's pk; the sibling line is found automatically.
    Gated on disbursement: nothing renders below the "not available" state
    until the Salary run for the period is Disbursed."""
    line = get_object_or_404(
        PayRunLine.objects.select_related("pay_run", "employee").prefetch_related("items"), pk=pk
    )
    bundle = get_payslip_bundle(line)
    unit = BusinessUnit.objects.filter(code=bundle.anchor.business_unit_code).first() if bundle.anchor else None
    return render(request, "payroll/payslip.html", {
        "bundle": bundle, "unit": unit,
        "can_disburse": in_role(request.user, *settings.ROLES_DISBURSE),
    })


def _pdf_response(pdf_bytes, filename):
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@login_required
def payslip_pdf(request, pk):
    line = get_object_or_404(
        PayRunLine.objects.select_related("pay_run").prefetch_related("items"), pk=pk
    )
    bundle = get_payslip_bundle(line)
    if not bundle.ready:
        messages.error(request, "This payslip isn't available yet — the Salary run hasn't been disbursed.")
        return redirect("payroll:payslip", pk=pk)
    fname = f"payslip-{bundle.anchor.staff_id}-{bundle.period_year}-{bundle.period_month:02d}.pdf"
    return _pdf_response(render_payslip_pdf(bundle), fname)


@login_required
@require_POST
def payslip_email(request, pk):
    line = get_object_or_404(PayRunLine.objects.select_related("pay_run").prefetch_related("items"), pk=pk)
    if not _guard(request, line.pay_run, *settings.ROLES_DISBURSE):
        return redirect("payroll:payslip", pk=pk)
    bundle = get_payslip_bundle(line)
    try:
        to = email_payslip(bundle)
        messages.success(request, f"Payslip emailed to {to} (console backend in dev).")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("payroll:payslip", pk=pk)


@login_required
def run_payslips_pdf(request, pk):
    run = get_object_or_404(PayRun, pk=pk)
    if run.run_type != RunType.SALARY or run.status != RunStatus.DISBURSED:
        messages.error(request, "Payslips are only available from a disbursed Salary run.")
        return redirect("payroll:run_detail", pk=pk)
    bundles = payslip_bundles_for_run(run)
    unit = request.GET.get("unit")
    if unit:
        bundles = [b for b in bundles if b.anchor and b.anchor.business_unit_code == unit]
    if not bundles:
        messages.error(request, "No lines to render.")
        return redirect("payroll:run_detail", pk=pk)
    fname = f"payslips-{run.period_year}-{run.period_month:02d}{'-' + unit if unit else ''}.pdf"
    return _pdf_response(render_payslip_pdf(bundles), fname)


@login_required
@require_POST
def run_payslips_email(request, pk):
    run = get_object_or_404(PayRun, pk=pk)
    if not _guard(request, run, *settings.ROLES_DISBURSE):
        return redirect("payroll:run_detail", pk=pk)
    if run.run_type != RunType.SALARY or run.status != RunStatus.DISBURSED:
        messages.error(request, "Payslips are only available from a disbursed Salary run.")
        return redirect("payroll:run_detail", pk=pk)
    result = email_run_payslips(run, business_unit_code=request.GET.get("unit") or None)
    msg = f"Emailed {result.sent} payslip(s)."
    if result.skipped:
        msg += f" Skipped {len(result.skipped)} (no email / zero net / not yet disbursed)."
    if result.failed:
        msg += f" {len(result.failed)} failed."
    (messages.warning if (result.skipped or result.failed) else messages.success)(request, msg)
    return redirect("payroll:run_detail", pk=pk)


def _csv_response(text, filename):
    resp = HttpResponse(text, content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@login_required
def run_paye_return(request, pk):
    run = get_object_or_404(PayRun, pk=pk)
    if not _guard(request, run, *settings.ROLES_DISBURSE):
        return redirect("payroll:run_detail", pk=pk)
    if not available_for(run):
        messages.error(request, "PAYE returns are only available for a calculated Salary run.")
        return redirect("payroll:run_detail", pk=pk)
    return _csv_response(paye_return_csv(run), f"paye-return-{run.period_year}-{run.period_month:02d}.csv")


@login_required
def run_nssf_return(request, pk):
    run = get_object_or_404(PayRun, pk=pk)
    if not _guard(request, run, *settings.ROLES_DISBURSE):
        return redirect("payroll:run_detail", pk=pk)
    if not available_for(run):
        messages.error(request, "NSSF returns are only available for a calculated Salary run.")
        return redirect("payroll:run_detail", pk=pk)
    return _csv_response(nssf_return_csv(run), f"nssf-return-{run.period_year}-{run.period_month:02d}.csv")
