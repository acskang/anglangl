from django.urls import path

from .views import (
    clip_detail_view,
    clip_playback_file,
    clip_playback_link,
    clips_search,
    study_recent,
    upload_batch_detail_view,
    video_detail,
    videos_search,
)

app_name = "internal_api"

urlpatterns = [
    path("clips/search/", clips_search, name="clips-search"),
    path("clips/<int:clip_id>/", clip_detail_view, name="clip-detail"),
    path("clips/<int:clip_id>/playback-link/", clip_playback_link, name="clip-playback-link"),
    path("clips/<int:clip_id>/playback-file/", clip_playback_file, name="clip-playback-file"),
    path("study/recent/", study_recent, name="study-recent"),
    path("videos/search/", videos_search, name="videos-search"),
    path("videos/<int:video_id>/", video_detail, name="video-detail"),
    path("upload-batches/<int:batch_id>/", upload_batch_detail_view, name="upload-batch-detail"),
]
