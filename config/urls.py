from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core.views import (
    LandingPageView,
    PlayerPageView,
    health_check,
    player_drama_detail_api,
    player_imdb_detail_api,
    player_imdb_search_api,
    player_drama_search_api,
    player_movie_search_api,
)

urlpatterns = [
    path("api/v1/health/", health_check, name="health-check"),
    path("admin/dashboard/", include("dashboard.urls")),
    path("admin/thumbnail/", include(("dramaNlearn.admin_urls", "thumbnail_admin"), namespace="thumbnail_admin")),
    path("admin/", admin.site.urls),
    path("", LandingPageView.as_view(), name="landing"),
    path("player/", PlayerPageView.as_view(), name="player"),
    path("player/api/movie-search/", player_movie_search_api, name="player-movie-search"),
    path("player/api/drama-search/", player_drama_search_api, name="player-drama-search"),
    path("player/api/drama-detail/", player_drama_detail_api, name="player-drama-detail"),
    path("player/api/imdb-search/", player_imdb_search_api, name="player-imdb-search"),
    path("player/api/imdb-detail/", player_imdb_detail_api, name="player-imdb-detail"),
    path("auth/", include(("platform_auth.urls", "platform_auth"), namespace="platform_auth")),
    path("internal-api/", include("internal_api.urls")),
    path("videos/", include("videos.urls")),
    path("clips/", include("clips.urls")),
    path("study/", include("study.urls")),
    path("jobs/", include("workers.urls")),
    path("dramaNlearn/", include("dramaNlearn.urls")),
    path("movies/", include("movies.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
