from django.urls import path

from . import views

app_name = "evidence"

urlpatterns = [
    path("<uuid:pk>/download/", views.document_download, name="document_download"),
]
