from django.urls import path

from . import views

app_name = "thumbnail_admin"

urlpatterns = [
    path("", views.thumbnail_list, name="list"),
    path("<int:asset_id>/edit/", views.thumbnail_edit, name="edit"),
    path("<int:asset_id>/delete/", views.thumbnail_delete, name="delete"),
]
