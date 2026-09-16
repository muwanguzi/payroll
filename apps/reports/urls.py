from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.report_index, name="index"),
    path("ytd/", views.employee_ytd, name="employee_ytd"),
    path("ytd/<int:pk>/", views.employee_ytd_detail, name="employee_ytd_detail"),
]
