import re

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path
from django.views.static import serve as serve_static

admin.site.site_header = "Next Media Payroll"
admin.site.site_title = "Next Media Payroll"
admin.site.index_title = "Payroll administration"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.core.urls")),
    path("employees/", include("apps.employees.urls")),
    path("payroll/", include("apps.payroll.urls")),
    path("statutory/", include("apps.statutory.urls")),
    path("reports/", include("apps.reports.urls")),
]

# Deliberately NOT django.conf.urls.static.static() - that helper is a
# no-op whenever DEBUG=False, which is exactly when this is needed: unlike
# static/ (served by WhiteNoise, see MIDDLEWARE), there's no separate web
# server for media in the Docker deploy (Traefik proxies straight to
# gunicorn). Media here is a handful of business-unit logos, already
# visible on public-facing payslips, so django.views.static.serve is an
# acceptable amount of "not for serious production scale" for this app's
# actual size.
urlpatterns += [
    re_path(
        r"^%s(?P<path>.*)$" % re.escape(settings.MEDIA_URL.lstrip("/")),
        serve_static,
        {"document_root": settings.MEDIA_ROOT},
    ),
]
