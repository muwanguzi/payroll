"""Best-effort import of employees from the legacy Template_Payroll.xlsx.

The supplied template is de-identified: the per-business-unit blocks and TOTAL
rows have been flattened into one alphabetical list, and pay figures are zeroed.
So this importer pulls the distinct people (Staff ID / name / position) from the
Salary and Exp sheets, matches them by a normalised name, and - because the
template carries no unit mapping - spreads them across business units in a
round-robin purely so the multi-entity screens have data to show.

Run `seed_reference` first. Use `--flush` to clear existing employees.
"""

import re
import zipfile
from html import unescape
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.employees.models import Employee, EngagementType
from apps.organization.models import BusinessUnit


def _load_strings(z):
    xml = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
    out = []
    for si in re.split(r"</si>", xml):
        parts = re.findall(r"<t[^>]*>(.*?)</t>", si, re.S)
        out.append(unescape("".join(parts)) if parts else "")
    return out


def _iter_rows(z, sheet, strings):
    xml = z.read(sheet).decode("utf-8", "ignore")
    for rm in re.finditer(r'<row[^>]*r="(\d+)"[^>]*>(.*?)</row>', xml, re.S):
        cells = {}
        for cm in re.finditer(r'<c r="([A-Z]+)\d+"([^>]*)>(.*?)</c>', rm.group(2), re.S):
            col, attrs, inner = cm.group(1), cm.group(2), cm.group(3)
            tm = re.search(r't="([^"]+)"', attrs)
            vm = re.search(r"<v>(.*?)</v>", inner, re.S)
            if not vm:
                continue
            if tm and tm.group(1) == "s":
                cells[col] = strings[int(vm.group(1))].strip()
            else:
                cells[col] = unescape(vm.group(1)).strip()
        yield int(rm.group(1)), cells


def _norm(name):
    return re.sub(r"\s+", " ", name or "").strip().lower()


class Command(BaseCommand):
    help = "Import employees from the legacy Template_Payroll.xlsx workbook."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=str(Path(settings.BASE_DIR) / "Template_Payroll.xlsx"))
        parser.add_argument("--flush", action="store_true", help="Delete existing employees first.")

    @transaction.atomic
    def handle(self, *args, **opts):
        path = Path(opts["path"])
        if not path.exists():
            raise CommandError(f"Workbook not found: {path}")

        units = list(BusinessUnit.objects.order_by("sequence"))
        if not units:
            raise CommandError("No business units - run `manage.py seed_reference` first.")

        if opts["flush"]:
            deleted = Employee.objects.all().delete()[0]
            self.stdout.write(self.style.WARNING(f"Flushed {deleted} employees"))

        z = zipfile.ZipFile(path)
        strings = _load_strings(z)

        # Salary sheet (sheet2): A=ID No, B=Name, C=Position
        people = {}  # norm_name -> dict
        for rn, c in _iter_rows(z, "xl/worksheets/sheet2.xml", strings):
            if rn <= 8:
                continue
            name = c.get("B", "")
            if not name or _norm(name) in {"name", "grand total", "total"}:
                continue
            people[_norm(name)] = {
                "name": name,
                "staff_id": c.get("A", "") or "",
                "position": c.get("C", "") if c.get("C", "") not in {"0", ""} else "",
            }

        # Exp sheet (sheet1): B=Name, C=Position - fill gaps / add expense-only staff
        for rn, c in _iter_rows(z, "xl/worksheets/sheet1.xml", strings):
            if rn <= 7:
                continue
            name = c.get("B", "")
            if not name or _norm(name) in {"name", "grand total", "total"}:
                continue
            key = _norm(name)
            rec = people.setdefault(key, {"name": name, "staff_id": "", "position": ""})
            if not rec["position"] and c.get("C", "") not in {"0", ""}:
                rec["position"] = c.get("C", "")

        created = updated = skipped = 0
        seen_ids = set()
        today = timezone.now().date()
        for i, (key, rec) in enumerate(sorted(people.items())):
            staff_id = re.sub(r"\s+", "", rec["staff_id"]) or f"TMP-{i + 1:04d}"
            if staff_id in seen_ids:
                staff_id = f"{staff_id}-{i + 1}"
            seen_ids.add(staff_id)

            unit = units[i % len(units)]
            defaults = {
                "full_legal_name": rec["name"],
                "position": rec["position"] or "Unassigned",
                "business_unit": unit,
                "engagement_type": EngagementType.PAYROLL_STAFF,
                "date_joined": today.replace(year=today.year - 2),
            }
            obj, was_created = Employee.objects.update_or_create(staff_id=staff_id, defaults=defaults)
            created += was_created
            updated += not was_created

        self.stdout.write(self.style.SUCCESS(
            f"Imported {created} new / {updated} updated employees across {len(units)} units. "
            f"(Business-unit assignment is round-robin demo data - the template carries no unit mapping.)"
        ))
