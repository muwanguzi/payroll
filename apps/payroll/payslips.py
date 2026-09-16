"""Payslip PDF rendering and emailing (Recommendation 6.10, Phase 3).

A payslip is one document per employee per month, combining the Salary run
line and the Expense Allowance run line for that period into a single view -
not two separate documents. It is only available once the Salary run for
that period has been marked Disbursed (see ``PayslipBundle.ready``); before
that, nothing is generated, downloadable or emailed for it.
"""

import base64
import io
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from xhtml2pdf import pisa

from .models import PayRunLine, RunStatus, RunType

ZERO = Decimal("0.00")


def _file_data_uri(path, mime="image/png") -> str:
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except OSError:  # pragma: no cover - file missing
        return ""


@lru_cache(maxsize=1)
def _logo_data_uri() -> str:
    """The Next Media group logo as a base64 data URI (xhtml2pdf needs no path lookup)."""
    return _file_data_uri(settings.BASE_DIR / "static" / "img" / "next-media-logo.png")


def _unit_logo_data_uris(codes):
    """{business_unit_code: data URI} for units that have a logo uploaded."""
    from apps.organization.models import BusinessUnit

    out = {}
    for bu in BusinessUnit.objects.filter(code__in=set(codes)).exclude(logo=""):
        if bu.logo:
            mime = "image/jpeg" if bu.logo.name.lower().endswith((".jpg", ".jpeg")) else "image/png"
            out[bu.code] = _file_data_uri(Path(bu.logo.path), mime)
    return out


# ---------------------------------------------------------------------------
# The merged payslip: one bundle per employee per period, combining the
# Salary and Expense Allowance lines (either may be absent).
# ---------------------------------------------------------------------------
@dataclass
class PayslipBundle:
    employee_id: int
    period_year: int
    period_month: int
    salary_line: PayRunLine | None
    expense_line: PayRunLine | None

    @property
    def anchor(self) -> PayRunLine:
        """A representative line for identity fields (name, staff ID, unit, ...).
        Prefers the Salary line since it is the authoritative one for the payslip."""
        return self.salary_line or self.expense_line

    @property
    def ready(self) -> bool:
        """Gate on disbursement (Item 2): a payslip is only visible/downloadable
        once the Salary run for this period is actually Disbursed - never merely
        because it was generated, calculated or approved. If there is no Salary
        line yet for the period at all, it is not ready either."""
        return self.salary_line is not None and self.salary_line.pay_run.status == RunStatus.DISBURSED

    @property
    def net_pay(self) -> Decimal:
        total = ZERO
        if self.salary_line:
            total += self.salary_line.net_pay
        if self.expense_line:
            total += self.expense_line.net_pay
        return total

    @property
    def email(self) -> str:
        return (self.salary_line and self.salary_line.email) or (self.expense_line and self.expense_line.email) or ""

    @property
    def period_label(self) -> str:
        return self.anchor.pay_run.period_label if self.anchor else ""


def get_payslip_bundle(line: PayRunLine) -> PayslipBundle:
    """Resolve the merged bundle for whichever line (salary or expense) is at hand.

    Matches by employee + calendar period (year/month), not by business unit,
    since the two run types are independent PayRuns. Assumption: if more than
    one run of the sibling type exists for that employee+period (not supposed
    to happen operationally, but not database-enforced across scopes), the
    most recently created one is used.
    """
    run = line.pay_run
    other_type = RunType.EXPENSE_ALLOWANCE if run.run_type == RunType.SALARY else RunType.SALARY
    sibling = (
        PayRunLine.objects.filter(
            employee_id=line.employee_id,
            pay_run__run_type=other_type,
            pay_run__period_year=run.period_year,
            pay_run__period_month=run.period_month,
        )
        .select_related("pay_run")
        .prefetch_related("items")
        .order_by("-pay_run__created_at")
        .first()
    )
    if run.run_type == RunType.SALARY:
        return PayslipBundle(line.employee_id, run.period_year, run.period_month, line, sibling)
    return PayslipBundle(line.employee_id, run.period_year, run.period_month, sibling, line)


def payslip_bundles_for_run(run) -> list[PayslipBundle]:
    """Every employee bundle anchored at a Salary run - the payslip's natural
    anchor now that it is gated on the Salary run being disbursed. Returns
    nothing for an Expense Allowance run; see ``run_detail.html``."""
    if run.run_type != RunType.SALARY:
        return []
    lines = run.lines.select_related("pay_run").prefetch_related("items").order_by(
        "business_unit_name", "employee_name"
    )
    return [get_payslip_bundle(line) for line in lines]


def render_payslip_pdf(bundles: list[PayslipBundle] | PayslipBundle) -> bytes:
    """Render one or many payslip bundles into a single PDF (one page each)."""
    bundle_list = [bundles] if isinstance(bundles, PayslipBundle) else list(bundles)
    codes = [b.anchor.business_unit_code for b in bundle_list if b.anchor]
    html = render_to_string(
        "payroll/payslip_pdf.html",
        {
            "bundles": bundle_list,
            "logo": _logo_data_uri(),
            "unit_logos": _unit_logo_data_uris(codes),
        },
    )
    buf = io.BytesIO()
    result = pisa.CreatePDF(src=html, dest=buf, encoding="utf-8")
    if result.err:
        raise RuntimeError("Payslip PDF generation failed.")
    return buf.getvalue()


def email_payslip(bundle: PayslipBundle, from_email=None) -> str:
    if not bundle.ready:
        raise ValueError("This payslip is not available yet - the Salary run has not been disbursed.")
    if not bundle.email:
        raise ValueError(f"{bundle.anchor.staff_id} {bundle.anchor.employee_name} has no email address on file.")
    pdf = render_payslip_pdf(bundle)
    subject = f"Payslip - {bundle.period_label}"
    body = (
        f"Dear {bundle.anchor.employee_name},\n\n"
        f"Please find attached your payslip for {bundle.period_label}.\n\n"
        f"Net pay: {bundle.net_pay:,.0f} UGX\n\n"
        "Next Media Finance"
    )
    msg = EmailMessage(subject, body, from_email, [bundle.email])
    fname = f"payslip-{bundle.anchor.staff_id}-{bundle.period_year}-{bundle.period_month:02d}.pdf"
    msg.attach(fname, pdf, "application/pdf")
    msg.send()
    return bundle.email


@dataclass
class BulkEmailResult:
    sent: int = 0
    skipped: list = field(default_factory=list)  # (staff_id, name, reason)
    failed: list = field(default_factory=list)   # (staff_id, name, error)

    @property
    def total(self):
        return self.sent + len(self.skipped) + len(self.failed)


def email_run_payslips(pay_run, business_unit_code: str | None = None) -> BulkEmailResult:
    """Email a merged payslip PDF to every payable employee in a disbursed
    Salary run who has an address on file."""
    bundles = payslip_bundles_for_run(pay_run)
    if business_unit_code:
        bundles = [b for b in bundles if b.anchor and b.anchor.business_unit_code == business_unit_code]

    res = BulkEmailResult()
    for bundle in bundles:
        anchor = bundle.anchor
        if not bundle.ready:
            res.skipped.append((anchor.staff_id, anchor.employee_name, "salary run not yet disbursed"))
            continue
        if not bundle.email:
            res.skipped.append((anchor.staff_id, anchor.employee_name, "no email on file"))
            continue
        if bundle.net_pay <= 0:
            res.skipped.append((anchor.staff_id, anchor.employee_name, f"net pay {bundle.net_pay}"))
            continue
        try:
            email_payslip(bundle)
            res.sent += 1
        except Exception as exc:  # pragma: no cover - defensive
            res.failed.append((anchor.staff_id, anchor.employee_name, str(exc)))
    return res
