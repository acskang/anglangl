from pathlib import Path
import json
import re

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.utils.text import get_valid_filename, slugify
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import DeleteView, DetailView, FormView, ListView, UpdateView
from django.utils import timezone

from core.models import BackgroundJobState, ProcessingState
from videos.models import MasterVideo
from workers.models import BackgroundJob, BackgroundJobType

from .forms import (
    ClipBulkUploadForm,
    ClipCreateForm,
    ClipExtractUpdateForm,
    ClipMetadataForm,
    ClipPlanForm,
    UploadedClipUpdateForm,
)
from .models import Clip, ClipSourceType, ClipUploadBatch, ClipUploadBatchStatus
from .services.subtitles import SubtitleParseError, build_extraction_plan, parse_subtitle_file
from .services.whisper import WhisperError, WhisperService
from .tasks import extract_clip, process_uploaded_clip, refresh_upload_batch_status
from .timecode import format_hhmmss, parse_hhmmss


def _subtitle_preview_session_key(clip_id: int) -> str:
    return f"clip_subtitle_preview_{clip_id}"


def _build_fallback_subtitle_timing(subtitle_text: str, duration_seconds: int) -> str:
    tokens = re.findall(r"\S+", subtitle_text or "")
    if not tokens:
        return "[]"
    duration = max(float(duration_seconds or 0), 0.1)
    step = duration / len(tokens)
    words = []
    current = 0.0
    for token in tokens:
        next_time = current + step
        words.append(
            {
                "start": round(current, 3),
                "end": round(next_time, 3),
                "word": token,
            }
        )
        current = next_time
    words[-1]["end"] = round(duration, 3)
    return json.dumps(
        [
            {
                "start": 0.0,
                "end": round(duration, 3),
                "text": subtitle_text.strip(),
                "words": words,
            }
        ],
        ensure_ascii=False,
    )


def _clip_plan_session_key(video_id: int) -> str:
    return f"clip_extraction_plan_{video_id}"


def _build_clip_title(movie_title: str, subtitle_text: str, start_seconds: int) -> str:
    snippet = re.sub(r"\s+", " ", (subtitle_text or "").strip())
    if len(snippet) > 40:
        snippet = snippet[:40].rstrip() + "..."
    return f"{movie_title} | {snippet or f'Clip {start_seconds}'}"


def _build_clip_generated_filename(movie_title: str, subtitle_text: str, start_seconds: int) -> str:
    safe_movie = get_valid_filename(slugify(movie_title) or "movie")
    safe_snippet = get_valid_filename(slugify((subtitle_text or "").strip()[:20]) or "clip")
    return f"{safe_movie}_{safe_snippet}_{start_seconds:06d}.mp4"


def _subtitle_file_to_webvtt(subtitle_path: Path) -> str:
    suffix = subtitle_path.suffix.lower()
    content = subtitle_path.read_text(encoding="utf-8-sig", errors="replace")
    if suffix == ".vtt":
        if content.lstrip().startswith("WEBVTT"):
            return content
        return f"WEBVTT\n\n{content}"
    if suffix != ".srt":
        raise SubtitleParseError("Unsupported subtitle format. Use .srt or .vtt.")

    lines: list[str] = ["WEBVTT", ""]
    for raw_line in content.splitlines():
        if "-->" in raw_line:
            lines.append(raw_line.replace(",", "."))
        else:
            lines.append(raw_line)
    return "\n".join(lines) + "\n"


class ClipListView(LoginRequiredMixin, ListView):
    model = Clip
    template_name = "clips/clip_list.html"
    context_object_name = "clips"

    def get_queryset(self):
        return Clip.objects.select_related("master_video", "upload_batch", "owner")


class ClipCreateView(LoginRequiredMixin, FormView):
    form_class = ClipPlanForm
    template_name = "clips/clip_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        master_video_id = self.request.GET.get("master_video")
        if master_video_id and master_video_id.isdigit():
            master_video_id_int = int(master_video_id)
            initial["master_video"] = master_video_id_int
            stored_plan = self.request.session.get(_clip_plan_session_key(master_video_id_int), {})
            if isinstance(stored_plan, dict):
                if "range_start" in stored_plan:
                    initial["range_start"] = format_hhmmss(int(stored_plan["range_start"]))
                if "range_end" in stored_plan:
                    initial["range_end"] = format_hhmmss(int(stored_plan["range_end"]))
        initial.setdefault("range_start", "00:00:00")
        initial.setdefault("range_end", "00:05:00")
        return initial

    def _build_plan_rows_from_post(self) -> list[dict]:
        total_rows = int(self.request.POST.get("plan_total_rows") or 0)
        rows: list[dict] = []
        for index in range(total_rows):
            start_label = (self.request.POST.get(f"plan_start_{index}", "") or "").strip()
            end_label = (self.request.POST.get(f"plan_end_{index}", "") or "").strip()
            subtitle_text = (self.request.POST.get(f"plan_subtitle_{index}", "") or "").strip()
            start_seconds = None
            end_seconds = None
            status_note = "직접 검토 중"
            try:
                start_seconds = parse_hhmmss(start_label)
                end_seconds = parse_hhmmss(end_label)
                if end_seconds <= start_seconds:
                    status_note = "종료 시간이 시작 시간보다 커야 합니다."
            except ValueError:
                status_note = "시간 형식을 다시 확인하세요."

            rows.append(
                {
                    "row_id": index,
                    "clip_start_time": start_seconds,
                    "clip_start_label": start_label,
                    "clip_end_time": end_seconds,
                    "clip_end_label": end_label,
                    "subtitle_text": subtitle_text,
                    "status_note": status_note,
                    "selected": self.request.POST.get(f"plan_selected_{index}") == "on",
                }
            )
        return rows

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context["form"]
        master_video = form.initial.get("master_video")
        if form.is_bound and form.is_valid():
            master_video = form.cleaned_data.get("master_video")
        elif hasattr(form, "cleaned_data"):
            master_video = form.cleaned_data.get("master_video") or master_video
        if isinstance(master_video, int):
            master_video = MasterVideo.objects.filter(pk=master_video).first()

        plan_rows = []
        if self.request.method == "POST" and self.request.POST.get("plan_total_rows"):
            plan_rows = self._build_plan_rows_from_post()
        elif master_video:
            stored_plan = self.request.session.get(_clip_plan_session_key(master_video.id), {})
            if isinstance(stored_plan, dict):
                plan_rows = stored_plan.get("rows") or []
                context["stored_plan_range_start"] = stored_plan.get("range_start", "")
                context["stored_plan_range_end"] = stored_plan.get("range_end", "")

        context["master_video"] = master_video
        context["plan_rows"] = plan_rows
        context["plan_count"] = len(plan_rows)
        context["selected_plan_count"] = sum(1 for row in plan_rows if row.get("selected"))
        context["selected_plan_duration_seconds"] = sum(
            max(0, int((row.get("clip_end_time") or 0) - (row.get("clip_start_time") or 0)))
            for row in plan_rows
            if row.get("selected") and row.get("clip_start_time") is not None and row.get("clip_end_time") is not None
        )
        context["player_source_url"] = ""
        context["player_source_type"] = ""
        context["subtitle_url"] = (
            reverse("clips:master-video-subtitle-vtt", args=[master_video.id]) if master_video and master_video.subtitle_file else ""
        )
        context["subtitle_file_name"] = master_video.subtitle_file.name if master_video and master_video.subtitle_file else ""
        context["master_video_duration_label"] = (
            format_hhmmss(master_video.duration_seconds) if master_video and master_video.duration_seconds is not None else "-"
        )
        if master_video:
            if master_video.hls_manifest_file:
                context["player_source_url"] = master_video.hls_manifest_file.url
                context["player_source_type"] = "hls"
            elif master_video.video_file:
                context["player_source_url"] = master_video.video_file.url
                context["player_source_type"] = "file"
        context["plan_rows_json"] = json.dumps(plan_rows, ensure_ascii=False)
        return context

    def post(self, request, *args, **kwargs):
        action = (request.POST.get("action") or "").strip().lower()
        if action == "reset":
            return self._handle_reset()
        if action == "extract":
            return self._handle_extract()
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        master_video = form.cleaned_data["master_video"]
        try:
            subtitle_segments = parse_subtitle_file(Path(master_video.subtitle_file.path))
        except SubtitleParseError as exc:
            form.add_error("master_video", str(exc))
            return self.form_invalid(form)

        plan_rows = build_extraction_plan(
            subtitle_segments,
            range_start=form.cleaned_data["range_start"],
            range_end=form.cleaned_data["range_end"],
        )
        if not plan_rows:
            messages.warning(self.request, "선택한 범위와 겹치는 자막 구간이 없습니다.")
        else:
            messages.success(self.request, f"추출 계획 {len(plan_rows)}개를 생성했습니다.")

        self.request.session[_clip_plan_session_key(master_video.id)] = {
            "rows": plan_rows,
            "range_start": form.cleaned_data["range_start"],
            "range_end": form.cleaned_data["range_end"],
        }
        self.request.session.modified = True
        context = self.get_context_data(form=form)
        context["plan_rows"] = plan_rows
        context["plan_count"] = len(plan_rows)
        context["plan_rows_json"] = json.dumps(plan_rows, ensure_ascii=False)
        return self.render_to_response(context)

    def _handle_reset(self):
        master_video_id = self.request.POST.get("master_video")
        if master_video_id and master_video_id.isdigit():
            session_key = _clip_plan_session_key(int(master_video_id))
            if session_key in self.request.session:
                del self.request.session[session_key]
                self.request.session.modified = True
        messages.info(self.request, "추출 계획을 초기화했습니다.")
        if master_video_id:
            return redirect(f"{reverse('clips:create')}?master_video={master_video_id}")
        return redirect("clips:create")

    def _handle_extract(self):
        form = self.get_form()
        if not form.is_valid():
            return self.form_invalid(form)

        master_video = form.cleaned_data["master_video"]
        total_rows = int(self.request.POST.get("plan_total_rows") or 0)
        planned_rows = []
        for index in range(total_rows):
            selected = self.request.POST.get(f"plan_selected_{index}") == "on"
            start_raw = self.request.POST.get(f"plan_start_{index}", "")
            end_raw = self.request.POST.get(f"plan_end_{index}", "")
            subtitle_text = (self.request.POST.get(f"plan_subtitle_{index}", "") or "").strip()
            if not selected or not subtitle_text:
                continue
            try:
                start_seconds = parse_hhmmss(start_raw)
                end_seconds = parse_hhmmss(end_raw)
            except ValueError as exc:
                messages.error(self.request, f"{index + 1}번째 행 시간 형식이 잘못되었습니다: {exc}")
                return self.render_to_response(self.get_context_data(form=form))
            if end_seconds <= start_seconds:
                messages.error(self.request, f"{index + 1}번째 행의 종료 시간이 시작 시간보다 커야 합니다.")
                return self.render_to_response(self.get_context_data(form=form))
            planned_rows.append(
                {
                    "start_seconds": start_seconds,
                    "end_seconds": end_seconds,
                    "subtitle_text": subtitle_text,
                }
            )

        if not planned_rows:
            messages.warning(self.request, "추출할 계획 행을 하나 이상 선택하세요.")
            return self.render_to_response(self.get_context_data(form=form))

        queued_count = 0
        failed_count = 0
        with transaction.atomic():
            created_clips: list[Clip] = []
            for row in planned_rows:
                clip = Clip.objects.create(
                    owner=self.request.user,
                    source_type=ClipSourceType.EXTRACTED,
                    master_video=master_video,
                    title=_build_clip_title(master_video.title, row["subtitle_text"], row["start_seconds"]),
                    description=row["subtitle_text"],
                    subtitle=row["subtitle_text"],
                    subtitle_timing="[]",
                    start_time_seconds=row["start_seconds"],
                    end_time_seconds=row["end_seconds"],
                    is_public=form.cleaned_data.get("is_public", False),
                    file_status=ProcessingState.QUEUED,
                    file_error_message="",
                    upload_batch=None,
                    original_filename=_build_clip_generated_filename(master_video.title, row["subtitle_text"], row["start_seconds"]),
                    mime_type="video/mp4",
                )
                created_clips.append(clip)

        for clip in created_clips:
            job = BackgroundJob.objects.create(
                user=self.request.user,
                job_type=BackgroundJobType.CLIP_EXTRACTION,
                related_object_type="clip",
                related_object_id=str(clip.id),
                status=BackgroundJobState.QUEUED,
                progress_percent=0,
                message="Queued from extraction plan",
            )
            try:
                async_result = extract_clip.delay(clip.id)
            except Exception as exc:  # noqa: BLE001
                failed_count += 1
                clip.file_status = ProcessingState.FAILED
                clip.file_error_message = f"Failed to enqueue extraction task: {exc}"
                clip.save(update_fields=["file_status", "file_error_message", "updated_at", "extraction_status", "extraction_error_message"])
                job.status = BackgroundJobState.FAILED
                job.error_message = str(exc)
                job.message = "Failed to enqueue clip task"
                job.save(update_fields=["status", "error_message", "message", "updated_at"])
                continue
            queued_count += 1
            job.celery_task_id = async_result.id
            job.save(update_fields=["celery_task_id", "updated_at"])

        session_key = _clip_plan_session_key(master_video.id)
        if session_key in self.request.session:
            del self.request.session[session_key]
            self.request.session.modified = True

        if queued_count and failed_count:
            messages.warning(self.request, f"{queued_count}개 클립 추출을 큐에 등록했고 {failed_count}개는 실패했습니다.")
        elif queued_count:
            messages.success(self.request, f"{queued_count}개 클립 추출을 큐에 등록했습니다.")
        else:
            messages.error(self.request, "클립 추출 작업을 큐에 등록하지 못했습니다.")

        return redirect(f"{reverse('clips:create')}?master_video={master_video.id}")


class MasterVideoSubtitleTrackView(LoginRequiredMixin, View):
    def get(self, request, video_id: int):
        master_video = get_object_or_404(MasterVideo, pk=video_id)
        if master_video.owner_id != request.user.id:
            raise PermissionDenied
        if not master_video.subtitle_file:
            return HttpResponse(status=404)

        subtitle_path = Path(master_video.subtitle_file.path)
        try:
            content = _subtitle_file_to_webvtt(subtitle_path)
        except (OSError, SubtitleParseError):
            return HttpResponse(status=404)

        return HttpResponse(content, content_type="text/vtt; charset=utf-8")


class ClipBulkUploadView(LoginRequiredMixin, FormView):
    template_name = "clips/clip_bulk_upload.html"
    form_class = ClipBulkUploadForm

    def form_valid(self, form):
        uploaded_files = form.cleaned_data["files"]
        now = timezone.now()
        auto_title = f"Upload Batch {now.strftime('%Y-%m-%d %H:%M:%S')}"

        batch = ClipUploadBatch.objects.create(
            owner=self.request.user,
            title=auto_title,
            description="",
            source_directory_label="",
            total_files=len(uploaded_files),
            status=ClipUploadBatchStatus.UPLOADING,
        )

        batch_job = BackgroundJob.objects.create(
            user=self.request.user,
            job_type=BackgroundJobType.CLIP_BATCH_UPLOAD,
            related_object_type="clip_upload_batch",
            related_object_id=str(batch.id),
            status=BackgroundJobState.PROCESSING,
            progress_percent=0,
            message="Creating clip rows from uploaded files",
        )

        enqueue_failed = 0
        queued_count = 0
        default_is_public = form.cleaned_data.get("default_is_public", False)

        for f in uploaded_files:
            clip = Clip.objects.create(
                source_type=ClipSourceType.UPLOADED,
                master_video=None,
                upload_batch=batch,
                owner=self.request.user,
                title=Path(f.name).stem[:255] or "Untitled Clip",
                description="",
                original_filename=f.name[:255],
                file_size_bytes=getattr(f, "size", None),
                mime_type=getattr(f, "content_type", "") or "",
                start_time_seconds=0,
                end_time_seconds=0,
                duration_seconds=0,
                clip_file=f,
                is_public=default_is_public,
                file_status=ProcessingState.QUEUED,
                file_error_message="",
            )

            job = BackgroundJob.objects.create(
                user=self.request.user,
                job_type=BackgroundJobType.CLIP_FILE_POSTPROCESS,
                related_object_type="clip",
                related_object_id=str(clip.id),
                status=BackgroundJobState.QUEUED,
                progress_percent=0,
                message="Queued for uploaded clip post-processing",
            )

            try:
                async_result = process_uploaded_clip.delay(clip.id)
            except Exception as exc:  # noqa: BLE001
                enqueue_failed += 1
                clip.file_status = ProcessingState.FAILED
                clip.file_error_message = f"Failed to enqueue post-processing task: {exc}"
                clip.save(update_fields=["file_status", "file_error_message", "updated_at", "extraction_status", "extraction_error_message"])
                job.status = BackgroundJobState.FAILED
                job.error_message = str(exc)
                job.message = "Failed to enqueue clip postprocess task"
                job.save(update_fields=["status", "error_message", "message", "updated_at"])
                continue

            queued_count += 1
            job.celery_task_id = async_result.id
            job.save(update_fields=["celery_task_id", "updated_at"])

        if queued_count > 0:
            batch.status = ClipUploadBatchStatus.PROCESSING
            batch.error_message = ""
            batch_job.status = BackgroundJobState.SUCCESS
            batch_job.progress_percent = 100
            batch_job.message = "Batch queued successfully"
            batch_job.finished_at = timezone.now()
        else:
            batch.status = ClipUploadBatchStatus.FAILED
            batch.error_message = "All files failed to queue."
            batch_job.status = BackgroundJobState.FAILED
            batch_job.error_message = "All files failed to queue."
            batch_job.message = "Batch queue failed"
            batch_job.progress_percent = 100
            batch_job.finished_at = timezone.now()

        batch.failed_files = enqueue_failed
        batch.success_files = 0
        batch.save(update_fields=["status", "error_message", "failed_files", "success_files", "updated_at"])
        batch_job.save(update_fields=["status", "progress_percent", "message", "error_message", "finished_at", "updated_at"])

        refresh_upload_batch_status.delay(batch.id)

        if enqueue_failed:
            messages.warning(self.request, f"Batch created. {enqueue_failed} file(s) failed to queue.")
        else:
            messages.success(self.request, "Batch uploaded and queued for processing.")

        return redirect("clips:batch-detail", pk=batch.id)


class ClipUploadBatchListView(LoginRequiredMixin, ListView):
    model = ClipUploadBatch
    template_name = "clips/clip_batch_list.html"
    context_object_name = "batches"

    def get_queryset(self):
        return ClipUploadBatch.objects.filter(owner=self.request.user)


class ClipUploadBatchDetailView(LoginRequiredMixin, DetailView):
    model = ClipUploadBatch
    template_name = "clips/clip_batch_detail.html"
    context_object_name = "batch"

    def get_queryset(self):
        return ClipUploadBatch.objects.filter(owner=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["clips"] = self.object.clips.all().order_by("-created_at")
        return context


class ClipVisibilityQuerysetMixin:
    def get_queryset(self):
        return Clip.objects.select_related("master_video", "owner", "upload_batch")


class ClipDetailView(ClipVisibilityQuerysetMixin, DetailView):
    model = Clip
    template_name = "clips/clip_detail.html"
    context_object_name = "clip"

    def get_queryset(self):
        return super().get_queryset().distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        can_manage = self.request.user.is_authenticated and self.object.owner_id == self.request.user.id
        context["can_manage"] = can_manage
        if self.object.hls_manifest_file:
            context["playback_url"] = self.object.hls_manifest_file.url
            context["playback_type"] = "hls"
        elif self.object.clip_file:
            context["playback_url"] = self.object.clip_file.url
            context["playback_type"] = "file"
        else:
            context["playback_url"] = ""
            context["playback_type"] = ""
        preview = self.request.session.get(_subtitle_preview_session_key(self.object.id), {})
        if isinstance(preview, dict):
            context["subtitle_preview"] = preview.get("text", "")
        else:
            context["subtitle_preview"] = str(preview or "")
        context["subtitle_timing_json"] = self.object.subtitle_timing or _build_fallback_subtitle_timing(
            self.object.subtitle or "",
            self.object.duration_seconds,
        )
        if can_manage:
            context["metadata_form"] = ClipMetadataForm(instance=self.object)
        return context


class ClipOwnerRequiredMixin(LoginRequiredMixin):
    def get_queryset(self):
        return Clip.objects.filter(owner=self.request.user).select_related("master_video", "upload_batch")


class ClipUpdateView(ClipOwnerRequiredMixin, UpdateView):
    model = Clip
    template_name = "clips/clip_form.html"

    def get_form_class(self):
        if self.get_object().source_type == ClipSourceType.UPLOADED:
            return UploadedClipUpdateForm
        return ClipExtractUpdateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.get_object().source_type == ClipSourceType.EXTRACTED:
            kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        clip = form.save(commit=False)

        if clip.source_type == ClipSourceType.UPLOADED:
            clip.save()
            messages.success(self.request, "Uploaded clip metadata updated.")
            return redirect("clips:detail", pk=clip.id)

        clip.file_status = ProcessingState.QUEUED
        clip.file_error_message = ""
        clip.save()

        job = BackgroundJob.objects.create(
            user=self.request.user,
            job_type=BackgroundJobType.CLIP_EXTRACTION,
            related_object_type="clip",
            related_object_id=str(clip.id),
            status=BackgroundJobState.QUEUED,
            progress_percent=0,
            message="Queued after clip update",
        )

        try:
            async_result = extract_clip.delay(clip.id)
        except Exception as exc:  # noqa: BLE001
            clip.file_status = ProcessingState.FAILED
            clip.file_error_message = f"Failed to enqueue extraction task: {exc}"
            clip.save(update_fields=["file_status", "file_error_message", "updated_at", "extraction_status", "extraction_error_message"])
            job.status = BackgroundJobState.FAILED
            job.error_message = str(exc)
            job.message = "Failed to enqueue clip task"
            job.save(update_fields=["status", "error_message", "message", "updated_at"])
            messages.error(self.request, "Clip updated, but queueing failed.")
            return redirect("clips:detail", pk=clip.id)

        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])

        messages.success(self.request, "Clip updated and re-queued for extraction.")
        return redirect("clips:detail", pk=clip.id)


class ClipDeleteView(ClipOwnerRequiredMixin, DeleteView):
    model = Clip
    template_name = "clips/clip_confirm_delete.html"

    def get_success_url(self):
        messages.success(self.request, "Clip deleted.")
        return reverse("clips:list")


class ClipRetryView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        clip = get_object_or_404(Clip, pk=pk)
        if clip.owner_id != request.user.id:
            raise PermissionDenied

        if clip.file_status != ProcessingState.FAILED:
            messages.info(request, "Only failed clip processing can be retried.")
            return redirect("clips:detail", pk=clip.id)

        clip.file_status = ProcessingState.QUEUED
        clip.file_error_message = ""
        clip.save(update_fields=["file_status", "file_error_message", "updated_at", "extraction_status", "extraction_error_message"])

        if clip.source_type == ClipSourceType.UPLOADED:
            job_type = BackgroundJobType.CLIP_FILE_POSTPROCESS
            task_func = process_uploaded_clip
            message = "Retry queued for uploaded clip post-processing"
        else:
            job_type = BackgroundJobType.CLIP_EXTRACTION
            task_func = extract_clip
            message = "Retry queued for clip extraction"

        job = BackgroundJob.objects.create(
            user=request.user,
            job_type=job_type,
            related_object_type="clip",
            related_object_id=str(clip.id),
            status=BackgroundJobState.QUEUED,
            progress_percent=0,
            message=message,
        )

        try:
            async_result = task_func.delay(clip.id)
        except Exception as exc:  # noqa: BLE001
            clip.file_status = ProcessingState.FAILED
            clip.file_error_message = f"Failed to enqueue retry task: {exc}"
            clip.save(update_fields=["file_status", "file_error_message", "updated_at", "extraction_status", "extraction_error_message"])
            job.status = BackgroundJobState.FAILED
            job.error_message = str(exc)
            job.message = "Failed to enqueue retry task"
            job.save(update_fields=["status", "error_message", "message", "updated_at"])
            messages.error(request, "Retry could not be queued.")
            return redirect("clips:detail", pk=clip.id)

        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])

        messages.success(request, "Retry queued.")
        return redirect("clips:detail", pk=clip.id)


class ClipMetadataUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        clip = get_object_or_404(Clip, pk=pk)
        if clip.owner_id != request.user.id:
            raise PermissionDenied

        form = ClipMetadataForm(request.POST, instance=clip)
        if form.is_valid():
            updated_clip = form.save(commit=False)
            updated_clip.save(update_fields=["title", "description", "updated_at"])
            messages.success(request, "Title and description updated.")
        else:
            messages.error(request, "Failed to update title/description.")

        return redirect("clips:detail", pk=clip.id)


class ClipSubtitleExtractView(LoginRequiredMixin, View):
    ALLOWED_MODELS = {"tiny", "base", "small", "medium"}
    ALLOWED_LANGUAGES = {"auto", "en", "ko"}

    def post(self, request, pk: int):
        clip = get_object_or_404(Clip, pk=pk)
        if clip.owner_id != request.user.id:
            raise PermissionDenied

        if not clip.clip_file:
            messages.error(request, "Subtitle extraction requires a clip file.")
            return redirect("clips:detail", pk=clip.id)

        model = (request.POST.get("whisper_model") or "base").strip().lower()
        language = (request.POST.get("whisper_language") or "en").strip().lower()

        if model not in self.ALLOWED_MODELS:
            model = "base"
        if language not in self.ALLOWED_LANGUAGES:
            language = "en"

        try:
            transcript = WhisperService(
                model=model,
                language=None if language == "auto" else language,
                task="transcribe",
            ).transcribe(Path(clip.clip_file.path))
        except WhisperError as exc:
            messages.error(request, f"Subtitle extraction failed: {exc}")
            return redirect("clips:detail", pk=clip.id)

        request.session[_subtitle_preview_session_key(clip.id)] = {
            "text": transcript.text or "",
            "timing_json": transcript.timing_json or "[]",
        }
        request.session.modified = True
        messages.success(request, "Subtitle extracted. Review it and save when ready.")
        return redirect("clips:detail", pk=clip.id)


class ClipSubtitleSaveView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        clip = get_object_or_404(Clip, pk=pk)
        if clip.owner_id != request.user.id:
            raise PermissionDenied

        subtitle_text = (request.POST.get("subtitle_text") or "").strip()
        preview = request.session.get(_subtitle_preview_session_key(clip.id), {})
        preview_text = preview.get("text", "") if isinstance(preview, dict) else ""
        preview_timing_json = preview.get("timing_json", "[]") if isinstance(preview, dict) else "[]"

        clip.subtitle = subtitle_text or None
        if subtitle_text and subtitle_text == preview_text.strip():
            clip.subtitle_timing = preview_timing_json or "[]"
        else:
            clip.subtitle_timing = "[]"
        clip.save(update_fields=["subtitle", "subtitle_timing", "updated_at"])

        session_key = _subtitle_preview_session_key(clip.id)
        if session_key in request.session:
            del request.session[session_key]
            request.session.modified = True

        messages.success(request, "Subtitle saved.")
        return redirect("clips:detail", pk=clip.id)
