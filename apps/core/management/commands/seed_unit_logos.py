"""Generate a tidy placeholder wordmark logo for every business unit.

Real artwork should replace these - upload per unit in the admin
(Business units > Logo) or run ``import_unit_logos <folder>``. This command
only fills the gap so payslips carry unit branding out of the box.

    manage.py seed_unit_logos [--overwrite]
"""

import io

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw, ImageFont

from apps.organization.models import BusinessUnit

# a distinct accent per unit (falls back to Next Media teal)
PALETTE = {
    "NBS": "#e2231a", "NBSS": "#4a9fb0", "HILL": "#111111", "NCOM": "#e08a2e",
    "SANY": "#e0902e", "NRAD": "#7bbf3f", "AFRO": "#0e7f8b", "NILE": "#b04a3a",
    "SLM": "#2e7d32", "NPL": "#1b3a6b", "UM": "#19a7b5", "MC": "#d73c26",
}


def _font(size):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wordmark(text, accent):
    W, H, pad = 640, 200, 28
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=22, fill="#ffffff", outline=accent, width=4)
    d.rounded_rectangle([pad, H - 26, pad + 120, H - 14], radius=6, fill=accent)  # brand tick
    font = _font(64)
    tw = d.textbbox((0, 0), text, font=font)[2]
    if tw > W - 2 * pad:
        font = _font(int(64 * (W - 2 * pad) / tw))
    d.text((pad, H / 2 - 18), text, font=font, fill="#12201f", anchor="lm")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class Command(BaseCommand):
    help = "Generate placeholder wordmark logos for business units that have none."

    def add_arguments(self, parser):
        parser.add_argument("--overwrite", action="store_true")

    def handle(self, *args, **opts):
        made = 0
        for bu in BusinessUnit.objects.all():
            if bu.logo and not opts["overwrite"]:
                continue
            accent = PALETTE.get(bu.code, "#19a7b5")
            bu.logo.save(f"{bu.code.lower()}.png", ContentFile(_wordmark(bu.name.upper(), accent)), save=True)
            made += 1
            self.stdout.write(self.style.SUCCESS(f"  {bu.name}"))
        self.stdout.write(self.style.SUCCESS(f"{made} placeholder logo(s) generated."))
