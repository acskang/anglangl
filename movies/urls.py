from django.urls import path

from . import views


app_name = "movies"

urlpatterns = [
    path("", views.search_page, name="index"),
    path("search/", views.search_page, name="search"),
    path("watch/<str:tmdb_id>/", views.watch_movie, name="watch"),
    path("api/search/", views.search_movies, name="api-search"),
    path("api/translate-title/", views.translate_title_ko2en, name="api-translate-title"),
    path("api/recent/", views.get_recent_searches, name="api-recent"),
]
