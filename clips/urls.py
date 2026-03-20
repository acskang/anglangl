from django.urls import path

from .views import (
    ClipBulkUploadView,
    ClipCreateView,
    ClipDeleteView,
    ClipDetailView,
    ClipListView,
    ClipMetadataUpdateView,
    ClipRetryView,
    ClipSubtitleExtractView,
    ClipSubtitleSaveView,
    MasterVideoSubtitleTrackView,
    ClipUpdateView,
    ClipUploadBatchDetailView,
    ClipUploadBatchListView,
)

app_name = "clips"

urlpatterns = [
    path("", ClipListView.as_view(), name="list"),
    path("create/", ClipCreateView.as_view(), name="create"),
    path("master-video/<int:video_id>/subtitle.vtt", MasterVideoSubtitleTrackView.as_view(), name="master-video-subtitle-vtt"),
    path("bulk-upload/", ClipBulkUploadView.as_view(), name="bulk-upload"),
    path("batches/", ClipUploadBatchListView.as_view(), name="batch-list"),
    path("batches/<int:pk>/", ClipUploadBatchDetailView.as_view(), name="batch-detail"),
    path("<int:pk>/", ClipDetailView.as_view(), name="detail"),
    path("<int:pk>/metadata/", ClipMetadataUpdateView.as_view(), name="metadata-update"),
    path("<int:pk>/subtitle-extract/", ClipSubtitleExtractView.as_view(), name="subtitle-extract"),
    path("<int:pk>/subtitle-save/", ClipSubtitleSaveView.as_view(), name="subtitle-save"),
    path("<int:pk>/edit/", ClipUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", ClipDeleteView.as_view(), name="delete"),
    path("<int:pk>/retry/", ClipRetryView.as_view(), name="retry"),
]
