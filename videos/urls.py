from django.urls import path

from .views import (
    MasterVideoCreateView,
    MasterVideoDeleteView,
    MasterVideoDetailView,
    MasterVideoJobStatusView,
    MasterVideoRetryView,
    MasterVideoSubtitleUpdateView,
    MasterVideoThumbnailUpdateView,
    RegisterUploadVideoView,
    RegisterYoutubeView,
    UploadedVideoListView,
    YoutubeVideoListView,
)

app_name = "videos"

urlpatterns = [
    path("", YoutubeVideoListView.as_view(), name="list"),
    path("local/", UploadedVideoListView.as_view(), name="upload-list"),
    path("create/", MasterVideoCreateView.as_view(), name="create"),
    path("create/youtube/", RegisterYoutubeView.as_view(), name="create-youtube"),
    path("create/video/", RegisterUploadVideoView.as_view(), name="create-video"),
    path("<int:pk>/thumbnail/", MasterVideoThumbnailUpdateView.as_view(), name="thumbnail-update"),
    path("<int:pk>/subtitle/", MasterVideoSubtitleUpdateView.as_view(), name="subtitle-update"),
    path("<int:pk>/delete/", MasterVideoDeleteView.as_view(), name="delete"),
    path("<int:pk>/job-status/", MasterVideoJobStatusView.as_view(), name="job-status"),
    path("<int:pk>/", MasterVideoDetailView.as_view(), name="detail"),
    path("<int:pk>/retry/", MasterVideoRetryView.as_view(), name="retry"),
]
