from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.text import get_valid_filename
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, FormView, ListView
from PIL import Image, ImageOps

from core.models import BackgroundJobState, ProcessingState
from workers.models import BackgroundJob, BackgroundJobType

from .forms import MasterVideoCreateForm
from .models import MasterVideo, MasterVideoSourceType
from .tasks import download_youtube_video, process_uploaded_master_video


THUMBNAIL_OUTPUT_SIZE = (960, 540)
THUMBNAIL_BASE_QUALITY = 75
THUMBNAIL_TARGET_MAX_BYTES = 250 * 1024


def _build_thumbnail_content(uploaded_file) -> ContentFile:
    uploaded_file.seek(0)
    with Image.open(uploaded_file) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        fitted = ImageOps.fit(
            image,
            THUMBNAIL_OUTPUT_SIZE,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

        if fitted.mode == "RGBA":
            alpha = fitted.getchannel("A")
            if alpha.getextrema() == (255, 255):
                fitted = fitted.convert("RGB")

        output = BytesIO()
        selected_bytes = b""
        for quality in (75, 72, 68, 65, 60):
            output.seek(0)
            output.truncate(0)
            fitted.save(output, format="WEBP", quality=quality, method=6)
            selected_bytes = output.getvalue()
            if len(selected_bytes) <= THUMBNAIL_TARGET_MAX_BYTES:
                break

    safe_name = get_valid_filename(Path(uploaded_file.name).stem or "thumbnail")
    return ContentFile(selected_bytes, name=f"{safe_name}.webp")


def _delete_previous_thumbnail_file(thumbnail_url: str) -> None:
    if not thumbnail_url:
        return
    parsed = urlparse(thumbnail_url)
    media_url = str(settings.MEDIA_URL or "/media/")
    media_path = parsed.path or ""
    if not media_path.startswith(media_url):
        return
    relative_path = media_path[len(media_url) :].lstrip("/")
    if relative_path:
        default_storage.delete(relative_path)


class VideoVisibilityQuerySetMixin(LoginRequiredMixin):
    def get_queryset(self):
        return MasterVideo.objects.select_related("owner")


class YoutubeVideoListView(VideoVisibilityQuerySetMixin, ListView):
    model = MasterVideo
    template_name = "videos/youtube_list.html"
    context_object_name = "videos"

    def get_queryset(self):
        return super().get_queryset().filter(source_type=MasterVideoSourceType.YOUTUBE)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Youtube"
        context["page_kicker"] = "Library"
        context["page_description"] = "등록된 YouTube 영상만 모아서 보는 화면입니다."
        context["empty_message"] = "등록된 YouTube 영상이 없습니다."
        return context


class UploadedVideoListView(VideoVisibilityQuerySetMixin, ListView):
    model = MasterVideo
    template_name = "videos/upload_list.html"
    context_object_name = "videos"

    def get_queryset(self):
        return super().get_queryset().filter(source_type=MasterVideoSourceType.UPLOAD)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Videos"
        context["page_kicker"] = "Library"
        context["page_description"] = "등록된 로컬 비디오만 모아서 보는 화면입니다."
        context["empty_message"] = "등록된 로컬 비디오가 없습니다."
        return context


class MasterVideoDetailView(VideoVisibilityQuerySetMixin, DetailView):
    model = MasterVideo
    template_name = "videos/video_detail.html"
    context_object_name = "video"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_manage"] = self.request.user.is_authenticated and self.object.owner_id == self.request.user.id
        context["job"] = None
        if context["can_manage"]:
            context["job"] = (
                BackgroundJob.objects.filter(
                    user=self.request.user,
                    related_object_type="master_video",
                    related_object_id=str(self.object.id),
                    job_type__in=[
                        BackgroundJobType.YOUTUBE_DOWNLOAD,
                        BackgroundJobType.MASTER_VIDEO_UPLOAD_PROCESS,
                    ],
                )
                .order_by("-created_at")
                .first()
            )
        context["clips"] = self.object.clips.order_by("-created_at")
        context["subtitle_url"] = self.object.subtitle_file.url if self.object.subtitle_file else ""
        if self.object.hls_manifest_file:
            context["playback_url"] = self.object.hls_manifest_file.url
            context["playback_type"] = "hls"
        elif self.object.video_file:
            context["playback_url"] = self.object.video_file.url
            context["playback_type"] = "file"
        else:
            context["playback_url"] = ""
            context["playback_type"] = ""
        if self.object.source_type == MasterVideoSourceType.UPLOAD:
            context["list_url"] = reverse("videos:upload-list")
            context["list_label"] = "Videos"
        else:
            context["list_url"] = reverse("videos:list")
            context["list_label"] = "Youtube"
        return context


class MasterVideoCreateView(LoginRequiredMixin, FormView):
    template_name = "videos/video_form.html"
    form_class = MasterVideoCreateForm

    def form_valid(self, form):
        source_type = form.cleaned_data["source_type"]
        if source_type == MasterVideoSourceType.UPLOAD:
            return self._handle_uploaded_video(form)
        return self._handle_youtube_video(form)

    def _handle_youtube_video(self, form):
        youtube_video_id = form.cleaned_data["youtube_video_id"]
        youtube_url = form.cleaned_data["youtube_url"]

        try:
            video = MasterVideo.objects.create(
                owner=self.request.user,
                source_type=MasterVideoSourceType.YOUTUBE,
                youtube_video_id=youtube_video_id,
                youtube_url=youtube_url,
                title=f"Video {youtube_video_id}",
                download_status=ProcessingState.QUEUED,
            )
        except IntegrityError:
            existing = MasterVideo.objects.get(owner=self.request.user, youtube_video_id=youtube_video_id)
            messages.info(self.request, "This video is already registered in your library.")
            return redirect("videos:detail", pk=existing.id)

        job = BackgroundJob.objects.create(
            user=self.request.user,
            job_type="youtube_download",
            related_object_type="master_video",
            related_object_id=str(video.id),
            status=BackgroundJobState.QUEUED,
            progress_percent=0,
            message="Queued for download",
        )

        try:
            async_result = download_youtube_video.delay(video.id)
        except Exception as exc:  # noqa: BLE001
            video.download_status = ProcessingState.FAILED
            video.download_error_message = f"Failed to enqueue task: {exc}"
            video.save(update_fields=["download_status", "download_error_message", "updated_at"])
            job.status = BackgroundJobState.FAILED
            job.error_message = str(exc)
            job.message = "Failed to enqueue Celery task"
            job.save(update_fields=["status", "error_message", "message", "updated_at"])
            messages.error(self.request, "Video was registered, but queueing failed.")
            return redirect("videos:detail", pk=video.id)

        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])

        messages.success(self.request, "Video registered and queued for background download.")
        return redirect("videos:detail", pk=video.id)

    def _handle_uploaded_video(self, form):
        uploaded_file = form.cleaned_data["video_file"]
        title = (form.cleaned_data.get("upload_title") or "").strip() or Path(uploaded_file.name).stem

        video = MasterVideo.objects.create(
            owner=self.request.user,
            source_type=MasterVideoSourceType.UPLOAD,
            title=title,
            download_status=ProcessingState.QUEUED,
        )

        video.video_file.save(uploaded_file.name, uploaded_file, save=False)
        subtitle_file = form.cleaned_data.get("subtitle_file")
        if subtitle_file:
            video.subtitle_file.save(subtitle_file.name, subtitle_file, save=False)
        video.file_size_bytes = video.video_file.size
        video.save(
            update_fields=[
                "video_file",
                "subtitle_file",
                "file_size_bytes",
                "download_status",
                "updated_at",
            ]
        )

        job = BackgroundJob.objects.create(
            user=self.request.user,
            job_type=BackgroundJobType.MASTER_VIDEO_UPLOAD_PROCESS,
            related_object_type="master_video",
            related_object_id=str(video.id),
            status=BackgroundJobState.QUEUED,
            progress_percent=0,
            message="Queued for uploaded video processing",
        )

        try:
            async_result = process_uploaded_master_video.delay(video.id)
        except Exception as exc:  # noqa: BLE001
            video.download_status = ProcessingState.FAILED
            video.download_error_message = f"Failed to enqueue upload processing task: {exc}"
            video.save(update_fields=["download_status", "download_error_message", "updated_at"])
            job.status = BackgroundJobState.FAILED
            job.error_message = str(exc)
            job.message = "Failed to enqueue upload processing task"
            job.save(update_fields=["status", "error_message", "message", "updated_at"])
            messages.error(self.request, "Video file was uploaded, but background processing could not be queued.")
            return redirect("videos:detail", pk=video.id)

        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])

        messages.success(self.request, "Local video uploaded and queued for background processing.")
        return redirect("videos:detail", pk=video.id)


class RegisterYoutubeView(MasterVideoCreateView):
    template_name = "videos/register_youtube.html"

    def get_initial(self):
        initial = super().get_initial()
        initial["source_type"] = MasterVideoSourceType.YOUTUBE
        return initial

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["source_type"].initial = MasterVideoSourceType.YOUTUBE
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["recent_youtube_videos"] = (
            MasterVideo.objects.filter(
                owner=self.request.user,
                source_type=MasterVideoSourceType.YOUTUBE,
            )
            .order_by("-created_at")[:12]
        )
        return context


class RegisterUploadVideoView(MasterVideoCreateView):
    template_name = "videos/register_upload.html"

    def get_initial(self):
        initial = super().get_initial()
        initial["source_type"] = MasterVideoSourceType.UPLOAD
        return initial

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["source_type"].initial = MasterVideoSourceType.UPLOAD
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["recent_upload_videos"] = (
            MasterVideo.objects.filter(
                owner=self.request.user,
                source_type=MasterVideoSourceType.UPLOAD,
            )
            .order_by("-created_at")[:12]
        )
        return context


class MasterVideoDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        video = get_object_or_404(MasterVideo, pk=pk, source_type=MasterVideoSourceType.UPLOAD)
        if video.owner_id != request.user.id:
            raise PermissionDenied

        if video.video_file:
            video.video_file.delete(save=False)
        if video.subtitle_file:
            video.subtitle_file.delete(save=False)

        if video.hls_manifest_file:
            hls_dir = Path(video.hls_manifest_file.path).parent
            video.hls_manifest_file.delete(save=False)
            if hls_dir.exists():
                for child in hls_dir.iterdir():
                    if child.is_file():
                        child.unlink()
                try:
                    hls_dir.rmdir()
                except OSError:
                    pass

        video.delete()
        messages.success(request, "Video deleted.")
        return redirect("videos:upload-list")


class MasterVideoSubtitleUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        video = get_object_or_404(MasterVideo, pk=pk, source_type=MasterVideoSourceType.UPLOAD)
        if video.owner_id != request.user.id:
            raise PermissionDenied

        subtitle_file = request.FILES.get("subtitle_file")
        if not subtitle_file:
            messages.error(request, "Choose a subtitle file first.")
            return redirect("videos:detail", pk=video.id)

        ext = Path(subtitle_file.name).suffix.lower()
        if ext not in {".srt", ".vtt", ".ass", ".ssa"}:
            messages.error(request, "Unsupported subtitle file extension.")
            return redirect("videos:detail", pk=video.id)

        if video.subtitle_file:
            video.subtitle_file.delete(save=False)

        video.subtitle_file.save(subtitle_file.name, subtitle_file, save=False)
        video.save(update_fields=["subtitle_file", "updated_at"])
        messages.success(request, "Subtitle uploaded.")
        return redirect("videos:detail", pk=video.id)


class MasterVideoRetryView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        video = get_object_or_404(MasterVideo, pk=pk)
        if video.owner_id != request.user.id:
            raise PermissionDenied

        if video.source_type != MasterVideoSourceType.YOUTUBE:
            messages.info(request, "Only YouTube videos can be retried.")
            return redirect("videos:detail", pk=video.id)

        if video.download_status != ProcessingState.FAILED:
            messages.info(request, "Only failed downloads can be retried.")
            return redirect("videos:detail", pk=video.id)

        video.download_status = ProcessingState.QUEUED
        video.download_error_message = ""
        video.save(update_fields=["download_status", "download_error_message", "updated_at"])

        job = BackgroundJob.objects.create(
            user=request.user,
            job_type="youtube_download",
            related_object_type="master_video",
            related_object_id=str(video.id),
            status=BackgroundJobState.QUEUED,
            progress_percent=0,
            message="Retry queued",
        )
        try:
            async_result = download_youtube_video.delay(video.id)
        except Exception as exc:  # noqa: BLE001
            video.download_status = ProcessingState.FAILED
            video.download_error_message = f"Failed to enqueue retry task: {exc}"
            video.save(update_fields=["download_status", "download_error_message", "updated_at"])
            job.status = BackgroundJobState.FAILED
            job.error_message = str(exc)
            job.message = "Failed to enqueue retry task"
            job.save(update_fields=["status", "error_message", "message", "updated_at"])
            messages.error(request, "Retry could not be queued.")
            return redirect(reverse("videos:detail", kwargs={"pk": video.id}))

        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])

        messages.success(request, "Retry queued.")
        return redirect(reverse("videos:detail", kwargs={"pk": video.id}))


class MasterVideoJobStatusView(LoginRequiredMixin, View):
    def get(self, request, pk: int):
        video = get_object_or_404(MasterVideo, pk=pk)
        if video.owner_id != request.user.id:
            raise PermissionDenied

        job = (
            BackgroundJob.objects.filter(
                user=request.user,
                related_object_type="master_video",
                related_object_id=str(video.id),
                job_type__in=[
                    BackgroundJobType.YOUTUBE_DOWNLOAD,
                    BackgroundJobType.MASTER_VIDEO_UPLOAD_PROCESS,
                ],
            )
            .order_by("-created_at")
            .first()
        )

        if not job:
            return JsonResponse({"ok": True, "job": None})

        return JsonResponse(
            {
                "ok": True,
                "job": {
                    "id": job.id,
                    "job_type": job.job_type,
                    "status": job.status,
                    "status_label": job.get_status_display(),
                    "progress_percent": job.progress_percent,
                    "message": job.message or "-",
                    "error_message": job.error_message or "-",
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                    "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                },
                "video": {
                    "download_status": video.download_status,
                    "download_status_label": video.get_download_status_display(),
                    "download_error_message": video.download_error_message or "",
                    "playback_url": video.hls_manifest_file.url if video.hls_manifest_file else (video.video_file.url if video.video_file else ""),
                    "playback_type": "hls" if video.hls_manifest_file else ("file" if video.video_file else ""),
                },
            }
        )


class MasterVideoThumbnailUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        video = get_object_or_404(MasterVideo, pk=pk)
        if video.owner_id != request.user.id:
            raise PermissionDenied

        uploaded_file = request.FILES.get("thumbnail_file")
        if not uploaded_file:
            return JsonResponse({"ok": False, "error": "썸네일 파일을 선택해주세요."}, status=400)

        processed_image = _build_thumbnail_content(uploaded_file)
        _delete_previous_thumbnail_file(video.thumbnail_url)
        storage_path = Path("thumbnails") / f"video-{video.id}-{uuid4().hex}-{processed_image.name}"
        saved_path = default_storage.save(str(storage_path), processed_image)
        video.thumbnail_url = request.build_absolute_uri(default_storage.url(saved_path))
        video.save(update_fields=["thumbnail_url", "updated_at"])

        return JsonResponse({"ok": True, "thumbnail_url": video.thumbnail_url})
