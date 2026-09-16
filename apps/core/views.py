import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date
from django.utils.http import http_date

from apps.core.audit import LIMIT_CHOICES, build_audit_entries
from apps.core.permissions import in_role
from apps.employees.models import Employee, EmployeeStatus
from apps.organization.models import BusinessUnit
from apps.payroll.models import PayRun, RunStatus

# Documents surfaced under Documents. Each file lives in docs/ (single source
# of truth; the user manual is also published as a shareable Artifact).
DOCUMENTS = {
    "user-manual": {
        "title": "Payroll User Manual",
        "file": "user-manual.html",
        "summary": "How HR and the four-officer chain run the two monthly pay cycles — "
                   "from the employee master record through calculation, review, approval and the bank file.",
        "contents": [
            "Getting started & what each role can do",
            "The monthly rhythm and the run lifecycle",
            "HR: add / edit employees, recurring deductions, bulk CSV load",
            "Head of Human Capital: create, calculate and recalculate a pay run",
            "Chief People Officer → Chief Audit Officer → Chief Finance Officer: review, approve, disburse",
            "Reference: Uganda PAYE bands, NSSF, codes",
            "Troubleshooting & glossary",
        ],
    },
}


@login_required
def documents(request):
    docs = []
    for slug, meta in DOCUMENTS.items():
        path = settings.BASE_DIR / "docs" / meta["file"]
        docs.append({
            "slug": slug,
            "updated": (
                datetime.date.fromtimestamp(path.stat().st_mtime) if path.exists() else None
            ),
            **meta,
        })
    return render(request, "core/documents.html", {"docs": docs})


@login_required
def document_view(request, slug):
    meta = DOCUMENTS.get(slug)
    if meta is None:
        raise Http404
    path = settings.BASE_DIR / "docs" / meta["file"]
    if not path.exists():
        raise Http404
    resp = FileResponse(open(path, "rb"), content_type="text/html")
    resp["Last-Modified"] = http_date(path.stat().st_mtime)
    return resp


@login_required
def dashboard(request):
    employees = Employee.objects.all()
    active = employees.filter(status=EmployeeStatus.ACTIVE)

    by_unit = (
        active.values("business_unit__name")
        .annotate(headcount=Count("id"), salary_cost=Sum("monthly_gross_salary"))
        .order_by("business_unit__name")
    )

    data_quality = {
        "missing_position": employees.filter(position="").count(),
        "missing_account": employees.filter(bank_account_number="", mobile_money_number="").count(),
        "missing_tin": employees.missing_tin().count(),
        "missing_nssf_number": employees.missing_nssf_number().count(),
        "leavers_still_active": employees.filter(
            status=EmployeeStatus.ACTIVE, date_left__isnull=False
        ).count(),
    }

    context = {
        "employee_count": employees.count(),
        "active_count": active.count(),
        "unit_count": BusinessUnit.objects.filter(is_active=True).count(),
        "by_unit": by_unit,
        "recent_runs": PayRun.objects.all()[:8],
        "open_runs": PayRun.objects.exclude(status=RunStatus.DISBURSED).count(),
        "data_quality": data_quality,
    }
    return render(request, "core/dashboard.html", context)


@login_required
def audit_trail(request):
    """A single, read-only timeline over every model that carries payroll
    integrity: who created/changed/deleted what, and when. Backed by the
    `django-simple-history` tables every tracked model already writes to —
    see apps/core/audit.py. Owned by the Chief Audit Officer."""
    if not in_role(request.user, *settings.ROLES_AUDIT):
        messages.error(request, "Only the Chief Audit Officer can view the audit trail.")
        return redirect("dashboard")

    model_key = request.GET.get("model", "all")
    action = request.GET.get("action", "all")
    actor = request.GET.get("actor", "all")
    since_raw = request.GET.get("since", "")
    since = parse_date(since_raw) if since_raw else None
    try:
        limit = int(request.GET.get("limit", 100))
    except ValueError:
        limit = 100

    entries, meta = build_audit_entries(
        model_key=model_key, action=action, actor=actor, since=since, limit=limit,
    )

    User = get_user_model()
    actors = list(
        User.objects.filter(is_active=True).order_by("username").values_list("username", flat=True)
    )

    context = {
        "entries": entries,
        "model_choices": meta["model_choices"],
        "action_choices": meta["action_choices"],
        "actors": actors,
        "limit_choices": LIMIT_CHOICES,
        "selected": {
            "model": model_key, "action": action, "actor": actor,
            "since": since_raw, "limit": limit,
        },
    }
    return render(request, "core/audit_trail.html", context)
