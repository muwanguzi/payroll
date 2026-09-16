"""One-click bank file generation (Recommendation 6.7).

Replaces the manual cell-by-cell cross-referencing on the current Bank Exp
Allowance / Bank Salary sheets. Every record is validated (numeric account,
correct length) here as well as at data entry.
"""

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings

from .models import PayRun, RunStatus


@dataclass
class BankFileResult:
    csv_text: str
    row_count: int
    total: Decimal
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors


def _validate_account(line):
    acct = (line.payment_reference or "").strip()
    if not acct:
        return f"{line.staff_id} {line.employee_name}: no bank account / mobile money on file."
    if not acct.isdigit():
        return f"{line.staff_id} {line.employee_name}: payment reference is not numeric ('{acct}')."
    lo, hi = settings.PAYROLL_BANK_ACCT_MIN_LEN, settings.PAYROLL_BANK_ACCT_MAX_LEN
    if not (lo <= len(acct) <= hi):
        return f"{line.staff_id} {line.employee_name}: account length {len(acct)} outside {lo}-{hi}."
    return None


def generate_bank_file(pay_run: PayRun, business_unit_code: str | None = None) -> BankFileResult:
    lines = pay_run.lines.all()
    if business_unit_code:
        lines = lines.filter(business_unit_code=business_unit_code)
    lines = lines.order_by("business_unit_name", "employee_name")

    errors, warnings = [], []
    if pay_run.status not in {RunStatus.APPROVED, RunStatus.DISBURSED}:
        warnings.append(
            f"Run status is {pay_run.get_status_display()} - a bank file should only be "
            "released from an APPROVED run (Recommendation 6.9)."
        )
    if pay_run.variance_line_count:
        errors.append(f"{pay_run.variance_line_count} line(s) have a non-zero variance.")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["No", "Name", "Staff ID", "Bank", "Account / Mobile Money", "Amount", "Currency"])

    total = Decimal("0.00")
    row_count = 0
    for idx, line in enumerate(lines, start=1):
        problem = _validate_account(line)
        if problem:
            errors.append(problem)
            continue
        if line.net_pay <= 0:
            warnings.append(f"{line.staff_id} {line.employee_name}: net pay is {line.net_pay}, skipped.")
            continue
        writer.writerow([
            idx, line.employee_name, line.staff_id, line.bank_name,
            line.payment_reference, f"{line.net_pay:.2f}", settings.PAYROLL_CURRENCY,
        ])
        total += line.net_pay
        row_count += 1

    writer.writerow([])
    writer.writerow(["", "", "", "", "TOTAL", f"{total:.2f}", settings.PAYROLL_CURRENCY])

    return BankFileResult(
        csv_text=buf.getvalue(), row_count=row_count, total=total,
        errors=errors, warnings=warnings,
    )
