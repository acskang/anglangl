from django.urls import path

from .views import ClipJobHistoryView, DramaVideoJobHistoryView, MasterVideoJobHistoryView

app_name = "workers"

urlpatterns = [
    path("master-video/<int:video_id>/", MasterVideoJobHistoryView.as_view(), name="master-video-job-history"),
    path("clip/<int:clip_id>/", ClipJobHistoryView.as_view(), name="clip-job-history"),
    path("drama-video/<int:video_id>/", DramaVideoJobHistoryView.as_view(), name="drama-video-job-history"),
]
