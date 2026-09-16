# Next Media Payroll System

A purpose-built replacement for the four-sheet `Template_Payroll.xlsx` workbook,
built to the recommendations in *Next_Media_Payroll_System_Analysis*.

**Covers Phase 1–3 in full plus the Phase 4 reporting layer:** one employee
master record, multi-entity grouping with computed (never hard-coded) totals, the
two monthly pay-run types, an automated Uganda PAYE/NSSF engine on versioned tax
tables, always-on gross = net validation, a draft → reviewed → approved →
disbursed workflow with segregation of duties, role-based access, a full audit
trail, one-click bank files, payslips (HTML + PDF + email), month-over-month and
year-to-date reporting, and PAYE / NSSF return exports.

See [`docs/REQUIREMENTS_TRACEABILITY.md`](docs/REQUIREMENTS_TRACEABILITY.md) for
the recommendation-by-recommendation mapping and
[`docs/RESEARCH.md`](docs/RESEARCH.md) for the statutory sources.

## Stack

Django 6.1 · SQLite (dev) · server-rendered templates + htmx · `django-simple-history`
for the audit trail · `django-unfold` for the admin · `xhtml2pdf` for payslip PDFs.
No build step, no CSS framework — one hand-written stylesheet.

### UI & brand

Follows the Next Media corporate identity from nextmedia.co.ug:
**Proxima Nova** (self-hosted from their site), the Next Media logo, teal
`#19A7B5` / dark-teal `#0B2E38` accents, the vermillion `#D73C26` brand line,
and warm neutrals.

- **App**: a fixed sidebar shell with the Next Media logo, sticky top bar with a
  brand accent line, KPI stat tiles, a workflow step indicator on pay runs,
  status pills, tabular-figure data tables, toast messages, and a
  **light / dark / system** theme toggle (dark mode uses the brand dark teal).
  Fully responsive; the sidebar collapses to a drawer on narrow screens.
- **Admin**: themed with `django-unfold` in the same palette + Proxima Nova — a
  custom dashboard (KPI cards, data-quality panel, salary-cost bars, recent
  runs), a grouped sidebar with an "open pay runs" badge, tabbed inlines, dark mode.

Brand assets live in `static/fonts/` and `static/img/next-media-logo.png`.

### User manual

A full operating manual lives at [`docs/user-manual.html`](docs/user-manual.html) — a
standalone, brand-styled, print-ready HTML document covering every role's tasks,
the run lifecycle, PAYE/NSSF reference and troubleshooting. It is surfaced in the
app under **Documents** (`/documents/`, served from that file — single source of
truth) and is also published as a shareable Artifact.

## Setup

The repo already contains a working `.venv/`. From scratch:

```bash
python3 -m venv --without-pip .venv
curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python   # host had no ensurepip
.venv/bin/pip install -r requirements.txt

.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_reference     # business units, codes, roles, PAYE/NSSF tables
.venv/bin/python manage.py import_template    # ~400 employees from Template_Payroll.xlsx
.venv/bin/python manage.py seed_demo          # demo logins + sample salaries/deductions
.venv/bin/python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

## Demo logins (password `payroll123`)

| User | Role | Can |
|---|---|---|
| `admin` | superuser | everything, Django admin |
| `hr` | HR Data Entry | add/edit employees, deductions, earnings |
| `hhc` | Head of Human Capital | open + calculate pay runs, edit/delete a draft, mark nothing further |
| `cpo` | Chief People Officer | mark a calculated run *Reviewed* |
| `cao` | Chief Audit Officer | *Approve* a reviewed run |
| `cfo` | Chief Finance Officer | disburse, bank file, statutory returns, payslip emails |

The pay-run workflow is a **four-officer chain** — Head of Human Capital prepares →
Chief People Officer reviews → Chief Audit Officer approves → Chief Finance Officer
disburses. Each step must be a different person; the system rejects a self-review,
self-approval or self-disbursement.

## How a monthly cycle runs

1. **HR** keeps the employee master current (admin ▸ Employees). Staff ID and
   Position are mandatory; bank account numbers are format-checked on save.
2. **Head of Human Capital** creates a pay run (*Pay runs ▸ New*) — pick Expense Allowance or
   Salary, the **business unit** (or *Every business unit* to bulk-create one run
   per unit, or *All business units* for a group run), and the period. The report
   title is derived from the pay date and carries the unit name.
3. **Calculate** builds one line per active employee from the master + the
   statutory engine. PAYE/NSSF are computed on the versioned table effective on
   the pay date; the band used is shown on every line. Recalculation is
   idempotent.
4. The run detail page shows totals **grouped by business unit** with a grand
   total, and flags any line where `gross ≠ net + statutory + deductions`.
5. **Chief People Officer** (not the preparer) marks the run *Reviewed* (blocked
   while any variance exists).
6. **Chief Audit Officer** (not the reviewer) *Approves* it — timestamped.
7. **Chief Finance Officer** (not the approver) takes it from here. **Bank file**:
   one-click CSV, whole group or one business unit. Records with a missing/invalid
   account are listed and block the download until fixed.
8. **Mark disbursed** — this is the single point where loan balances (Hire
   Purchase, Fuel/Advance) are decremented; a loan stops itself at zero.
9. **Payslips** — per line as print-ready HTML or PDF; bulk PDF for the whole
   run or one business unit; or emailed to the employee with the PDF attached
   (dev uses the console email backend).
10. **Statutory returns** — from a calculated Salary run, download a **PAYE
    return CSV** (TIN, gross, chargeable income, PAYE, band) and an **NSSF return
    CSV** (NSSF number, gross, 5% / 10% / 15%).

## Reporting

*Reports* in the top nav:

- **Group monthly totals** for a chosen year — headcount, gross, PAYE, NSSF 5%/10%,
  net, for both run types, month by month, with a net-pay bar per month and a
  salary-cost-by-business-unit table.
- **Employee year-to-date** — gross / PAYE / NSSF / deductions / net aggregated
  across the year's Salary runs, filterable; each employee also has a per-employee
  YTD page (linked from the employee record) listing every pay line for the year.

## Statutory tables

*Statutory* in the top nav shows the active and draft PAYE bands and NSSF rates
and has a quick PAYE/NSSF calculator. Rates are edited in the admin
(*Statutory ▸ PAYE tables* / *NSSF configurations*) — each change is a new
effective-dated version, and past runs keep the version they were calculated
against. A proposed FY2026/27 PAYE table is pre-loaded **inactive**; tick
*is_active* to switch the group over.

## Also included

- **In-app employee add / edit** — no Django admin needed for routine HR work.
  `+ New employee` on the list, `Edit` on the record; `Employee.clean()`
  validation is shown per field.
- **Recurring deductions & earnings from the employee page** — attach / edit /
  remove a SACCO deduction, a hire-purchase loan (with opening balance), an
  acting allowance, etc. without the admin.
- **Bulk employee update** (`/employees/bulk-update/`) and **bulk onboarding of
  new joiners** (`/employees/import/`), HR or Head of Human Capital — upload a
  CSV, see a row-by-row preview with an error report, commit only on confirm.
  Downloadable templates.
- **Edit / delete a pay run** — pay date + notes while it is still draft or
  calculated; Head of Human Capital only.
- **Prior-period comparison** on every pay run — gross / PAYE / net deltas and
  joiners/leavers vs the previous same-type run.
- **Email all payslips** for a run in one click (skips anyone with no address).
- **Workflow e-mail notifications** — calculate → Chief People Officer, review →
  Chief Audit Officer, approve → Chief Finance Officer, disburse → Head of Human
  Capital + Chief Finance Officer (console backend in dev; set `PAYROLL_NOTIFY=0`
  to silence).
- **Audit trail** (`/audit/`, Chief Audit Officer only) — every create /
  change / delete across employees, pay runs, recurring deductions & earnings,
  business units and statutory tables, merged into one timeline with the
  acting user and a field-by-field diff. Filterable by record type, action,
  actor and date. Backed by `django-simple-history`, which every tracked model
  already writes to; nothing new to maintain, just a readable view over it.

## Tests

```bash
.venv/bin/python manage.py test apps
```

73 tests. PAYE band maths (each band + the 40% surcharge), the NSSF split,
line balancing, idempotent recalculation, leaver exclusion, the four-officer
approval chain (each step gated to its officer, reviewer ≠ preparer, approver ≠
reviewer, disburser ≠ approver, bank file CFO-only), once-only loan decrement,
bank-file validation, payslip PDF generation + single/bulk email, PAYE/NSSF
return contents, the report views, prior-period comparison, workflow
notifications, the CSV bulk-update + bulk-onboard parsers, the in-app employee
add/edit and recurring-component views, pay-run edit/delete, and the audit
trail (role gating + content).

## Project layout

```
config/                 settings, urls
apps/core/              dashboard, role helpers, management commands
apps/organization/      BusinessUnit, Department
apps/employees/         Employee master record + validation
apps/statutory/         PayeTable/PayeBand/NssfConfig + engine.py
apps/payroll/           codes, per-employee components, PayRun/PayRunLine,
                        services.py (calculation + workflow), banking.py,
                        payslips.py (PDF + email), statutory_exports.py
apps/reports/           month-over-month, cost-by-entity, employee year-to-date
```

## Remaining polish (Phase 4 tail)

Charts beyond the single net-pay bar; report exports to a specific URA/NSSF
portal template (the CSVs are structured for import, not a fixed portal layout);
scheduled or emailed report runs.
