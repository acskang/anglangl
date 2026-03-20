from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core.views import LandingPageView, PlayerPageView, player_movie_search_api

urlpatterns = [
    path("admin/dashboard/", include("dashboard.urls")),
    path("admin/thumbnail/", include(("dramaNlearn.admin_urls", "thumbnail_admin"), namespace="thumbnail_admin")),
    path("admin/", admin.site.urls),
    path("", LandingPageView.as_view(), name="landing"),
    path("player/", PlayerPageView.as_view(), name="player"),
    path("player/api/movie-search/", player_movie_search_api, name="player-movie-search"),
    path("auth/", include(("platform_auth.urls", "platform_auth"), namespace="platform_auth")),
    path("internal-api/", include("internal_api.urls")),
    path("videos/", include("videos.urls")),
    path("clips/", include("clips.urls")),
    path("jobs/", include("workers.urls")),
    path("dramaNlearn/", include("dramaNlearn.urls")),
    path("legacy/", include("youtube_saver.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
