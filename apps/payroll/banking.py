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

from .models import PayRun, RunStatus, RunType

# Uganda business convention seen on the bank's own template ("SEPT", not "SEP").
_MONTH_ABBR = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEPT", 10: "OCT", 11: "NOV", 12: "DEC",
}


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


def _run_preamble_checks(pay_run):
    errors, warnings = [], []
    if pay_run.status not in {RunStatus.APPROVED, RunStatus.DISBURSED}:
        warnings.append(
            f"Run status is {pay_run.get_status_display()} - a bank file should only be "
            "released from an APPROVED run (Recommendation 6.9)."
        )
    if pay_run.variance_line_count:
        errors.append(f"{pay_run.variance_line_count} line(s) have a non-zero variance.")
    return errors, warnings


def generate_bank_file(pay_run: PayRun, business_unit_code: str | None = None) -> BankFileResult:
    lines = pay_run.lines.all()
    if business_unit_code:
        lines = lines.filter(business_unit_code=business_unit_code)
    lines = lines.order_by("business_unit_name", "employee_name")

    errors, warnings = _run_preamble_checks(pay_run)

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


def generate_nbol_bank_file(pay_run: PayRun, business_unit_code: str | None = None) -> BankFileResult:
    """Bank's own bulk-payment upload layout ('nBOL Import rawfile'):
    a title/debit-total preamble, then one row per beneficiary with the
    bank's own Sort Code - not the generic CSV from generate_bank_file().
    """
    lines = pay_run.lines.all()
    if business_unit_code:
        lines = lines.filter(business_unit_code=business_unit_code)
    lines = lines.order_by("business_unit_name", "employee_name")

    errors, warnings = _run_preamble_checks(pay_run)

    rows = []
    total = Decimal("0.00")
    row_count = 0
    for line in lines:
        problem = _validate_account(line)
        if problem:
            errors.append(problem)
            continue
        if not (line.bank_sort_code or "").strip():
            errors.append(f"{line.staff_id} {line.employee_name}: no bank Sort Code on file.")
            continue
        if line.net_pay <= 0:
            warnings.append(f"{line.staff_id} {line.employee_name}: net pay is {line.net_pay}, skipped.")
            continue
        rows.append(line)
        total += line.net_pay
        row_count += 1

    narrative = "Allowance" if pay_run.run_type == RunType.EXPENSE_ALLOWANCE else "Salary"
    title = f"GSTAFF-{_MONTH_ABBR[pay_run.period_month]}-{business_unit_code or 'ALL'}"

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([title, "", "", "", "", "Enable Macros and click on the file converter to generate text file.", ""])
    writer.writerow([f"Debit Amount({settings.PAYROLL_CURRENCY.lower()})", "", "", "", "", "", ""])
    writer.writerow([f"{total:.0f}", "", "", "", "", "", ""])
    writer.writerow(["Beneficiary Name", "Narrative", "Sort Code", "Account Number", "Amount", "", "Address"])
    for line in rows:
        writer.writerow([
            line.employee_name, narrative, line.bank_sort_code, line.payment_reference,
            f"{line.net_pay:.0f}", "", settings.PAYROLL_BANK_PAYING_ADDRESS,
        ])

    return BankFileResult(
        csv_text=buf.getvalue(), row_count=row_count, total=total,
        errors=errors, warnings=warnings,
    )
