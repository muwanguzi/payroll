from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("documents/", views.documents, name="documents"),
    path("documents/<slug:slug>/", views.document_view, name="document_view"),
    path("audit/", views.audit_trail, name="audit_trail"),
]
