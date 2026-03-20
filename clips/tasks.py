import mimetypes
import shutil
from pathlib import Path
from uuid import uuid4

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone
from django.utils.text import get_valid_filename, slugify

from core.models import BackgroundJobState, ProcessingState
from workers.models import BackgroundJob

from .models import Clip, ClipSourceType, ClipUploadBatch, ClipUploadBatchStatus
from .services.ffmpeg import FfmpegPermanentError, FfmpegService, FfmpegTransientError


CLIP_RETRY_LIMIT = 2
CLIP_RETRY_DELAY_SECONDS = 60


def _clip_task_kwargs(queue: str) -> dict[str, object]:
    return {
        "bind": True,
        "queue": queue,
        "soft_time_limit": settings.CELERY_FFMPEG_SOFT_TIME_LIMIT,
        "time_limit": settings.CELERY_FFMPEG_TIME_LIMIT,
    }


def _build_clip_output_filename(clip: Clip) -> str:
    movie_title = clip.master_video.title if clip.master_video else clip.title
    subtitle_snippet = (clip.subtitle or clip.title or "clip").strip()[:20]
    safe_movie = get_valid_filename(slugify(movie_title) or "movie")
    safe_snippet = get_valid_filename(slugify(subtitle_snippet) or "clip")
    time_part = f"{clip.start_time_seconds:06d}"
    return f"{safe_movie}_{safe_snippet}_{time_part}_{clip.id}.mp4"


def _get_related_job(clip: Clip) -> BackgroundJob | None:
    return (
        BackgroundJob.objects.filter(
            related_object_type="clip",
            related_object_id=str(clip.id),
        )
        .order_by("-created_at")
        .first()
    )


def _mark_clip_failed(clip: Clip, job: BackgroundJob | None, error_message: str) -> None:
    clip.file_status = ProcessingState.FAILED
    clip.file_error_message = error_message
    clip.save(update_fields=["file_status", "file_error_message", "updated_at", "extraction_status", "extraction_error_message"])

    if job:
        job.status = BackgroundJobState.FAILED
        job.error_message = error_message
        job.message = "Clip processing failed"
        job.progress_percent = 100
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "message", "progress_percent", "finished_at", "updated_at"])


def _cleanup_path(path: Path | None) -> None:
    if not path or not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    path.unlink(missing_ok=True)
    parent = path.parent
    media_root = Path(settings.MEDIA_ROOT)
    while parent != media_root and parent.exists():
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def _refresh_batch_async(clip: Clip) -> None:
    if clip.upload_batch_id:
        refresh_upload_batch_status.delay(clip.upload_batch_id)


def _set_job_progress(job: BackgroundJob | None, *, progress_percent: int, message: str | None = None) -> None:
    if not job:
        return

    progress_percent = max(0, min(100, progress_percent))
    update_fields: list[str] = ["updated_at"]

    if job.progress_percent != progress_percent:
        job.progress_percent = progress_percent
        update_fields.append("progress_percent")

    if message is not None and job.message != message:
        job.message = message
        update_fields.append("message")

    if len(update_fields) > 1:
        job.save(update_fields=update_fields)


def _make_stage_progress_callback(
    job: BackgroundJob | None,
    *,
    start_percent: int,
    end_percent: int,
    message: str,
):
    last_value = job.progress_percent if job else -1

    def callback(stage_percent: int) -> None:
        nonlocal last_value
        bounded = max(0, min(100, stage_percent))
        mapped = start_percent + ((end_percent - start_percent) * bounded // 100)
        if mapped <= last_value:
            return
        last_value = mapped
        _set_job_progress(job, progress_percent=mapped, message=message)

    return callback


@shared_task(**_clip_task_kwargs("clip_extract"))
def extract_clip(self, clip_id: int):
    try:
        clip = Clip.objects.select_related("master_video").get(id=clip_id)
    except Clip.DoesNotExist:
        return

    if clip.source_type != ClipSourceType.EXTRACTED:
        _mark_clip_failed(clip, _get_related_job(clip), "extract_clip task can only process extracted clips.")
        _refresh_batch_async(clip)
        return

    job = _get_related_job(clip)
    now = timezone.now()

    master_video = clip.master_video
    source_file = Path(master_video.video_file.path) if (master_video and master_video.video_file) else None
    if not source_file or not source_file.exists():
        _mark_clip_failed(clip, job, "Master video source file is missing.")
        _refresh_batch_async(clip)
        return

    clip.file_status = ProcessingState.PROCESSING
    clip.file_error_message = ""
    clip.save(update_fields=["file_status", "file_error_message", "updated_at", "extraction_status", "extraction_error_message"])

    extract_progress = None
    hls_progress = None
    if job:
        job.status = BackgroundJobState.PROCESSING
        if not job.started_at:
            job.started_at = now
        job.message = "Extracting clip with ffmpeg"
        job.error_message = ""
        job.progress_percent = 10
        job.celery_task_id = self.request.id or job.celery_task_id
        job.save(
            update_fields=[
                "status",
                "started_at",
                "message",
                "error_message",
                "progress_percent",
                "celery_task_id",
                "updated_at",
            ]
        )
        extract_progress = _make_stage_progress_callback(
            job,
            start_percent=10,
            end_percent=70,
            message="Extracting clip with ffmpeg",
        )
        hls_progress = _make_stage_progress_callback(
            job,
            start_percent=70,
            end_percent=95,
            message="Packaging clip for playback",
        )

    clip_dir = Path(settings.MEDIA_ROOT) / "clips" / f"user_{clip.owner_id}" / str(clip.id)
    clip_output = clip_dir / _build_clip_output_filename(clip)
    thumb_output = Path(settings.MEDIA_ROOT) / "thumbnails" / f"clip-{clip.id}-{uuid4().hex}.jpg"
    hls_output_dir = Path(settings.MEDIA_ROOT) / "clips" / "hls" / f"user_{clip.owner_id}" / str(clip.id)
    service = FfmpegService()

    try:
        result = service.extract_clip(
            source_path=source_file,
            output_path=clip_output,
            thumbnail_path=thumb_output,
            start_seconds=clip.start_time_seconds,
            end_seconds=clip.end_time_seconds,
            timeout=settings.FFMPEG_DEFAULT_TIMEOUT,
            progress_callback=extract_progress,
        )
        _set_job_progress(job, progress_percent=70, message="Packaging clip for playback")
        hls_result = service.generate_hls(
            source_path=clip_output,
            output_dir=hls_output_dir,
            timeout=settings.FFMPEG_HLS_TIMEOUT,
            progress_callback=hls_progress,
            expected_duration_seconds=clip.duration_seconds or (clip.end_time_seconds - clip.start_time_seconds),
        )
    except SoftTimeLimitExceeded:
        _cleanup_path(clip_output)
        _cleanup_path(thumb_output)
        _cleanup_path(hls_output_dir)
        _mark_clip_failed(clip, job, "Clip processing exceeded the soft time limit and was cleaned up.")
        _refresh_batch_async(clip)
        return
    except FfmpegPermanentError as exc:
        _cleanup_path(clip_output)
        _cleanup_path(thumb_output)
        _cleanup_path(hls_output_dir)
        _mark_clip_failed(clip, job, str(exc))
        _refresh_batch_async(clip)
        return
    except FfmpegTransientError as exc:
        _cleanup_path(clip_output)
        _cleanup_path(thumb_output)
        _cleanup_path(hls_output_dir)
        if self.request.retries < CLIP_RETRY_LIMIT:
            clip.file_status = ProcessingState.QUEUED
            clip.file_error_message = ""
            clip.save(update_fields=["file_status", "file_error_message", "updated_at", "extraction_status", "extraction_error_message"])
            if job:
                job.status = BackgroundJobState.QUEUED
                job.message = "Transient ffmpeg error. Retrying extraction."
                job.error_message = str(exc)
                job.progress_percent = 0
                job.save(update_fields=["status", "message", "error_message", "progress_percent", "updated_at"])
            raise self.retry(exc=exc, countdown=CLIP_RETRY_DELAY_SECONDS)

        _mark_clip_failed(clip, job, str(exc))
        _refresh_batch_async(clip)
        return
    except Exception as exc:  # noqa: BLE001
        _cleanup_path(clip_output)
        _cleanup_path(thumb_output)
        _cleanup_path(hls_output_dir)
        _mark_clip_failed(clip, job, str(exc))
        _refresh_batch_async(clip)
        return

    clip.clip_file.name = str(result.clip_output_path.relative_to(settings.MEDIA_ROOT))
    clip.hls_manifest_file.name = str(hls_result.manifest_path.relative_to(settings.MEDIA_ROOT))
    clip.thumbnail_file.name = str(result.thumbnail_output_path.relative_to(settings.MEDIA_ROOT))
    clip.original_filename = result.clip_output_path.name
    clip.extracted_at = timezone.now()
    clip.file_status = ProcessingState.READY
    clip.file_error_message = ""
    clip.save(
        update_fields=[
            "clip_file",
            "hls_manifest_file",
            "thumbnail_file",
            "original_filename",
            "extracted_at",
            "file_status",
            "file_error_message",
            "updated_at",
            "extraction_status",
            "extraction_error_message",
        ]
    )

    if job:
        job.status = BackgroundJobState.SUCCESS
        job.progress_percent = 100
        job.message = "Clip extraction completed"
        job.error_message = ""
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "progress_percent", "message", "error_message", "finished_at", "updated_at"])

    _refresh_batch_async(clip)


@shared_task(**_clip_task_kwargs("clip_upload_process"))
def process_uploaded_clip(self, clip_id: int):
    try:
        clip = Clip.objects.select_related("upload_batch").get(id=clip_id)
    except Clip.DoesNotExist:
        return

    if clip.source_type != ClipSourceType.UPLOADED:
        _mark_clip_failed(clip, _get_related_job(clip), "process_uploaded_clip task can only process uploaded clips.")
        _refresh_batch_async(clip)
        return

    job = _get_related_job(clip)
    now = timezone.now()

    source_file = Path(clip.clip_file.path) if clip.clip_file else None
    if not source_file or not source_file.exists():
        _mark_clip_failed(clip, job, "Uploaded file is missing.")
        _refresh_batch_async(clip)
        return

    clip.file_status = ProcessingState.PROCESSING
    clip.file_error_message = ""
    clip.save(update_fields=["file_status", "file_error_message", "updated_at", "extraction_status", "extraction_error_message"])

    hls_progress = None
    if job:
        job.status = BackgroundJobState.PROCESSING
        if not job.started_at:
            job.started_at = now
        job.message = "Post-processing uploaded clip"
        job.error_message = ""
        job.progress_percent = 20
        job.celery_task_id = self.request.id or job.celery_task_id
        job.save(
            update_fields=[
                "status",
                "started_at",
                "message",
                "error_message",
                "progress_percent",
                "celery_task_id",
                "updated_at",
            ]
        )
        hls_progress = _make_stage_progress_callback(
            job,
            start_percent=30,
            end_percent=95,
            message="Packaging uploaded clip for playback",
        )

    service = FfmpegService()
    thumb_path = Path(settings.MEDIA_ROOT) / "thumbnails" / f"clip-{clip.id}-{uuid4().hex}.jpg"
    hls_output_dir = Path(settings.MEDIA_ROOT) / "clips" / "hls" / f"user_{clip.owner_id}" / str(clip.id)

    try:
        duration = service.probe_duration_seconds(source_file)
        _set_job_progress(job, progress_percent=25, message="Generating clip thumbnail")
        service.generate_thumbnail(
            source_file,
            thumb_path,
            duration / 2,
            timeout=settings.FFMPEG_DEFAULT_TIMEOUT,
        )
        _set_job_progress(job, progress_percent=30, message="Packaging uploaded clip for playback")
        hls_result = service.generate_hls(
            source_path=source_file,
            output_dir=hls_output_dir,
            timeout=settings.FFMPEG_HLS_TIMEOUT,
            progress_callback=hls_progress,
            expected_duration_seconds=duration,
        )
    except SoftTimeLimitExceeded:
        _cleanup_path(thumb_path)
        _cleanup_path(hls_output_dir)
        _mark_clip_failed(clip, job, "Uploaded clip processing exceeded the soft time limit and was cleaned up.")
        _refresh_batch_async(clip)
        return
    except FfmpegPermanentError as exc:
        _cleanup_path(thumb_path)
        _cleanup_path(hls_output_dir)
        _mark_clip_failed(clip, job, str(exc))
        _refresh_batch_async(clip)
        return
    except FfmpegTransientError as exc:
        _cleanup_path(thumb_path)
        _cleanup_path(hls_output_dir)
        if self.request.retries < CLIP_RETRY_LIMIT:
            clip.file_status = ProcessingState.QUEUED
            clip.file_error_message = ""
            clip.save(update_fields=["file_status", "file_error_message", "updated_at", "extraction_status", "extraction_error_message"])
            if job:
                job.status = BackgroundJobState.QUEUED
                job.message = "Transient ffmpeg/ffprobe error. Retrying uploaded clip processing."
                job.error_message = str(exc)
                job.progress_percent = 0
                job.save(update_fields=["status", "message", "error_message", "progress_percent", "updated_at"])
            raise self.retry(exc=exc, countdown=CLIP_RETRY_DELAY_SECONDS)

        _mark_clip_failed(clip, job, str(exc))
        _refresh_batch_async(clip)
        return
    except Exception as exc:  # noqa: BLE001
        _cleanup_path(thumb_path)
        _cleanup_path(hls_output_dir)
        _mark_clip_failed(clip, job, str(exc))
        _refresh_batch_async(clip)
        return

    guessed_mime = mimetypes.guess_type(source_file.name)[0] or ""
    clip.duration_seconds = duration
    clip.start_time_seconds = 0
    clip.end_time_seconds = duration
    clip.file_size_bytes = clip.file_size_bytes or source_file.stat().st_size
    clip.mime_type = clip.mime_type or guessed_mime
    clip.hls_manifest_file.name = str(hls_result.manifest_path.relative_to(settings.MEDIA_ROOT))
    clip.thumbnail_file.name = str(thumb_path.relative_to(settings.MEDIA_ROOT))
    clip.file_status = ProcessingState.READY
    clip.file_error_message = ""
    clip.save(
        update_fields=[
            "duration_seconds",
            "start_time_seconds",
            "end_time_seconds",
            "file_size_bytes",
            "mime_type",
            "hls_manifest_file",
            "thumbnail_file",
            "file_status",
            "file_error_message",
            "updated_at",
            "extraction_status",
            "extraction_error_message",
        ]
    )

    if job:
        job.status = BackgroundJobState.SUCCESS
        job.progress_percent = 100
        job.message = "Uploaded clip post-processing completed"
        job.error_message = ""
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "progress_percent", "message", "error_message", "finished_at", "updated_at"])

    _refresh_batch_async(clip)


@shared_task(bind=True)
def refresh_upload_batch_status(self, batch_id: int):
    try:
        batch = ClipUploadBatch.objects.get(id=batch_id)
    except ClipUploadBatch.DoesNotExist:
        return

    clips = batch.clips.all()
    total = clips.count()
    ready = clips.filter(file_status=ProcessingState.READY).count()
    failed = clips.filter(file_status=ProcessingState.FAILED).count()
    queued_or_processing = clips.filter(file_status__in=[ProcessingState.PENDING, ProcessingState.QUEUED, ProcessingState.PROCESSING]).count()

    batch.total_files = total
    batch.success_files = ready
    batch.failed_files = failed

    if total == 0:
        batch.status = ClipUploadBatchStatus.FAILED
    elif ready == total:
        batch.status = ClipUploadBatchStatus.COMPLETED
    elif failed == total:
        batch.status = ClipUploadBatchStatus.FAILED
    elif ready > 0 and failed > 0:
        batch.status = ClipUploadBatchStatus.PARTIAL_FAILED
    elif queued_or_processing > 0:
        batch.status = ClipUploadBatchStatus.PROCESSING
    else:
        batch.status = ClipUploadBatchStatus.PROCESSING

    batch.save(update_fields=["total_files", "success_files", "failed_files", "status", "updated_at"])
