"""Cross-system audit trail — a read-only, human-readable merge of the
`django-simple-history` tables that already sit behind every model that
matters for payroll integrity (Recommendation 6.8: a full audit trail).

Everything here is read-only: it never writes history, it only formats it.
The source of truth stays the per-model `<Model>.history` manager that
`simple_history.middleware.HistoryRequestMiddleware` keeps populated on every
save/delete, with the acting user captured automatically.
"""

import calendar
from collections import defaultdict
from decimal import Decimal

from django.contrib.auth import get_user_model

from apps.employees.models import Employee
from apps.organization.models import BusinessUnit, Department
from apps.payroll.models import (
    DeductionCode,
    EarningCode,
    EmployeeDeduction,
    EmployeeEarning,
    PayRun,
)
from apps.statutory.models import NssfConfig, PayeTable

User = get_user_model()

# key -> (model, human label, FK field names on the model whose *target*
# should be resolved for the row's title)
HISTORY_MODELS = {
    "payrun": (PayRun, "Pay run", ("business_unit",)),
    "employee": (Employee, "Employee", ()),
    "deduction": (EmployeeDeduction, "Recurring deduction", ("employee", "code")),
    "earning": (EmployeeEarning, "Recurring earning", ("employee", "code")),
    "businessunit": (BusinessUnit, "Business unit", ()),
    "department": (Department, "Department", ("business_unit",)),
    "earningcode": (EarningCode, "Earning code", ()),
    "deductioncode": (DeductionCode, "Deduction code", ()),
    "payetable": (PayeTable, "PAYE table", ()),
    "nssfconfig": (NssfConfig, "NSSF configuration", ()),
}

ACTION_LABELS = {"+": "created", "~": "updated", "-": "deleted"}
LIMIT_CHOICES = (50, 100, 200, 500)


def _fmt_value(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Decimal):
        return f"{value:,.0f}"
    return str(value)


def _row_title(key, row, resolve):
    """Build a human label for one historical row without touching the
    (possibly since-changed or deleted) live relations — only the resolved
    lookup maps built once for the whole page."""
    if key == "payrun":
        unit = resolve(BusinessUnit, row.business_unit_id) if row.business_unit_id else "All units"
        month = calendar.month_name[row.period_month] if row.period_month else "?"
        return f"{row.get_run_type_display()} · {month} {row.period_year} · {unit}"
    if key == "employee":
        return f"{row.full_legal_name} [{row.staff_id}]"
    if key in ("deduction", "earning"):
        emp = resolve(Employee, row.employee_id) if row.employee_id else "—"
        code_model = EarningCode if key == "earning" else DeductionCode
        code = resolve(code_model, row.code_id) if row.code_id else "—"
        return f"{emp} — {code} {_fmt_value(row.amount)}"
    if key == "businessunit":
        return row.name
    if key == "department":
        unit = resolve(BusinessUnit, row.business_unit_id) if row.business_unit_id else "—"
        return f"{row.name} ({unit})"
    if key in ("earningcode", "deductioncode"):
        return f"{row.code} — {row.name}"
    if key == "payetable":
        return f"{row.name} ({row.get_residency_display()}, from {row.effective_from})"
    if key == "nssfconfig":
        return f"{row.name} (from {row.effective_from})"
    return str(row.pk)


def build_audit_entries(*, model_key="all", action="all", actor="all", since=None, limit=100):
    """Return (entries, meta) — a merged, most-recent-first list of history
    rows across every tracked model, with related ids resolved to readable
    labels in bulk (a handful of extra queries total, not per row)."""
    if limit not in LIMIT_CHOICES:
        limit = 100

    history_type = {"created": "+", "updated": "~", "deleted": "-"}.get(action)
    keys = [model_key] if model_key in HISTORY_MODELS else list(HISTORY_MODELS)

    raw_rows = []
    for key in keys:
        model, label, ref_fields = HISTORY_MODELS[key]
        qs = model.history.all()
        if history_type:
            qs = qs.filter(history_type=history_type)
        if since:
            qs = qs.filter(history_date__date__gte=since)
        if actor != "all":
            qs = qs.filter(history_user__username=actor)
        for row in qs.order_by("-history_date")[:limit]:
            raw_rows.append((row, key, model, label, ref_fields))

    raw_rows.sort(key=lambda t: t[0].history_date, reverse=True)
    raw_rows = raw_rows[:limit]

    # Pass 1 — collect every foreign id we'll need a label for, grouped by
    # the model it points at, so each target is fetched with one query.
    ref_ids = defaultdict(set)
    diffs_by_row = {}
    for row, key, model, label, ref_fields in raw_rows:
        for field_name in ref_fields:
            value = getattr(row, f"{field_name}_id", None)
            if value is not None:
                target = model._meta.get_field(field_name).remote_field.model
                ref_ids[target].add(value)
        if row.history_user_id:
            ref_ids[User].add(row.history_user_id)
        if row.history_type == "~":
            prev = row.prev_record
            if prev is not None:
                changes = []
                for change in row.diff_against(prev).changes:
                    try:
                        field = model._meta.get_field(change.field)
                    except Exception:
                        field = None
                    if field is not None and field.is_relation:
                        target = field.remote_field.model
                        if change.old is not None:
                            ref_ids[target].add(change.old)
                        if change.new is not None:
                            ref_ids[target].add(change.new)
                    changes.append((change.field, change.old, change.new, field))
                diffs_by_row[row.history_id] = changes

    # Pass 2 — bulk-resolve every collected id, once per target model.
    resolved = {}
    for target_model, ids in ref_ids.items():
        resolved[target_model] = {
            obj.pk: str(obj) for obj in target_model.objects.filter(pk__in=ids)
        }

    def resolve(model_cls, value):
        return resolved.get(model_cls, {}).get(value, f"#{value}")

    # Pass 3 — assemble the display list.
    entries = []
    for row, key, model, label, ref_fields in raw_rows:
        changes = []
        for field_name, old, new, field in diffs_by_row.get(row.history_id, []):
            try:
                verbose = model._meta.get_field(field_name).verbose_name
            except Exception:
                verbose = field_name
            if field is not None and field.is_relation:
                old_disp = resolve(field.remote_field.model, old) if old is not None else "—"
                new_disp = resolve(field.remote_field.model, new) if new is not None else "—"
            else:
                old_disp, new_disp = _fmt_value(old), _fmt_value(new)
            changes.append({"field": verbose, "old": old_disp, "new": new_disp})

        entries.append({
            "when": row.history_date,
            "actor": resolve(User, row.history_user_id) if row.history_user_id else "system",
            "action": ACTION_LABELS.get(row.history_type, row.history_type),
            "model_label": label,
            "title": _row_title(key, row, resolve),
            "changes": changes,
        })

    meta = {
        "model_choices": [("all", "All records")] + [(k, v[1]) for k, v in HISTORY_MODELS.items()],
        "action_choices": [
            ("all", "All actions"), ("created", "Created"), ("updated", "Updated"), ("deleted", "Deleted"),
        ],
        "limit_choices": LIMIT_CHOICES,
    }
    return entries, meta
