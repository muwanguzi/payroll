from django.urls import path

from . import views

app_name = "statutory"

urlpatterns = [
    path("", views.statutory_overview, name="overview"),
]
