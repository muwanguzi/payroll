"""
Django settings for the Next Media Payroll System.

Covers Phase 1 (employee master + digitised structure) and Phase 2
(automated PAYE/NSSF engine + live validation) of the system review.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-=2bk+7ffix2e$xyt(=*@q8im%@b2iprl4s1=t%70z8&^w35m!u",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
if DEBUG and "testserver" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("testserver")
# Always allowed regardless of DJANGO_ALLOWED_HOSTS: only reachable from
# inside the same container/host, used by the Docker healthcheck
# (docker-compose.yml hits http://127.0.0.1:8000/login/ directly, bypassing
# whatever public hostname is configured).
if "127.0.0.1" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("127.0.0.1")

CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

# Behind nginx terminating TLS (deploy/provision.sh): trust its
# X-Forwarded-Proto header, and only mark cookies secure once DEBUG is off -
# otherwise a plain-HTTP dev/staging run would silently drop every cookie.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

INSTALLED_APPS = [
    # Unfold admin theme - must precede django.contrib.admin
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.simple_history",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "simple_history",
    # local
    "apps.core",
    "apps.organization",
    "apps.employees",
    "apps.statutory",
    "apps.payroll",
    "apps.reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # captures request.user for the audit trail (simple_history)
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.roles",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        # Overridable so the Docker image can point this at a mounted
        # volume (e.g. /app/data/db.sqlite3) without changing plain
        # (non-Docker) local/dev behaviour, which keeps using BASE_DIR.
        "NAME": os.environ.get("DJANGO_DB_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Kampala"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Defaults to printing emails to the console/log (dev, and any deploy that
# hasn't set SMTP details yet - payslip "sending" then just logs instead of
# failing). Set DJANGO_EMAIL_HOST (+ PORT/USER/PASSWORD/USE_TLS/DEFAULT_FROM)
# to switch to real SMTP.
if os.environ.get("DJANGO_EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ["DJANGO_EMAIL_HOST"]
    EMAIL_PORT = int(os.environ.get("DJANGO_EMAIL_PORT", 587))
    EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = os.environ.get("DJANGO_EMAIL_USE_TLS", "1") == "1"
    DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# ---------------------------------------------------------------------------
# Payroll-specific configuration
# ---------------------------------------------------------------------------

# Bank account number validation (Recommendation 6.7 - extend the partial
# length check on the current Salary sheet to every record, at data entry).
PAYROLL_BANK_ACCT_MIN_LEN = int(os.environ.get("PAYROLL_BANK_ACCT_MIN_LEN", 8))
PAYROLL_BANK_ACCT_MAX_LEN = int(os.environ.get("PAYROLL_BANK_ACCT_MAX_LEN", 20))

# Currency used across the group workbook.
PAYROLL_CURRENCY = "UGX"

# Workflow e-mail notifications (Recommendation 6.9).
PAYROLL_NOTIFY = os.environ.get("PAYROLL_NOTIFY", "1") == "1"
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "http://127.0.0.1:8000")

# Role group names (Recommendation 6.8 - role-based access).
# The pay-run workflow is a four-officer chain of separation of duties:
#   Head of Human Capital  - drafts + calculates the run
#   Chief People Officer    - reviews it
#   Chief Audit Officer     - approves it
#   Chief Finance Officer   - disburses it (and owns the bank file / returns)
ROLE_HR = "HR Data Entry"
ROLE_HHC = "Head of Human Capital"
ROLE_CPO = "Chief People Officer"
ROLE_CAO = "Chief Audit Officer"
ROLE_CFO = "Chief Finance Officer"
PAYROLL_ROLES = [ROLE_HR, ROLE_HHC, ROLE_CPO, ROLE_CAO, ROLE_CFO]

# Semantic bundles used by the views (a role can be granted to several people).
ROLES_PREPARE = [ROLE_HHC]                 # create / calculate / edit / delete a run
ROLES_REVIEW = [ROLE_CPO]                  # mark reviewed
ROLES_APPROVE = [ROLE_CAO]                 # approve
ROLES_DISBURSE = [ROLE_CFO]               # mark disbursed, bank file, statutory returns, payslip email
ROLES_REOPEN = [ROLE_HHC, ROLE_CPO, ROLE_CAO, ROLE_CFO]
ROLES_EMPLOYEE_EDIT = [ROLE_HR, ROLE_HHC]  # employee master, deductions, bulk CSV
ROLES_AUDIT = [ROLE_CAO]                   # read the cross-system audit trail
ROLES_DEDUCTION_APPROVE = [ROLE_CAO]       # approve/reject per-deduction-type entries

# ---------------------------------------------------------------------------
# Unfold admin theme
# ---------------------------------------------------------------------------
from django.templatetags.static import static  # noqa: E402
from django.urls import reverse_lazy  # noqa: E402

UNFOLD = {
    "SITE_TITLE": "Next Media Payroll",
    "SITE_HEADER": "Next Media Payroll",
    "SITE_SUBHEADER": "Administration",
    "SITE_SYMBOL": "payments",
    "SITE_LOGO": lambda request: static("img/next-media-logo.png"),
    "SITE_ICON": lambda request: static("img/next-media-logo.png"),
    "SITE_URL": "/",
    "STYLES": [lambda request: static("css/admin-brand.css")],
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "SHOW_BACK_BUTTON": True,
    "ENVIRONMENT": "apps.core.admin_dashboard.environment_callback",
    "DASHBOARD_CALLBACK": "apps.core.admin_dashboard.dashboard_callback",
    "BORDER_RADIUS": "8px",
    "COLORS": {
        "base": {
            "50": "248 250 252", "100": "241 245 249", "200": "226 232 240",
            "300": "203 213 225", "400": "148 163 184", "500": "100 116 139",
            "600": "71 85 105", "700": "51 65 85", "800": "30 41 59",
            "900": "15 23 42", "950": "2 6 23",
        },
        # Next Media teal (accent #0E7F8B, dark #0B2E38)
        "primary": {
            "50": "228 243 244", "100": "200 231 233", "200": "154 213 217",
            "300": "99 191 198", "400": "51 167 177", "500": "26 143 153",
            "600": "14 127 139", "700": "12 102 112", "800": "11 82 91",
            "900": "11 46 56", "950": "7 30 37",
        },
        "font": {
            "subtle-light": "var(--color-base-500)",
            "subtle-dark": "var(--color-base-400)",
            "default-light": "var(--color-base-600)",
            "default-dark": "var(--color-base-300)",
            "important-light": "var(--color-base-900)",
            "important-dark": "var(--color-base-100)",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Payroll app",
                "separator": True,
                "items": [
                    {"title": "Open payroll app", "icon": "open_in_new", "link": "/"},
                    {"title": "Pay runs", "icon": "receipt_long", "link": "/payroll/runs/", "badge": "apps.core.admin_dashboard.open_runs_badge"},
                    {"title": "Reports", "icon": "monitoring", "link": "/reports/"},
                    {"title": "Documents", "icon": "menu_book", "link": "/documents/"},
                    {"title": "Audit trail", "icon": "gavel", "link": "/audit/"},
                ],
            },
            {
                "title": "People",
                "separator": True,
                "items": [
                    {"title": "Employees", "icon": "badge", "link": reverse_lazy("admin:employees_employee_changelist")},
                    {"title": "Business units", "icon": "apartment", "link": reverse_lazy("admin:organization_businessunit_changelist")},
                    {"title": "Departments", "icon": "workspaces", "link": reverse_lazy("admin:organization_department_changelist")},
                ],
            },
            {
                "title": "Pay elements",
                "separator": True,
                "items": [
                    {"title": "Earning codes", "icon": "add_card", "link": reverse_lazy("admin:payroll_earningcode_changelist")},
                    {"title": "Deduction codes", "icon": "credit_card_off", "link": reverse_lazy("admin:payroll_deductioncode_changelist")},
                    {"title": "Employee deductions", "icon": "money_off", "link": reverse_lazy("admin:payroll_employeededuction_changelist")},
                    {"title": "Employee earnings", "icon": "attach_money", "link": reverse_lazy("admin:payroll_employeeearning_changelist")},
                ],
            },
            {
                "title": "Statutory",
                "separator": True,
                "items": [
                    {"title": "PAYE tables", "icon": "table_chart", "link": reverse_lazy("admin:statutory_payetable_changelist")},
                    {"title": "NSSF configurations", "icon": "savings", "link": reverse_lazy("admin:statutory_nssfconfig_changelist")},
                ],
            },
            {
                "title": "Pay runs & access",
                "separator": True,
                "items": [
                    {"title": "Pay runs (admin)", "icon": "payments", "link": reverse_lazy("admin:payroll_payrun_changelist")},
                    {"title": "Pay run lines", "icon": "list_alt", "link": reverse_lazy("admin:payroll_payrunline_changelist")},
                    {"title": "Users", "icon": "person", "link": reverse_lazy("admin:auth_user_changelist")},
                    {"title": "Groups / roles", "icon": "groups", "link": reverse_lazy("admin:auth_group_changelist")},
                ],
            },
        ],
    },
}
