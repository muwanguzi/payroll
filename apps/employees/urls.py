from django.urls import path

from . import views

app_name = "employees"

urlpatterns = [
    path("", views.employee_list, name="list"),
    path("new/", views.employee_create, name="create"),
    path("reverse-gross/", views.reverse_gross_preview, name="reverse_gross"),
    path("bulk-update/", views.bulk_update, name="bulk_update"),
    path("import/", views.bulk_import, name="bulk_import"),
    path("<int:pk>/", views.employee_detail, name="detail"),
    path("<int:pk>/edit/", views.employee_edit, name="edit"),
    path("<int:pk>/<str:kind>/new/", views.component_form, name="component_add"),
    path("<int:pk>/<str:kind>/<int:cid>/edit/", views.component_form, name="component_edit"),
    path("<int:pk>/<str:kind>/<int:cid>/delete/", views.component_delete, name="component_delete"),
]
