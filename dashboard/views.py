from collections import defaultdict
from datetime import datetime, timezone as dt_timezone

from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from clips.models import Clip, ClipUploadBatch
from core.models import BackgroundJobState, ProcessingState
from study.models import ClipStudyHistory, StudyMaterial
from videos.models import MasterVideo
from workers.models import BackgroundJob


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/dashboard.html"

    recent_study_limit = 6
    quick_start_limit = 5
    recent_jobs_limit = 8
    recent_batches_limit = 5
    recent_videos_limit = 5
    recent_materials_limit = 5
    attention_limit = 8

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        now = timezone.now()
        recent_threshold = now - timezone.timedelta(days=7)

        recent_study_items = list(
            ClipStudyHistory.objects.filter(user=user)
            .select_related("clip", "clip__master_video", "clip__upload_batch")
            .order_by("-last_studied_at", "-updated_at")[: self.recent_study_limit]
        )
        quick_start_clips = list(
            Clip.objects.filter(owner=user, is_active=True, file_status=ProcessingState.READY)
            .select_related("master_video", "upload_batch")
            .order_by("-last_studied_at_cache", "-created_at")[: self.quick_start_limit]
        )
        recent_jobs = list(
            BackgroundJob.objects.filter(user=user)
            .order_by("-created_at")[: self.recent_jobs_limit]
        )
        recent_batches = list(
            ClipUploadBatch.objects.filter(owner=user)
            .order_by("-created_at")[: self.recent_batches_limit]
        )
        recent_master_videos = list(
            MasterVideo.objects.filter(owner=user, is_active=True)
            .order_by("-created_at")[: self.recent_videos_limit]
        )
        recent_study_materials = list(
            StudyMaterial.objects.filter(owner=user)
            .select_related("copied_from", "source_clip", "source_master_video", "source_drama_video")
            .order_by("-updated_at", "-created_at")[: self.recent_materials_limit]
        )

        self._decorate_study_items(recent_study_items)
        self._decorate_clips(quick_start_clips)
        self._decorate_jobs(recent_jobs)
        self._decorate_batches(recent_batches)
        self._decorate_master_videos(recent_master_videos)
        self._decorate_study_materials(recent_study_materials)

        attention_items = self._get_attention_items(user)

        context.update(
            {
                "stats": {
                    "master_video_count": MasterVideo.objects.filter(owner=user, is_active=True).count(),
                    "clip_count": Clip.objects.filter(owner=user, is_active=True).count(),
                    "study_material_count": StudyMaterial.objects.filter(owner=user).count(),
                    "recent_study_count": ClipStudyHistory.objects.filter(
                        user=user,
                        last_studied_at__gte=recent_threshold,
                    ).count(),
                    "active_job_count": BackgroundJob.objects.filter(
                        user=user,
                        status__in=[
                            BackgroundJobState.PENDING,
                            BackgroundJobState.QUEUED,
                            BackgroundJobState.PROCESSING,
                        ],
                    ).count(),
                    "failed_job_count": BackgroundJob.objects.filter(
                        user=user,
                        status=BackgroundJobState.FAILED,
                    ).count(),
                },
                "recent_study_items": recent_study_items,
                "quick_start_clips": quick_start_clips,
                "recent_jobs": recent_jobs,
                "recent_batches": recent_batches,
                "recent_master_videos": recent_master_videos,
                "recent_study_materials": recent_study_materials,
                "attention_items": attention_items,
            }
        )
        return context

    def _decorate_study_items(self, study_items):
        clips = [item.clip for item in study_items if item.clip_id]
        self._decorate_clips(clips)
        for item in study_items:
            clip = item.clip
            item.clip_thumbnail_url = getattr(clip, "dashboard_thumbnail_url", "")
            item.clip_detail_url = getattr(clip, "dashboard_detail_url", "")
            item.study_url = getattr(clip, "dashboard_study_url", "")
            item.clip_title = clip.title
            item.source_type_label = clip.get_source_type_display()
            item.formatted_duration = getattr(clip, "formatted_duration", "-")

    def _decorate_clips(self, clips):
        for clip in clips:
            clip.formatted_duration = self._format_duration(clip.duration_seconds)
            clip.visibility_label = "Public" if clip.is_public else "Private"
            clip.dashboard_detail_url = reverse("clips:detail", kwargs={"pk": clip.id})
            clip.dashboard_study_url = self._get_study_url(clip.id)
            if clip.thumbnail_file:
                clip.dashboard_thumbnail_url = clip.thumbnail_file.url
            elif clip.master_video and clip.master_video.thumbnail_url:
                clip.dashboard_thumbnail_url = clip.master_video.thumbnail_url
            else:
                clip.dashboard_thumbnail_url = ""

    def _decorate_jobs(self, jobs):
        related_ids_by_type = defaultdict(set)
        for job in jobs:
            parsed_id = self._parse_int(job.related_object_id)
            if parsed_id is not None and job.related_object_type:
                related_ids_by_type[job.related_object_type].add(parsed_id)

        clip_map = {
            obj.id: obj
            for obj in Clip.objects.filter(id__in=related_ids_by_type.get("clip", set()), owner=self.request.user)
            .select_related("master_video", "upload_batch")
        }
        video_map = {
            obj.id: obj
            for obj in MasterVideo.objects.filter(
                id__in=related_ids_by_type.get("master_video", set()),
                owner=self.request.user,
            )
        }
        batch_map = {
            obj.id: obj
            for obj in ClipUploadBatch.objects.filter(
                id__in=related_ids_by_type.get("clip_upload_batch", set()),
                owner=self.request.user,
            )
        }

        for job in jobs:
            job.related_object_label = self._job_related_label(job, clip_map, video_map, batch_map)
            job.retry_placeholder = job.status == BackgroundJobState.FAILED

    def _decorate_batches(self, batches):
        for batch in batches:
            batch.detail_url = reverse("clips:batch-detail", kwargs={"pk": batch.id})
            batch.completion_ratio = f"{batch.success_files}/{batch.total_files}"

    def _decorate_master_videos(self, videos):
        for video in videos:
            video.formatted_duration = self._format_duration(video.duration_seconds)
            video.detail_url = reverse("videos:detail", kwargs={"pk": video.id})
            video.clip_create_url = f"{reverse('clips:create')}?master_video={video.id}"

    def _decorate_study_materials(self, materials):
        for material in materials:
            material.detail_url = reverse("study:detail", kwargs={"pk": material.id})
            material.edit_url = reverse("study:edit", kwargs={"pk": material.id})
            material.source_summary = material.source_title or material.get_source_type_display()

    def _get_attention_items(self, user):
        items = []

        failed_jobs = list(
            BackgroundJob.objects.filter(user=user, status=BackgroundJobState.FAILED).order_by("-created_at")[:4]
        )
        self._decorate_jobs(failed_jobs)
        for job in failed_jobs:
            items.append(
                {
                    "kind": "job",
                    "title": job.get_job_type_display(),
                    "status": job.get_status_display(),
                    "message": job.error_message or job.message or "Background job failed.",
                    "meta": job.related_object_label or "Related object unavailable",
                    "timestamp": job.finished_at or job.updated_at,
                }
            )

        failed_videos = list(
            MasterVideo.objects.filter(
                owner=user,
                is_active=True,
                download_status=ProcessingState.FAILED,
            ).order_by("-updated_at")[:2]
        )
        for video in failed_videos:
            items.append(
                {
                    "kind": "video",
                    "title": video.title,
                    "status": video.get_download_status_display(),
                    "message": video.download_error_message or "Master video processing failed.",
                    "meta": "Master video",
                    "timestamp": video.updated_at,
                }
            )

        failed_clips = list(
            Clip.objects.filter(
                owner=user,
                is_active=True,
                file_status=ProcessingState.FAILED,
            )
            .select_related("master_video", "upload_batch")
            .order_by("-updated_at")[:2]
        )
        for clip in failed_clips:
            items.append(
                {
                    "kind": "clip",
                    "title": clip.title,
                    "status": clip.get_file_status_display(),
                    "message": clip.file_error_message or "Clip processing failed.",
                    "meta": clip.get_source_type_display(),
                    "timestamp": clip.updated_at,
                }
            )

        min_timestamp = datetime.min.replace(tzinfo=dt_timezone.utc)
        items.sort(key=lambda item: item["timestamp"] or min_timestamp, reverse=True)
        return items[: self.attention_limit]

    def _job_related_label(self, job, clip_map, video_map, batch_map):
        parsed_id = self._parse_int(job.related_object_id)
        if parsed_id is None:
            return job.related_object_type or ""

        if job.related_object_type == "clip":
            clip = clip_map.get(parsed_id)
            return f"Clip: {clip.title}" if clip else f"Clip #{parsed_id}"

        if job.related_object_type == "master_video":
            video = video_map.get(parsed_id)
            return f"Video: {video.title}" if video else f"Video #{parsed_id}"

        if job.related_object_type == "clip_upload_batch":
            batch = batch_map.get(parsed_id)
            return f"Batch: {batch.title}" if batch else f"Batch #{parsed_id}"

        return f"{job.related_object_type} #{parsed_id}"

    def _get_study_url(self, clip_id):
        return reverse("clips:detail", kwargs={"pk": clip_id})

    def _format_duration(self, seconds):
        total_seconds = int(seconds or 0)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    def _parse_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
