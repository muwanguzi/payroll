"""Bulk update of the employee master from a CSV (Recommendation 6.1).

Finance / HR keep working in a spreadsheet, then upload it: match by Staff ID,
show a row-by-row old -> new preview, and only commit on confirmation. Only the
columns present in the file are touched.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.organization.models import BusinessUnit

from .models import Employee, EmployeeStatus, EngagementType

# column name -> (model field, coercer)
_DECIMAL_FIELDS = {"monthly_gross_salary", "monthly_expense_allowance"}
_TEXT_FIELDS = {"position", "email", "tin", "nssf_number", "bank_name", "bank_account_number"}
_STATUS_FIELD = "status"
UPDATABLE = _DECIMAL_FIELDS | _TEXT_FIELDS | {_STATUS_FIELD}

TEMPLATE_HEADER = ["staff_id", "monthly_gross_salary", "monthly_expense_allowance", "status"]


@dataclass
class RowPlan:
    line_no: int
    staff_id: str
    employee: Employee | None = None
    changes: list = field(default_factory=list)   # (field, old, new)
    error: str = ""

    @property
    def ok(self):
        return not self.error and bool(self.changes)


@dataclass
class ImportPlan:
    rows: list = field(default_factory=list)
    header_error: str = ""
    unknown_columns: list = field(default_factory=list)

    @property
    def valid_rows(self):
        return [r for r in self.rows if r.ok]

    @property
    def error_rows(self):
        return [r for r in self.rows if r.error]

    @property
    def noop_rows(self):
        return [r for r in self.rows if not r.error and not r.changes]

    @property
    def field_count(self):
        return sum(len(r.changes) for r in self.valid_rows)


def _coerce(column, raw):
    raw = (raw or "").strip()
    if column in _DECIMAL_FIELDS:
        try:
            val = Decimal(raw.replace(",", ""))
        except (InvalidOperation, ValueError):
            raise ValueError(f"{column}: '{raw}' is not a number")
        if val < 0:
            raise ValueError(f"{column}: must not be negative")
        return val.quantize(Decimal("0.01"))
    if column == _STATUS_FIELD:
        up = raw.upper()
        if up not in EmployeeStatus.values:
            raise ValueError(f"status: must be ACTIVE or INACTIVE (got '{raw}')")
        return up
    return raw


def build_plan(file_obj) -> ImportPlan:
    data = file_obj.read()
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(data))
    plan = ImportPlan()

    if not reader.fieldnames or "staff_id" not in [f.strip().lower() for f in reader.fieldnames]:
        plan.header_error = "The CSV must have a 'staff_id' column."
        return plan

    fieldmap = {f: f.strip().lower() for f in reader.fieldnames}
    update_cols = [c for c in fieldmap.values() if c in UPDATABLE]
    plan.unknown_columns = [
        c for c in fieldmap.values() if c not in UPDATABLE and c != "staff_id"
    ]

    by_sid = {e.staff_id: e for e in Employee.objects.all()}

    for i, raw_row in enumerate(reader, start=2):
        row = {fieldmap[k]: v for k, v in raw_row.items() if k is not None}
        sid = (row.get("staff_id") or "").strip()
        rp = RowPlan(line_no=i, staff_id=sid)
        if not sid:
            rp.error = "missing staff_id"
            plan.rows.append(rp)
            continue
        emp = by_sid.get(sid)
        if emp is None:
            rp.error = "no employee with this Staff ID"
            plan.rows.append(rp)
            continue
        rp.employee = emp
        try:
            for col in update_cols:
                if col not in row or (row.get(col) or "").strip() == "":
                    continue
                new_val = _coerce(col, row[col])
                old_val = getattr(emp, col)
                if str(old_val) != str(new_val):
                    rp.changes.append((col, old_val, new_val))
        except ValueError as exc:
            rp.error = str(exc)
        plan.rows.append(rp)

    return plan


@transaction.atomic
def apply_plan(plan: ImportPlan, actor=None) -> dict:
    updated = 0
    fields = 0
    for rp in plan.valid_rows:
        emp = rp.employee
        for col, _old, new in rp.changes:
            setattr(emp, col, new)
            fields += 1
        emp.save()
        updated += 1
    return {"updated": updated, "fields": fields, "skipped": len(plan.error_rows)}


def template_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(TEMPLATE_HEADER)
    for e in Employee.objects.all()[:5]:
        w.writerow([e.staff_id, f"{e.monthly_gross_salary:.2f}", f"{e.monthly_expense_allowance:.2f}", e.status])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Bulk onboarding of NEW employees
# ---------------------------------------------------------------------------
CREATE_REQUIRED = ["staff_id", "full_legal_name", "position", "business_unit", "date_joined"]
CREATE_OPTIONAL = [
    "national_id", "email", "tin", "nssf_number", "department", "engagement_type",
    "monthly_gross_salary", "monthly_expense_allowance",
    "bank_name", "bank_branch_code", "bank_account_number", "mobile_money_number",
]
CREATE_TEMPLATE_HEADER = CREATE_REQUIRED + [
    "email", "engagement_type", "monthly_gross_salary", "monthly_expense_allowance",
    "bank_name", "bank_account_number",
]


@dataclass
class NewRow:
    line_no: int
    staff_id: str
    name: str = ""
    unit: str = ""
    error: str = ""
    instance: Employee | None = None

    @property
    def ok(self):
        return not self.error


@dataclass
class CreatePlan:
    rows: list = field(default_factory=list)
    header_error: str = ""

    @property
    def valid_rows(self):
        return [r for r in self.rows if r.ok]

    @property
    def error_rows(self):
        return [r for r in self.rows if r.error]


def _parse_date(raw):
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"date_joined: '{raw}' is not a recognised date (use YYYY-MM-DD)")


def build_create_plan(file_obj) -> CreatePlan:
    data = file_obj.read()
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(data))
    plan = CreatePlan()

    cols = [c.strip().lower() for c in (reader.fieldnames or [])]
    missing = [c for c in CREATE_REQUIRED if c not in cols]
    if missing:
        plan.header_error = "Missing required column(s): " + ", ".join(missing)
        return plan

    units = {u.code.lower(): u for u in BusinessUnit.objects.all()}
    units.update({u.name.lower(): u for u in BusinessUnit.objects.all()})
    existing = set(Employee.objects.values_list("staff_id", flat=True))
    seen = set()

    for i, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        sid = row.get("staff_id", "")
        r = NewRow(line_no=i, staff_id=sid, name=row.get("full_legal_name", ""), unit=row.get("business_unit", ""))
        if not sid:
            r.error = "missing staff_id"
            plan.rows.append(r); continue
        if sid in existing or sid in seen:
            r.error = "Staff ID already exists"
            plan.rows.append(r); continue
        seen.add(sid)

        unit = units.get(row.get("business_unit", "").lower())
        if unit is None:
            r.error = f"unknown business unit '{row.get('business_unit')}'"
            plan.rows.append(r); continue

        try:
            emp = Employee(
                staff_id=sid,
                full_legal_name=row.get("full_legal_name", ""),
                national_id=row.get("national_id", ""),
                email=row.get("email", ""),
                tin=row.get("tin", ""),
                nssf_number=row.get("nssf_number", ""),
                position=row.get("position", ""),
                business_unit=unit,
                engagement_type=(row.get("engagement_type") or EngagementType.PAYROLL_STAFF).upper(),
                bank_name=row.get("bank_name", ""),
                bank_branch_code=row.get("bank_branch_code", ""),
                bank_account_number=row.get("bank_account_number", ""),
                mobile_money_number=row.get("mobile_money_number", ""),
                date_joined=_parse_date(row.get("date_joined")),
            )
            for money_col in ("monthly_gross_salary", "monthly_expense_allowance"):
                if row.get(money_col):
                    setattr(emp, money_col, _coerce(money_col, row[money_col]))
            if emp.engagement_type not in EngagementType.values:
                raise ValueError(f"engagement_type: '{emp.engagement_type}' is not valid")
            emp.full_clean(exclude=["department"])
            r.instance = emp
        except ValidationError as exc:
            r.error = "; ".join(f"{k}: {' '.join(v)}" for k, v in exc.message_dict.items())
        except ValueError as exc:
            r.error = str(exc)
        plan.rows.append(r)

    return plan


@transaction.atomic
def apply_create_plan(plan: CreatePlan, actor=None) -> dict:
    created = 0
    for r in plan.valid_rows:
        r.instance.save()
        created += 1
    return {"created": created, "skipped": len(plan.error_rows)}


def create_template_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CREATE_TEMPLATE_HEADER)
    unit = BusinessUnit.objects.first()
    w.writerow([
        "NEW-001", "Jane Doe", "News Reporter", unit.code if unit else "NBS",
        date.today().isoformat(), "jane.doe@nextmedia.test", "PAYROLL_STAFF",
        "2500000.00", "300000.00", "Stanbic", "0140012345678",
    ])
    return buf.getvalue()
