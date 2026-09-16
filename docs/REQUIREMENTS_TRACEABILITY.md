# Requirements traceability — Next_Media_Payroll_System_Analysis

How each recommendation in the review maps to this build. Scope delivered:
**Phase 1 + 2 in full, plus Phase 3 (workflow, RBAC, payslips including PDF +
email) and the Phase 4 reporting / statutory-export layer.**

| Rec. | Requirement | Status | Where |
|---|---|---|---|
| 6.1 | One employee master record (single source of truth) | ✅ Done | `employees.Employee` — name, staff ID, national ID, position, dept, business unit, engagement type, bank/mobile-money, join/leave dates, status. `simple_history` audit. |
| 6.2 | Multi-entity structure without hard-coded rows | ✅ Done | `organization.BusinessUnit` as a FK field; `PayRun.unit_totals()` / `totals()` use `GROUP BY`, never cell references. |
| 6.3 | Two linked pay-run types | ✅ Done | `payroll.PayRun.run_type` = Expense Allowance (mid-month) / Salary (month-end); deduction codes flagged per run type. |
| 6.4 | Automated statutory calculation engine | ✅ Done | `statutory.PayeTable`/`PayeBand`/`NssfConfig` (versioned, effective-dated) + `statutory/engine.py`. Shows the band used on every line and payslip. |
| 6.5 | Configurable earnings & deduction codes | ✅ Done | `payroll.EarningCode` / `DeductionCode` (+ `EmployeeEarning` / `EmployeeDeduction`). Loans carry a balance that decrements on disbursement and self-deactivates at zero. New codes added in admin, no code change. |
| 6.6 | Built-in, always-on validation | ✅ Done | Every `PayRunLine` stores `variance = gross − (net + statutory + deductions)`; run detail flags non-zero lines; review is blocked while any variance exists. Derived run title (no hand-typed period string). |
| 6.7 | One-click bank file generation | ✅ Done | `payroll/banking.py` → CSV per run or per business unit. Account numeric/length check on every record (`PAYROLL_BANK_ACCT_MIN/MAX_LEN`), also enforced at data entry in `Employee.clean()`. Bad records block the file. |
| 6.8 | Access control and an audit trail | ✅ Done | Groups **HR Data Entry / Finance Review / Approver** seeded with permissions; view-level `RoleRequiredMixin` / `in_role`; calculated fields are read-only (admin) and never in a form; `django-simple-history` records who/when/old→new on every master model and the pay run. |
| 6.9 | Approval workflow | ✅ Done | `RunStatus`: Draft → Calculated → Reviewed → Approved → Disbursed. Reviewer and approver captured with timestamps; approver must differ from reviewer; bank file only from an approved run. **E-mail notifications** on each transition (`payroll/notifications.py`) ping the next role's inbox. |
| 6.10 | Payslips and reporting | ✅ Done | Per-line payslip as print-ready HTML **and PDF** (`payroll/payslips.py`, xhtml2pdf); bulk PDF per run/unit; email one payslip **or email the whole run at once** (`email_run_payslips`, skips no-email/zero-net). Reports area (`apps/reports`): month-over-month group totals, salary cost by business unit, employee **year-to-date** (list + per-employee), and a **prior-period comparison** on every run (`payroll/comparison.py`) — headline gross/PAYE/net deltas plus joiners/leavers vs the previous same-type run. Statutory e-filing exports: **PAYE return CSV** and **NSSF return CSV** from a calculated Salary run (`payroll/statutory_exports.py`). |
| 6.1 (ops) | Keep working in a spreadsheet | ✅ Added | **In-app employee add / edit forms** (`/employees/new/`, `/employees/<id>/edit/`) — no Django admin needed for routine HR work; model validation surfaced per field. **Recurring deductions / earnings** added, edited and removed from the employee page (`/employees/<id>/<kind>/…`). **Bulk update** existing (`/employees/bulk-update/`) and **bulk onboard** new joiners (`/employees/import/`) from CSV — both with a row-by-row preview and an error/skip report, nothing written until confirmed. HR / Finance only; downloadable templates. |
| 6.3/6.9 (ops) | Edit / cancel a pay run | ✅ Added | `/payroll/runs/<id>/edit/` (pay date + notes, blocked once approved) and delete for a draft/calculated run — Finance only. |
| 6.11 | Data-quality safeguards | ✅ Done | `staff_id` and `position` mandatory in `Employee.clean()`; account format validated at entry; single master record removes cross-sheet name drift by construction; dashboard "data-quality watch" panel. |
| §5.7 | Bank reconciliation sign inconsistency | ✅ Fixed by design | Reconciliation is now `sum(line net) vs grouped total` computed one way for every unit; no per-unit hand-written formula to flip. |

## Phase map (from §7 of the review)

- **Phase 1** — employee master + digitised structure, grouped totals: **complete**.
- **Phase 2** — automated PAYE/NSSF + live validation: **complete**.
- **Phase 3** — approval workflow, RBAC, payslips: **complete** (payslips as HTML + PDF + email).
- **Phase 4** — reporting, history, statutory e-filing exports: **core delivered** — YTD and
  month-over-month views, cost-by-entity, prior-period run comparison, PAYE/NSSF return CSVs,
  `simple_history` history layer, workflow e-mail notifications, bulk CSV employee update.
  Remaining polish: charts/dashboards beyond the basic bar, direct URA/NSSF portal file formats
  (the CSVs are structured for import but not a specific portal template), and scheduled/emailed
  report runs.
