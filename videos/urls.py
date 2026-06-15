from django.urls import path
from django.views.generic import RedirectView

from .views import (
    MasterVideoCreateView,
    MasterVideoDeleteView,
    MasterVideoDownloadView,
    MasterVideoFetchInfoView,
    MasterVideoDetailView,
    MasterVideoEditView,
    MasterVideoAjaxUpdateView,
    MasterVideoJobStatusView,
    MasterVideoRetryView,
    MasterVideoSaveAjaxView,
    MasterVideoSubtitleUpdateView,
    MasterVideoThumbnailProxyView,
    MasterVideoThumbnailUpdateView,
    RegisterUploadVideoView,
    RegisterYoutubeView,
    ThumbnailAlbumView,
    UploadedVideoListView,
    VideoLibraryView,
    YoutubeVideoListView,
)

app_name = "videos"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="dashboard:home", permanent=False), name="list"),
    path("linked/", YoutubeVideoListView.as_view(), name="linked-list"),
    path("thumbnails/album/", ThumbnailAlbumView.as_view(), name="thumbnail-album"),
    path("local/", UploadedVideoListView.as_view(), name="upload-list"),
    path("create/", MasterVideoCreateView.as_view(), name="create"),
    path("create/youtube/", RegisterYoutubeView.as_view(), name="create-youtube"),
    path("create/video/", RegisterUploadVideoView.as_view(), name="create-video"),
    path("api/fetch-info/", MasterVideoFetchInfoView.as_view(), name="api-fetch-info"),
    path("api/save-video/", MasterVideoSaveAjaxView.as_view(), name="api-save"),
    path("<int:pk>/edit/", MasterVideoEditView.as_view(), name="edit"),
    path("<int:pk>/api/update/", MasterVideoAjaxUpdateView.as_view(), name="api-update"),
    path("<int:pk>/download/", MasterVideoDownloadView.as_view(), name="download"),
    path("<int:pk>/thumbnail-proxy/", MasterVideoThumbnailProxyView.as_view(), name="thumbnail-proxy"),
    path("<int:pk>/thumbnail/", MasterVideoThumbnailUpdateView.as_view(), name="thumbnail-update"),
    path("<int:pk>/subtitle/", MasterVideoSubtitleUpdateView.as_view(), name="subtitle-update"),
    path("<int:pk>/delete/", MasterVideoDeleteView.as_view(), name="delete"),
    path("<int:pk>/job-status/", MasterVideoJobStatusView.as_view(), name="job-status"),
    path("<int:pk>/", MasterVideoDetailView.as_view(), name="detail"),
    path("<int:pk>/retry/", MasterVideoRetryView.as_view(), name="retry"),
]
