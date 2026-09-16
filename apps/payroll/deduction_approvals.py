"""Per-deduction-type approval pages for the Chief Audit Officer (Item 5).

Reuses ``EmployeeDeduction`` as the single source of truth - no separate
approval-queue model. Every :class:`DeductionCode` gets its own review page
(reachable at ``/payroll/deductions/approvals/<code>/``), scoped to that
type only, so SACCO/Medicare/Food/etc. are reviewed independently.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.permissions import in_role

from .models import DeductionApprovalStatus, DeductionCode, EmployeeDeduction


def _requested_by(deduction: EmployeeDeduction):
    """Who attached this deduction, from its own history - no new field needed."""
    first = deduction.history.order_by("history_date").first()
    return first.history_user if first else None


@login_required
def deduction_approval_index(request):
    if not in_role(request.user, *settings.ROLES_DEDUCTION_APPROVE):
        messages.error(request, "Only the Chief Audit Officer can review deduction approvals.")
        return redirect("dashboard")

    codes = DeductionCode.objects.annotate(
        pending=Count("employeededuction", filter=Q(employeededuction__approval_status=DeductionApprovalStatus.PENDING)),
        approved=Count("employeededuction", filter=Q(employeededuction__approval_status=DeductionApprovalStatus.APPROVED)),
        rejected=Count("employeededuction", filter=Q(employeededuction__approval_status=DeductionApprovalStatus.REJECTED)),
    ).order_by("sequence", "code")

    return render(request, "payroll/deduction_approval_index.html", {
        "codes": codes,
        "total_pending": sum(c.pending for c in codes),
    })


@login_required
def deduction_approval_list(request, code):
    if not in_role(request.user, *settings.ROLES_DEDUCTION_APPROVE):
        messages.error(request, "Only the Chief Audit Officer can review deduction approvals.")
        return redirect("dashboard")

    deduction_code = get_object_or_404(DeductionCode, code=code)
    status_filter = request.GET.get("status", DeductionApprovalStatus.PENDING)

    qs = (
        EmployeeDeduction.objects.filter(code=deduction_code)
        .select_related("employee", "employee__business_unit", "approval_reviewed_by")
        .order_by("-id")
    )
    if status_filter in DeductionApprovalStatus.values:
        qs = qs.filter(approval_status=status_filter)

    entries = list(qs)
    for d in entries:
        d.requested_by = _requested_by(d)

    return render(request, "payroll/deduction_approval_list.html", {
        "deduction_code": deduction_code,
        "entries": entries,
        "status_filter": status_filter,
        "status_choices": DeductionApprovalStatus.choices,
        "counts": {
            status: EmployeeDeduction.objects.filter(code=deduction_code, approval_status=status).count()
            for status, _ in DeductionApprovalStatus.choices
        },
    })


@login_required
@require_POST
def deduction_approval_action(request, pk):
    if not in_role(request.user, *settings.ROLES_DEDUCTION_APPROVE):
        messages.error(request, "Only the Chief Audit Officer can review deduction approvals.")
        return redirect("dashboard")

    deduction = get_object_or_404(EmployeeDeduction.objects.select_related("code", "employee"), pk=pk)
    action = request.POST.get("action")
    note = request.POST.get("note", "").strip()

    if action == "approve":
        deduction.approve(actor=request.user, note=note)
        messages.success(request, f"Approved {deduction.code.name} for {deduction.employee}.")
    elif action == "reject":
        if not note:
            messages.error(request, "A note is required when rejecting a deduction.")
            return redirect("payroll:deduction_approval_list", code=deduction.code.code)
        deduction.reject(actor=request.user, note=note)
        messages.success(request, f"Rejected {deduction.code.name} for {deduction.employee}.")
    else:
        messages.error(request, "Unknown action.")

    return redirect("payroll:deduction_approval_list", code=deduction.code.code)
