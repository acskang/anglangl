from django.urls import path

from . import views

app_name = "dramaNlearn"

urlpatterns = [
    path("", views.home, name="home"),
    path("imdb/", views.imdb_browser, name="imdb"),
    path("imdb/reorder/", views.reorder_imdb_series, name="reorder_imdb_series"),
    path("imdb/<str:imdb_id>/delete/", views.delete_imdb_series, name="delete_imdb_series"),
    path("urls/", views.url_manage, name="url_manage"),
    path("add/", views.add_video, name="add_video"),
    path("player/<int:video_id>/", views.player, name="player"),
    path("player/<int:video_id>/clip-extract/", views.open_clip_extract, name="clip_extract"),
    path("title/<int:video_id>/", views.update_title, name="update_title"),
    path("thumbnail/<int:video_id>/", views.update_thumbnail, name="update_thumbnail"),
    path("refresh/<int:video_id>/", views.refresh_video, name="refresh_video"),
    path("retry/<int:video_id>/", views.retry_video, name="retry_video"),
    path("cancel/<int:video_id>/", views.cancel_video, name="cancel_video"),
    path("delete/<int:video_id>/", views.delete_video, name="delete_video"),
    path("api/video/<int:video_id>/status/", views.api_video_status, name="api_video_status"),
    path("api/static-images/", views.api_static_images, name="api_static_images"),
]
