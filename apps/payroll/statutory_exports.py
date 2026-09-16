"""Statutory filing exports (Recommendation 6.10, Phase 4).

Produce ready-to-file PAYE and NSSF return rows from an approved Salary run,
rather than reconstructing them from the payroll sheet each month.
"""

import csv
import io

from .models import PayRun, RunType


def _writer():
    buf = io.StringIO()
    return buf, csv.writer(buf)


def paye_return_csv(run: PayRun) -> str:
    """One row per employee: identity, gross, chargeable income, PAYE."""
    buf, w = _writer()
    w.writerow([
        "TIN", "Staff ID", "Employee name", "Business unit",
        "Gross pay", "Chargeable income", "PAYE", "PAYE band",
    ])
    total = 0
    for line in run.lines.order_by("business_unit_name", "employee_name"):
        w.writerow([
            line.tin, line.staff_id, line.employee_name, line.business_unit_name,
            f"{line.gross_pay:.2f}", f"{line.chargeable_income:.2f}",
            f"{line.paye:.2f}", line.paye_band,
        ])
        total += line.paye
    w.writerow([])
    w.writerow(["", "", "", "TOTAL PAYE", "", "", f"{total:.2f}", ""])
    return buf.getvalue()


def nssf_return_csv(run: PayRun) -> str:
    """One row per employee: NSSF number, gross, 5% employee, 10% employer, 15% total."""
    buf, w = _writer()
    w.writerow([
        "NSSF number", "Staff ID", "Employee name", "Business unit",
        "Gross pay", "Employee 5%", "Employer 10%", "Total 15%",
    ])
    t_ee = t_er = 0
    for line in run.lines.order_by("business_unit_name", "employee_name"):
        total15 = line.nssf_employee + line.nssf_employer
        w.writerow([
            line.nssf_number, line.staff_id, line.employee_name, line.business_unit_name,
            f"{line.gross_pay:.2f}", f"{line.nssf_employee:.2f}",
            f"{line.nssf_employer:.2f}", f"{total15:.2f}",
        ])
        t_ee += line.nssf_employee
        t_er += line.nssf_employer
    w.writerow([])
    w.writerow(["", "", "", "TOTAL", "", f"{t_ee:.2f}", f"{t_er:.2f}", f"{t_ee + t_er:.2f}"])
    return buf.getvalue()


def available_for(run: PayRun) -> bool:
    return run.run_type == RunType.SALARY and run.lines.exists()
