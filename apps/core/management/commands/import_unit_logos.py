"""Attach business-unit logos from a folder of image files.

Drop the logo files somewhere (e.g. media/incoming-logos/) and run:

    manage.py import_unit_logos media/incoming-logos

Each file is matched to a business unit by a normalised comparison of the file
name against the unit's name and code, e.g. ``nbs-sport.png`` -> "NBS Sport",
``NextRadio.jpg`` -> "Next Radio". Unmatched files are listed and skipped.
"""

import re
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from apps.organization.models import BusinessUnit

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


class Command(BaseCommand):
    help = "Attach business-unit logos from a folder of image files."

    def add_arguments(self, parser):
        parser.add_argument("folder")
        parser.add_argument("--overwrite", action="store_true", help="Replace logos that are already set.")

    def handle(self, *args, **opts):
        folder = Path(opts["folder"])
        if not folder.is_dir():
            raise CommandError(f"Not a folder: {folder}")

        units = list(BusinessUnit.objects.all())
        by_key = {}
        for u in units:
            by_key[_norm(u.name)] = u
            by_key[_norm(u.code)] = u

        matched = skipped = 0
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in IMG_EXT or not path.is_file():
                continue
            key = _norm(path.stem)
            unit = by_key.get(key)
            if unit is None:
                # loose contains-match as a fallback
                unit = next(
                    (u for u in units if _norm(u.name) in key or key in _norm(u.name)), None
                )
            if unit is None:
                self.stdout.write(self.style.WARNING(f"  no unit matches {path.name} - skipped"))
                skipped += 1
                continue
            if unit.logo and not opts["overwrite"]:
                self.stdout.write(f"  {unit.name}: already has a logo (use --overwrite)")
                continue
            with path.open("rb") as fh:
                unit.logo.save(f"{unit.code.lower()}{path.suffix.lower()}", File(fh), save=True)
            self.stdout.write(self.style.SUCCESS(f"  {unit.name} <- {path.name}"))
            matched += 1

        self.stdout.write(self.style.SUCCESS(f"Done: {matched} attached, {skipped} unmatched."))
