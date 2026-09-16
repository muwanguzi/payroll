import io
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.permissions import in_role

from apps.organization.models import BusinessUnit
from apps.payroll.models import RunType
from apps.statutory.engine import reverse_gross_from_net

from .forms import COMPONENT_FORMS, EmployeeForm
from .imports import (
    apply_create_plan,
    apply_plan,
    build_create_plan,
    build_plan,
    create_template_csv,
    template_csv,
)
from .models import Employee


def _can_edit(user):
    return in_role(user, *settings.ROLES_EMPLOYEE_EDIT)


def _require_edit(request):
    if not _can_edit(request.user):
        messages.error(request, "Adding and editing employees is limited to HR and Finance.")
        return False
    return True


@login_required
def employee_list(request):
    qs = Employee.objects.select_related("business_unit", "department")
    q = request.GET.get("q", "").strip()
    unit = request.GET.get("unit", "").strip()
    status = request.GET.get("status", "").strip()
    if q:
        qs = qs.filter(
            Q(full_legal_name__icontains=q) | Q(staff_id__icontains=q) | Q(position__icontains=q)
        )
    if unit:
        qs = qs.filter(business_unit__code=unit)
    if status:
        qs = qs.filter(status=status)

    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    context = {
        "page_obj": page,
        "q": q,
        "unit": unit,
        "status": status,
        "total": qs.count(),
        "units": BusinessUnit.objects.filter(is_active=True),
    }
    template = "employees/_rows.html" if request.headers.get("HX-Request") else "employees/list.html"
    return render(request, template, context)


@login_required
def employee_detail(request, pk):
    employee = get_object_or_404(
        Employee.objects.select_related("business_unit", "department"), pk=pk
    )
    return render(
        request,
        "employees/detail.html",
        {
            "employee": employee,
            "deductions": employee.deductions.select_related("code"),
            "earnings": employee.earnings.select_related("code"),
            "pay_lines": employee.pay_lines.select_related("pay_run")[:12],
            "can_edit": _can_edit(request.user),
        },
    )


# --------------------------------------------------------------------------
# Employee add / edit (Recommendation 6.1 - no admin needed for routine work)
# --------------------------------------------------------------------------
@login_required
def employee_create(request):
    if not _require_edit(request):
        return redirect("employees:list")
    form = EmployeeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        emp = form.save()
        messages.success(request, f"Added {emp.full_legal_name} ({emp.staff_id}).")
        return redirect("employees:detail", pk=emp.pk)
    return render(request, "employees/form.html", {"form": form, "mode": "create", "default_fixed_deductions": "0"})


@login_required
def employee_edit(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if not _require_edit(request):
        return redirect("employees:detail", pk=pk)
    form = EmployeeForm(request.POST or None, instance=employee)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Employee updated.")
        return redirect("employees:detail", pk=pk)
    fixed_deductions = sum(
        (d.instalment_for_run() for d in employee.deductions.select_related("code")
         if d.is_active and d.applies_to_run(RunType.SALARY)),
        Decimal("0"),
    )
    return render(request, "employees/form.html", {
        "form": form, "mode": "edit", "employee": employee,
        "default_fixed_deductions": fixed_deductions,
    })


@login_required
def reverse_gross_preview(request):
    """HR enters a target monthly Net Pay (Item 3); this solves the Salary
    monthly gross that produces it, working back through PAYE + NSSF (5%) +
    a flat amount of other fixed deductions. Additive alongside the normal
    gross-first flow - it only pre-fills the Gross field, it never saves."""
    if not _require_edit(request):
        return HttpResponse(status=403)

    result = None
    error = None
    net_raw = request.GET.get("net", "").replace(",", "").strip()
    ded_raw = request.GET.get("deductions", "0").replace(",", "").strip() or "0"
    if net_raw:
        try:
            net_target = Decimal(net_raw)
            fixed_deductions = Decimal(ded_raw)
            result = reverse_gross_from_net(net_target, date.today(), fixed_deductions=fixed_deductions)
        except (InvalidOperation, TypeError):
            error = "Enter a valid net pay amount."
        except ImproperlyConfigured as exc:
            error = str(exc)
        except ValueError as exc:
            error = str(exc)

    return render(request, "employees/_reverse_gross_result.html", {"result": result, "error": error})


# --------------------------------------------------------------------------
# Recurring components (deductions / earnings) from the employee page
# --------------------------------------------------------------------------
@login_required
def component_form(request, pk, kind, cid=None):
    employee = get_object_or_404(Employee, pk=pk)
    if not _require_edit(request):
        return redirect("employees:detail", pk=pk)
    if kind not in COMPONENT_FORMS:
        messages.error(request, "Unknown component type.")
        return redirect("employees:detail", pk=pk)

    FormClass, related_name, label = COMPONENT_FORMS[kind]
    instance = None
    if cid:
        instance = get_object_or_404(getattr(employee, related_name), pk=cid)

    form = FormClass(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.employee = employee
        obj.save()
        messages.success(request, f"{label.capitalize()} {'updated' if cid else 'added'}.")
        return redirect("employees:detail", pk=pk)
    return render(
        request,
        "employees/component_form.html",
        {"form": form, "employee": employee, "kind": kind, "label": label, "editing": bool(cid)},
    )


@login_required
@require_POST
def component_delete(request, pk, kind, cid):
    employee = get_object_or_404(Employee, pk=pk)
    if not _require_edit(request):
        return redirect("employees:detail", pk=pk)
    _, related_name, label = COMPONENT_FORMS[kind]
    obj = get_object_or_404(getattr(employee, related_name), pk=cid)
    obj.delete()
    messages.success(request, f"{label.capitalize()} removed.")
    return redirect("employees:detail", pk=pk)


# --------------------------------------------------------------------------
# CSV: bulk update existing / bulk onboard new
# --------------------------------------------------------------------------
@login_required
def bulk_update(request):
    if not _require_edit(request):
        return redirect("employees:list")

    if request.GET.get("template") == "1":
        resp = HttpResponse(template_csv(), content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="employee-bulk-update-template.csv"'
        return resp

    plan = None
    if request.method == "POST":
        if request.POST.get("confirm") == "1":
            text = request.session.get("_bulk_csv", "")
            if not text:
                messages.error(request, "Upload timed out — please choose the file again.")
                return redirect("employees:bulk_update")
            plan = build_plan(io.StringIO(text))
            summary = apply_plan(plan, actor=request.user)
            request.session.pop("_bulk_csv", None)
            messages.success(
                request,
                f"Updated {summary['updated']} employee(s), {summary['fields']} field(s). "
                f"{summary['skipped']} row(s) with errors were skipped.",
            )
            return redirect("employees:list")

        if request.FILES.get("file"):
            text = request.FILES["file"].read().decode("utf-8-sig", "replace")
            request.session["_bulk_csv"] = text
            plan = build_plan(io.StringIO(text))

    return render(request, "employees/bulk_update.html", {"plan": plan})


@login_required
def bulk_import(request):
    if not _require_edit(request):
        return redirect("employees:list")

    if request.GET.get("template") == "1":
        resp = HttpResponse(create_template_csv(), content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="employee-onboarding-template.csv"'
        return resp

    plan = None
    if request.method == "POST":
        if request.POST.get("confirm") == "1":
            text = request.session.get("_bulk_new_csv", "")
            if not text:
                messages.error(request, "Upload timed out — please choose the file again.")
                return redirect("employees:bulk_import")
            plan = build_create_plan(io.StringIO(text))
            summary = apply_create_plan(plan, actor=request.user)
            request.session.pop("_bulk_new_csv", None)
            messages.success(
                request,
                f"Onboarded {summary['created']} employee(s). {summary['skipped']} row(s) skipped.",
            )
            return redirect("employees:list")

        if request.FILES.get("file"):
            text = request.FILES["file"].read().decode("utf-8-sig", "replace")
            request.session["_bulk_new_csv"] = text
            plan = build_create_plan(io.StringIO(text))

    return render(request, "employees/bulk_import.html", {"plan": plan})
