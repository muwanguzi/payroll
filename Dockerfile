# Next Media Payroll - production image.
#
# lxml / Pillow / reportlab all resolve to prebuilt manylinux wheels for
# this Python version (verified against the dev .venv), so no compiler
# toolchain is needed here - keeps the image small and the build fast.

FROM python:3.14.4-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Fonts for the payslip PDF (xhtml2pdf/reportlab) and payslip logos ship in
# the repo itself (static/fonts, static/img) - nothing extra needed at the
# OS level for rendering.

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# nextjs-ui-kit/, deploy/, .git/ etc. never make it into the build context -
# see .dockerignore.

# Fixed UID/GID (not just --system, which picks an arbitrary one) so the
# host directories bind-mounted in for /app/data, /app/media, /app/staticfiles
# (see docker-compose.yml) can be chowned to match ahead of time - otherwise
# Docker creates them as root:root and the app can't write to them.
RUN groupadd --gid 1000 payroll \
    && useradd --uid 1000 --gid payroll --home /app --shell /usr/sbin/nologin payroll \
    && mkdir -p /app/media /app/staticfiles /app/data \
    && chown -R payroll:payroll /app

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER payroll

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", \
     "--access-logfile", "-", "--error-logfile", "-"]
