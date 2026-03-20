from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.views.generic import ListView

from clips.models import Clip
from videos.models import MasterVideo
from workers.models import BackgroundJobType

from .models import BackgroundJob


class MasterVideoJobHistoryView(LoginRequiredMixin, ListView):
    model = BackgroundJob
    template_name = "workers/master_video_job_history.html"
    context_object_name = "jobs"

    def dispatch(self, request, *args, **kwargs):
        self.master_video = MasterVideo.objects.filter(pk=kwargs["video_id"]).first()
        if self.master_video is None:
            raise PermissionDenied
        if self.master_video.owner_id != request.user.id:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return BackgroundJob.objects.filter(
            user=self.request.user,
            related_object_type="master_video",
            related_object_id=str(self.master_video.id),
            job_type__in=[
                BackgroundJobType.YOUTUBE_DOWNLOAD,
                BackgroundJobType.MASTER_VIDEO_UPLOAD_PROCESS,
            ],
        ).order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["master_video"] = self.master_video
        return context


class ClipJobHistoryView(LoginRequiredMixin, ListView):
    model = BackgroundJob
    template_name = "workers/clip_job_history.html"
    context_object_name = "jobs"

    def dispatch(self, request, *args, **kwargs):
        self.clip = Clip.objects.select_related("master_video").filter(pk=kwargs["clip_id"]).first()
        if self.clip is None:
            raise PermissionDenied
        if self.clip.owner_id != request.user.id:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return BackgroundJob.objects.filter(
            user=self.request.user,
            related_object_type="clip",
            related_object_id=str(self.clip.id),
        ).order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["clip"] = self.clip
        return context
