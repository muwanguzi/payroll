from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .engine import compute_paye
from .models import NssfConfig, PayeTable


@login_required
def statutory_overview(request):
    tables = PayeTable.objects.prefetch_related("bands")

    preview = None
    gross_raw = request.GET.get("gross", "").replace(",", "").strip()
    if gross_raw:
        try:
            gross = Decimal(gross_raw)
            table = tables.filter(is_active=True).order_by("-effective_from").first()
            result = compute_paye(gross, table.effective_from, table=table)
            nssf = NssfConfig.objects.filter(is_active=True).order_by("-effective_from").first()
            ee = (gross * nssf.employee_rate).quantize(Decimal("0.01"))
            er = (gross * nssf.employer_rate).quantize(Decimal("0.01"))
            preview = {
                "gross": gross,
                "paye": result.amount,
                "band": result.band_label,
                "table": result.table_name,
                "nssf_employee": ee,
                "nssf_employer": er,
                "net_of_statutory": gross - result.amount - ee,
            }
        except (InvalidOperation, AttributeError):
            preview = {"error": "Enter a valid gross amount."}

    context = {
        "tables": tables,
        "nssf_configs": NssfConfig.objects.all(),
        "preview": preview,
        "gross_raw": gross_raw,
    }
    template = "statutory/_preview.html" if request.headers.get("HX-Request") else "statutory/overview.html"
    return render(request, template, context)
