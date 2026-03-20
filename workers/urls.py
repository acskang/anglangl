from django.urls import path

from .views import ClipJobHistoryView, MasterVideoJobHistoryView

app_name = "workers"

urlpatterns = [
    path("master-video/<int:video_id>/", MasterVideoJobHistoryView.as_view(), name="master-video-job-history"),
    path("clip/<int:clip_id>/", ClipJobHistoryView.as_view(), name="clip-job-history"),
]
