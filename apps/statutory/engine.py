"""Statutory calculation engine (Recommendation 6.4).

Pure functions over the versioned :class:`PayeTable` / :class:`NssfConfig`
records. The pay-run calculation calls these; nothing is typed in by hand.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ImproperlyConfigured

from .models import NssfConfig, PayeTable, Residency

TWO_DP = Decimal("0.01")


@dataclass(frozen=True)
class PayeResult:
    amount: Decimal
    band_label: str
    table_name: str


@dataclass(frozen=True)
class NssfResult:
    employee: Decimal
    employer: Decimal
    config_name: str


@dataclass(frozen=True)
class ReverseGrossResult:
    """Result of solving for the gross that lands on a target net pay.

    Solved for the simple, common case this tool is meant for: a basic
    monthly salary with no additional taxable/NSSF-subject earnings, so the
    PAYE and NSSF employee-rate bases are both exactly ``gross``. If an
    employee has additional taxable earnings attached, those are not
    accounted for here - the caller should note that in the UI.
    """

    gross: Decimal
    paye: Decimal
    nssf_employee: Decimal
    nssf_employer: Decimal
    band_label: str
    net_of_statutory_and_deductions: Decimal
    fixed_deductions: Decimal


def get_paye_table(on_date, residency=Residency.RESIDENT):
    table = (
        PayeTable.objects.filter(
            residency=residency, is_active=True, effective_from__lte=on_date
        )
        .order_by("-effective_from")
        .first()
    )
    if table is None:
        raise ImproperlyConfigured(
            f"No active {residency} PAYE table effective on or before {on_date}. "
            "Load one under Statutory > PAYE tables (or run `manage.py seed_reference`)."
        )
    return table


def get_nssf_config(on_date):
    cfg = (
        NssfConfig.objects.filter(is_active=True, effective_from__lte=on_date)
        .order_by("-effective_from")
        .first()
    )
    if cfg is None:
        raise ImproperlyConfigured(
            f"No active NSSF configuration effective on or before {on_date}."
        )
    return cfg


def compute_paye(chargeable_income, on_date, residency=Residency.RESIDENT, table=None):
    table = table or get_paye_table(on_date, residency)
    amount, band_label = table.tax_for(chargeable_income)
    return PayeResult(amount=amount, band_label=band_label, table_name=table.name)


def compute_nssf(gross_pay, on_date, config=None):
    config = config or get_nssf_config(on_date)
    employee, employer = config.contributions_for(gross_pay)
    return NssfResult(employee=employee, employer=employer, config_name=config.name)


def reverse_gross_from_net(net_target, on_date, fixed_deductions=Decimal("0"), residency=Residency.RESIDENT):
    """Solve for the gross (basic monthly salary) that produces ``net_target``
    after PAYE, NSSF employee (5%) and a flat amount of other deductions.

    Uganda PAYE is piecewise-linear per band: ``tax = cumulative_base +
    (gross - lower_bound) * rate``. NSSF employee is a flat rate on gross.
    So within one band:

        net = gross - [cumulative_base + (gross - lower_bound) * rate]
                     - gross * nssf_rate - fixed_deductions

    Solving for gross:

        gross = (net + fixed_deductions + cumulative_base - lower_bound * rate)
                / (1 - rate - nssf_rate)

    Each band is tried in ascending order (rates are monotonic) and the first
    candidate that actually falls inside that band's own range - matching the
    exact boundary rule :meth:`PayeTable.tax_for` uses - is the answer, so the
    result round-trips through ``compute_paye``/``compute_nssf`` exactly.
    """
    net_target = Decimal(net_target)
    fixed_deductions = Decimal(fixed_deductions or 0)
    table = get_paye_table(on_date, residency)
    nssf_config = get_nssf_config(on_date)
    nssf_rate = nssf_config.employee_rate

    bands = list(table.bands.order_by("sequence", "lower_bound"))
    if not bands:
        raise ImproperlyConfigured(f"{table.name} has no PAYE bands configured.")

    for band in bands:
        denom = Decimal("1") - band.marginal_rate - nssf_rate
        if denom <= 0:
            continue
        candidate = (
            net_target + fixed_deductions + band.cumulative_base - band.lower_bound * band.marginal_rate
        ) / denom
        candidate = candidate.quantize(TWO_DP, rounding=ROUND_HALF_UP)
        # Same boundary rule as PayeTable.tax_for: lower < income <= upper.
        if candidate <= band.lower_bound:
            continue
        if band.upper_bound is not None and candidate > band.upper_bound:
            continue

        paye = compute_paye(candidate, on_date, residency, table=table)
        nssf = compute_nssf(candidate, on_date, config=nssf_config)
        net_of_statutory_and_deductions = (
            candidate - paye.amount - nssf.employee - fixed_deductions
        ).quantize(TWO_DP)
        return ReverseGrossResult(
            gross=candidate,
            paye=paye.amount,
            nssf_employee=nssf.employee,
            nssf_employer=nssf.employer,
            band_label=paye.band_label,
            net_of_statutory_and_deductions=net_of_statutory_and_deductions,
            fixed_deductions=fixed_deductions,
        )

    raise ValueError(
        "Could not solve a gross for that net pay against the current PAYE table - "
        "the target net may be unreachable (e.g. negative or absurdly high)."
    )
