"""Workflow e-mail notifications (Recommendation 6.9).

Best-effort: a mail failure never blocks a pay-run transition. In development
the console e-mail backend just prints the message.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.mail import send_mail
from django.urls import reverse

log = logging.getLogger(__name__)


def _recipients(*role_names):
    return list(
        Group.objects.filter(name__in=role_names)
        .values_list("user__email", flat=True)
        .distinct()
    )


def _send(subject, body, recipients):
    recipients = [r for r in recipients if r]
    if not recipients or not getattr(settings, "PAYROLL_NOTIFY", True):
        return 0
    try:
        return send_mail(subject, body, None, recipients, fail_silently=True)
    except Exception:  # pragma: no cover - defensive
        log.exception("pay-run notification failed")
        return 0


def notify_transition(pay_run, event: str, actor=None):
    """event in {'calculated', 'reviewed', 'approved', 'disbursed'}."""
    try:
        path = reverse("payroll:run_detail", args=[pay_run.pk])
    except Exception:  # pragma: no cover
        path = ""
    link = f"{settings.SITE_BASE_URL}{path}" if getattr(settings, "SITE_BASE_URL", "") else path
    who = getattr(actor, "get_username", lambda: "someone")()

    matrix = {
        "calculated": (
            (settings.ROLE_CPO,),
            f"[Payroll] {pay_run.title} is calculated and awaiting review",
            f"{who} calculated this run. {pay_run.lines.count()} lines, "
            f"{pay_run.variance_line_count} variance(s). Review it: {link}",
        ),
        "reviewed": (
            (settings.ROLE_CAO,),
            f"[Payroll] {pay_run.title} is reviewed and awaiting approval",
            f"{who} marked this run reviewed. Approve or reject it: {link}",
        ),
        "approved": (
            (settings.ROLE_CFO,),
            f"[Payroll] {pay_run.title} is approved and awaiting disbursement",
            f"{who} approved this run. Generate the bank file and disburse it: {link}",
        ),
        "disbursed": (
            (settings.ROLE_HHC, settings.ROLE_CFO),
            f"[Payroll] {pay_run.title} marked disbursed",
            f"{who} marked this run disbursed; loan balances were updated. {link}",
        ),
    }
    if event not in matrix:
        return
    roles, subject, body = matrix[event]
    _send(subject, body, _recipients(*roles))
