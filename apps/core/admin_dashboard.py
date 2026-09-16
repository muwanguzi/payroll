"""Custom Unfold admin dashboard: KPI cards + quick links."""

from decimal import Decimal

from django.db.models import Count, Sum
from django.urls import reverse


def environment_callback(request):
    # [label, colour] shown as a pill next to the site header.
    return ["Development", "warning"]


def open_runs_badge(request):
    from apps.payroll.models import PayRun, RunStatus

    n = PayRun.objects.exclude(status=RunStatus.DISBURSED).count()
    return str(n) if n else None


def _money(v):
    return f"{Decimal(v or 0):,.0f}"


def dashboard_callback(request, context):
    from apps.employees.models import Employee, EmployeeStatus
    from apps.organization.models import BusinessUnit
    from apps.payroll.models import PayRun, PayRunLine, RunStatus, RunType

    employees = Employee.objects.all()
    active = employees.filter(status=EmployeeStatus.ACTIVE)
    last_salary = (
        PayRun.objects.filter(run_type=RunType.SALARY)
        .order_by("-period_year", "-period_month")
        .first()
    )
    last_net = 0
    if last_salary:
        last_net = last_salary.lines.aggregate(n=Sum("net_pay"))["n"] or 0

    kpis = [
        {
            "title": "Active employees",
            "value": f"{active.count():,}",
            "footer": f"{employees.count():,} records in total",
            "icon": "groups",
        },
        {
            "title": "Business units",
            "value": str(BusinessUnit.objects.filter(is_active=True).count()),
            "footer": "consolidated group view",
            "icon": "apartment",
        },
        {
            "title": "Open pay runs",
            "value": str(PayRun.objects.exclude(status=RunStatus.DISBURSED).count()),
            "footer": f"{PayRun.objects.count()} runs recorded",
            "icon": "receipt_long",
        },
        {
            "title": "Last salary net",
            "value": _money(last_net),
            "footer": last_salary.period_label if last_salary else "no runs yet",
            "icon": "payments",
        },
    ]

    dq = [
        {"label": "Missing position", "value": employees.filter(position="").count()},
        {"label": "No bank / mobile money", "value": employees.filter(bank_account_number="", mobile_money_number="").count()},
        {"label": "Missing TIN", "value": employees.filter(tin="").count()},
        {"label": "Leavers still active", "value": employees.filter(status=EmployeeStatus.ACTIVE, date_left__isnull=False).count()},
    ]

    unit_costs = list(
        active.values("business_unit__name")
        .annotate(head=Count("id"), cost=Sum("monthly_gross_salary"))
        .order_by("-cost")[:12]
    )
    peak = max((u["cost"] or 0 for u in unit_costs), default=0) or 1
    for u in unit_costs:
        u["pct"] = int((float(u["cost"] or 0) / float(peak)) * 100)
        u["cost_display"] = _money(u["cost"])

    recent_runs = [
        {
            "title": r.title,
            "status": r.get_status_display(),
            "status_key": r.status,
            "url": reverse("payroll:run_detail", args=[r.pk]),
            "period": r.period_label,
        }
        for r in PayRun.objects.all()[:6]
    ]

    context.update(
        {
            "kpis": kpis,
            "data_quality": dq,
            "unit_costs": unit_costs,
            "recent_runs": recent_runs,
        }
    )
    return context
