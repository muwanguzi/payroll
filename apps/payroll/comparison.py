"""Prior-period comparison for a pay run (Recommendation 6.10 - trend view)."""

from __future__ import annotations

from decimal import Decimal

ZERO = Decimal("0")


def _d(v):
    return v if v is not None else ZERO


def compare_runs(current, previous):
    """Return headline deltas + joiners/leavers between two pay runs."""
    if previous is None:
        return None

    cur_ids = {
        (sid, name)
        for sid, name in current.lines.values_list("staff_id", "employee_name")
    }
    prev_ids = {
        (sid, name)
        for sid, name in previous.lines.values_list("staff_id", "employee_name")
    }
    cur_sids = {s for s, _ in cur_ids}
    prev_sids = {s for s, _ in prev_ids}

    joiners = sorted(n for s, n in cur_ids if s not in prev_sids)
    leavers = sorted(n for s, n in prev_ids if s not in cur_sids)

    c, p = current.totals(), previous.totals()

    def delta(key):
        return _d(c.get(key)) - _d(p.get(key))

    headline = {
        "previous": previous,
        "headcount": (c.get("headcount") or 0) - (p.get("headcount") or 0),
        "gross": delta("gross"),
        "paye": delta("paye"),
        "nssf_employee": delta("nssf_employee"),
        "net": delta("net"),
        "gross_now": _d(c.get("gross")),
        "gross_prev": _d(p.get("gross")),
        "net_now": _d(c.get("net")),
        "net_prev": _d(p.get("net")),
        "joiners": joiners,
        "leavers": leavers,
        "joiner_count": len(joiners),
        "leaver_count": len(leavers),
    }

    # per business-unit net delta
    cur_by_unit = {r["business_unit_name"]: r for r in current.unit_totals()}
    prev_by_unit = {r["business_unit_name"]: r for r in previous.unit_totals()}
    units = []
    for name in sorted(set(cur_by_unit) | set(prev_by_unit)):
        cu, pu = cur_by_unit.get(name, {}), prev_by_unit.get(name, {})
        units.append(
            {
                "name": name,
                "net_now": _d(cu.get("net")),
                "net_prev": _d(pu.get("net")),
                "net_delta": _d(cu.get("net")) - _d(pu.get("net")),
                "head_now": cu.get("headcount") or 0,
                "head_prev": pu.get("headcount") or 0,
            }
        )
    headline["units"] = units
    return headline
