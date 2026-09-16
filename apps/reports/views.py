import calendar
from datetime import date

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.text import slugify

from apps.employees.models import Employee
from apps.payroll.models import PayRun, PayRunLine, RunStatus, RunType

FINALISED = [RunStatus.APPROVED, RunStatus.DISBURSED, RunStatus.REVIEWED, RunStatus.CALCULATED]


def _years():
    yrs = list(PayRun.objects.values_list("period_year", flat=True).distinct())
    this = date.today().year
    return sorted(set(yrs + [this]), reverse=True)


@login_required
def report_index(request):
    years = _years()
    year = int(request.GET.get("year", years[0] if years else date.today().year))

    lines = PayRunLine.objects.filter(pay_run__period_year=year)

    months = []
    for m in range(1, 13):
        row = {"month": m, "name": calendar.month_name[m]}
        for rt, key in ((RunType.SALARY, "salary"), (RunType.EXPENSE_ALLOWANCE, "expense")):
            agg = lines.filter(pay_run__period_month=m, pay_run__run_type=rt).aggregate(
                head=Count("id"), gross=Sum("gross_pay"), paye=Sum("paye"),
                nssf_ee=Sum("nssf_employee"), nssf_er=Sum("nssf_employer"),
                ded=Sum("total_deductions"), net=Sum("net_pay"),
            )
            row[key] = agg
        months.append(row)

    year_total = lines.aggregate(
        gross=Sum("gross_pay"), paye=Sum("paye"), nssf_ee=Sum("nssf_employee"),
        nssf_er=Sum("nssf_employer"), net=Sum("net_pay"),
    )

    by_unit = (
        lines.filter(pay_run__run_type=RunType.SALARY)
        .values("business_unit_name")
        .annotate(gross=Sum("gross_pay"), paye=Sum("paye"), net=Sum("net_pay"))
        .order_by("business_unit_name")
    )

    salary_net = [
        (calendar.month_abbr[m["month"]], (m["salary"]["net"] or 0)) for m in months
    ]
    peak = max((v for _, v in salary_net), default=0) or 1

    salary_staff_ids = (
        lines.filter(pay_run__run_type=RunType.SALARY)
        .exclude(nssf_employee=0)
        .values_list("staff_id", flat=True)
        .distinct()
    )
    missing_tin_count = Employee.objects.filter(staff_id__in=salary_staff_ids, tin="").count()
    missing_nssf_number_count = Employee.objects.filter(staff_id__in=salary_staff_ids, nssf_number="").count()

    return render(request, "reports/index.html", {
        "years": years, "year": year, "months": months,
        "year_total": year_total, "by_unit": by_unit,
        "salary_net_bars": [(lbl, v, int((float(v) / float(peak)) * 100)) for lbl, v in salary_net],
        "missing_tin_count": missing_tin_count,
        "missing_nssf_number_count": missing_nssf_number_count,
    })


@login_required
def employee_ytd(request):
    years = _years()
    year = int(request.GET.get("year", years[0] if years else date.today().year))
    q = request.GET.get("q", "").strip()

    rows = (
        PayRunLine.objects.filter(pay_run__period_year=year, pay_run__run_type=RunType.SALARY)
        .values("staff_id", "employee_name", "business_unit_name")
        .annotate(
            runs=Count("id"), gross=Sum("gross_pay"), paye=Sum("paye"),
            nssf_ee=Sum("nssf_employee"), nssf_er=Sum("nssf_employer"),
            ded=Sum("total_deductions"), net=Sum("net_pay"),
        )
        .order_by("employee_name")
    )
    if q:
        rows = [r for r in rows if q.lower() in r["employee_name"].lower() or q.lower() in r["staff_id"].lower()]

    missing_tin_ids = set(Employee.objects.missing_tin().values_list("staff_id", flat=True))
    missing_nssf_ids = set(Employee.objects.missing_nssf_number().values_list("staff_id", flat=True))
    for r in rows:
        r["missing_tin"] = r["staff_id"] in missing_tin_ids
        r["missing_nssf_number"] = r["staff_id"] in missing_nssf_ids

    return render(request, "reports/employee_ytd.html", {
        "years": years, "year": year, "q": q, "rows": rows,
    })


@login_required
def employee_ytd_detail(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    years = _years()
    year = int(request.GET.get("year", years[0] if years else date.today().year))
    lines = (
        PayRunLine.objects.filter(employee=employee, pay_run__period_year=year)
        .select_related("pay_run")
        .order_by("pay_run__period_month", "pay_run__run_type")
    )
    totals = lines.aggregate(
        gross=Sum("gross_pay"), paye=Sum("paye"), nssf_ee=Sum("nssf_employee"),
        nssf_er=Sum("nssf_employer"), ded=Sum("total_deductions"), net=Sum("net_pay"),
    )
    return render(request, "reports/employee_ytd_detail.html", {
        "employee": employee, "year": year, "years": years,
        "lines": lines, "totals": totals,
    })
