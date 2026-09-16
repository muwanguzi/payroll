# Research notes — statutory rules & payroll design

Compiled for the Next Media Payroll System build (Phase 1 + 2). These are the
external facts the calculation engine encodes. Everything here is configurable
and versioned in the app (Statutory ▸ PAYE tables / NSSF configurations); the
values below are what `manage.py seed_reference` loads as the active version.

## 1. Uganda PAYE — monthly, resident individuals

Source: **Uganda Revenue Authority, "PAYE rates"** — <https://ura.go.ug/en/domestic-taxes/paye-rates/>
(checked 31 Aug 2026). Cross-checked against third-party 2026 PAYE guides.

| Monthly chargeable income (UGX) | Tax |
|---|---|
| 0 – 235,000 | Nil |
| 235,001 – 335,000 | 10% of the amount over 235,000 |
| 335,001 – 410,000 | 20% of the amount over 335,000 **+ 10,000** |
| 410,001 – 10,000,000 | 30% of the amount over 410,000 **+ 25,000** |
| Above 10,000,000 | [30% of the amount over 410,000 + 25,000] **+ 10% of the amount over 10,000,000** |

The extra 10% above UGX 10,000,000 is a surcharge that lifts the effective top
marginal rate to **40%**. The engine models it as a final open-ended band with
`marginal_rate = 0.40` and `cumulative_base = 2,902,000` (the tax due at exactly
10,000,000: `25,000 + (10,000,000 − 410,000) × 30%`).

**How the engine stores a band:** `tax = cumulative_base + (income − lower_bound) × marginal_rate`,
where `cumulative_base` is the tax already accrued on all income up to the
band's lower bound. This keeps each row a simple lookup and makes a rate change
a data edit, not code.

### Proposed 2026/27 thresholds (loaded INACTIVE)

The Ministry of Finance proposed raising the tax-free monthly threshold from
UGX 235,000 to **UGX 335,000** (annual free amount 2,820,000 → 4,020,000) for FY
2026/27. As of the build date this was awaiting assent, so `seed_reference`
loads it as a **second, inactive** `PayeTable` (effective 1 Jul 2026). When it is
confirmed, tick *is_active* on that version in the admin — no code change, and
historical runs keep the table they were calculated against.

> The exact band structure above 335,000 in the inactive table is a
> reasonable reconstruction for demonstration; confirm against the assented
> Income Tax (Amendment) Act before activating.

## 2. NSSF contributions

Source: **NSSF Act 2022** and NSSF Uganda guidance (multiple 2026 references).

- **Employee:** 5% of gross — deducted from pay.
- **Employer:** 10% of gross — an employer cost, **not** a deduction from net.
- Total remitted: 15% of gross.
- Mandatory for all employers since the 2022 Act (previously only employers of
  5+ staff).
- PAYE in Uganda is charged on gross pay; the employee NSSF contribution is
  **not** deductible before PAYE. The engine therefore computes PAYE on
  chargeable earnings and NSSF separately on the NSSF-subject gross.

Stored as `NssfConfig(effective_from, employee_rate, employer_rate)` — effective-dated
like the PAYE tables.

## 3. What the legacy workbook told us (Template_Payroll.xlsx)

Structural facts carried into the data model:

- **Four sheets** — `Exp`, `Salary`, `Bank Exp Allowance`, `Bank Salary`.
- **Two monthly cycles** — Expense Allowance (~15th) and Salary (~27th) — against
  largely the same people. → `PayRun.run_type` with two values.
- **Deduction families:**
  - Exp: SACCO, Food, Medicare, Hire Purchase, Cost Share, ID Replacement, Fuel/Advance
  - Salary: SACCO, Food, Medicare, Hire Purchase, Cost Share, ID Replacement, Penalty
  → `DeductionCode` with `applies_to_expense` / `applies_to_salary` flags; Fuel/Advance
    and Hire Purchase flagged `is_loan` (carry a running balance).
- **Statutory columns on the Salary sheet contain no formulas** — every PAYE / NSSF
  figure is hand-keyed. → the whole reason for the engine in §1–2.
- **Name-spelling drift between sheets** — confirmed in the template itself:
  `Abdallah Gulemye` (Exp) vs `Abdallar Gulemye` (Salary); `Adrian Bakuwama` vs
  `Adrian Bakuwamma`. → one `Employee` master record; matching by `staff_id`, never by name.
- **Hard-coded total formulas** — grand totals sum ~10 specific cell references.
  → totals computed by `GROUP BY business_unit`, never by row position.
- **Bank sheets** pull each amount by formula from the pay sheet, and Bank Salary
  has a per-unit reconciliation block (with a sign-convention inconsistency on the
  last three units). → one-click bank file generated from the approved run, with
  per-record account validation.
- The supplied template is **de-identified**: unit blocks flattened into one
  alphabetical list, pay figures zeroed. `import_template` therefore loads the
  distinct people and spreads them across business units round-robin as demo data.

## 4. Environment note

The build host had no `pip`/`ensurepip`. Pip was bootstrapped into a local
`.venv` via `get-pip.py`; Django 6.1, django-simple-history and xhtml2pdf (for
payslip PDFs) run fine on the host's Python 3.14. See `README.md` for setup.
