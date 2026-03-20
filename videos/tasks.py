import shutil
from pathlib import Path

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone

from clips.services.ffmpeg import FfmpegPermanentError, FfmpegService, FfmpegTransientError
from core.models import BackgroundJobState, ProcessingState
from videos.models import MasterVideo, MasterVideoSourceType
from videos.services.ytdlp import YtDlpPermanentError, YtDlpService, YtDlpTransientError
from workers.models import BackgroundJob, BackgroundJobType


TRANSIENT_RETRY_LIMIT = 3
TRANSIENT_RETRY_DELAY_SECONDS = 60


def _video_task_kwargs(queue: str) -> dict[str, object]:
    return {
        "bind": True,
        "queue": queue,
        "soft_time_limit": settings.CELERY_FFMPEG_SOFT_TIME_LIMIT,
        "time_limit": settings.CELERY_FFMPEG_TIME_LIMIT,
    }


def _get_related_job(master_video: MasterVideo, *job_types: str) -> BackgroundJob | None:
    if not job_types:
        job_types = (
            BackgroundJobType.YOUTUBE_DOWNLOAD,
            BackgroundJobType.MASTER_VIDEO_UPLOAD_PROCESS,
        )
    return (
        BackgroundJob.objects.filter(
            related_object_type="master_video",
            related_object_id=str(master_video.id),
            job_type__in=job_types,
        )
        .order_by("-created_at")
        .first()
    )


def _mark_failed(video: MasterVideo, job: BackgroundJob | None, error_message: str) -> None:
    video.download_status = ProcessingState.FAILED
    video.download_error_message = error_message
    video.save(update_fields=["download_status", "download_error_message", "updated_at"])

    if job:
        job.status = BackgroundJobState.FAILED
        job.error_message = error_message
        job.message = "Download failed"
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


@shared_task(**_video_task_kwargs("youtube_download"))
def download_youtube_video(self, master_video_id: int):
    try:
        video = MasterVideo.objects.get(id=master_video_id)
    except MasterVideo.DoesNotExist:
        return

    job = _get_related_job(video)
    now = timezone.now()

    if video.source_type != MasterVideoSourceType.YOUTUBE:
        _mark_failed(video, job, "Only YouTube videos can be processed by the download worker.")
        return

    video.download_status = ProcessingState.PROCESSING
    video.download_error_message = ""
    video.save(update_fields=["download_status", "download_error_message", "updated_at"])

    hls_progress = None
    if job:
        job.status = BackgroundJobState.PROCESSING
        if not job.started_at:
            job.started_at = now
        job.message = "Downloading video with yt-dlp"
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
        hls_progress = _make_stage_progress_callback(
            job,
            start_percent=55,
            end_percent=95,
            message="Packaging downloaded video for playback",
        )

    service = YtDlpService()
    ffmpeg_service = FfmpegService()
    destination_dir = Path(settings.MEDIA_ROOT) / "master_videos" / f"user_{video.owner_id}" / str(video.id)
    hls_output_dir = Path(settings.MEDIA_ROOT) / "master_videos" / "hls" / f"user_{video.owner_id}" / str(video.id)

    try:
        result = service.download_with_metadata(video.youtube_url, destination_dir)
        _set_job_progress(job, progress_percent=55, message="Packaging downloaded video for playback")
        hls_result = ffmpeg_service.generate_hls(
            source_path=result.output_path,
            output_dir=hls_output_dir,
            timeout=settings.FFMPEG_HLS_TIMEOUT,
            progress_callback=hls_progress,
            expected_duration_seconds=result.duration_seconds,
        )
    except SoftTimeLimitExceeded:
        _cleanup_path(hls_output_dir)
        _mark_failed(video, job, "Video processing exceeded the soft time limit and was cleaned up.")
        return
    except YtDlpPermanentError as exc:
        _mark_failed(video, job, str(exc))
        return
    except YtDlpTransientError as exc:
        _cleanup_path(hls_output_dir)
        if self.request.retries < TRANSIENT_RETRY_LIMIT:
            if job:
                job.status = BackgroundJobState.QUEUED
                job.message = "Transient error. Retrying download."
                job.error_message = str(exc)
                job.progress_percent = 0
                job.save(update_fields=["status", "message", "error_message", "progress_percent", "updated_at"])
            video.download_status = ProcessingState.QUEUED
            video.download_error_message = ""
            video.save(update_fields=["download_status", "download_error_message", "updated_at"])
            raise self.retry(exc=exc, countdown=TRANSIENT_RETRY_DELAY_SECONDS)

        _mark_failed(video, job, str(exc))
        return
    except (FfmpegPermanentError, FfmpegTransientError) as exc:
        _cleanup_path(hls_output_dir)
        _mark_failed(video, job, f"HLS generation failed: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        _cleanup_path(hls_output_dir)
        _mark_failed(video, job, f"HLS generation failed: {exc}")
        return

    relative_path = result.output_path.relative_to(settings.MEDIA_ROOT)
    hls_relative_path = hls_result.manifest_path.relative_to(settings.MEDIA_ROOT)
    video.title = result.title or video.title
    video.description = result.description
    video.thumbnail_url = result.thumbnail_url
    video.duration_seconds = result.duration_seconds
    video.file_size_bytes = result.file_size_bytes or result.output_path.stat().st_size
    video.video_file.name = str(relative_path)
    video.hls_manifest_file.name = str(hls_relative_path)
    video.downloaded_at = timezone.now()
    video.download_status = ProcessingState.READY
    video.download_error_message = ""
    video.save(
        update_fields=[
            "title",
            "description",
            "thumbnail_url",
            "duration_seconds",
            "file_size_bytes",
            "video_file",
            "hls_manifest_file",
            "downloaded_at",
            "download_status",
            "download_error_message",
            "updated_at",
        ]
    )

    if job:
        job.status = BackgroundJobState.SUCCESS
        job.progress_percent = 100
        job.message = "Download completed"
        job.error_message = ""
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "progress_percent", "message", "error_message", "finished_at", "updated_at"])


@shared_task(**_video_task_kwargs("default"))
def process_uploaded_master_video(self, master_video_id: int):
    try:
        video = MasterVideo.objects.get(id=master_video_id)
    except MasterVideo.DoesNotExist:
        return

    job = _get_related_job(video, BackgroundJobType.MASTER_VIDEO_UPLOAD_PROCESS)
    now = timezone.now()

    if video.source_type != MasterVideoSourceType.UPLOAD:
        _mark_failed(video, job, "Only uploaded videos can be processed by the upload worker.")
        return

    source_file = Path(video.video_file.path) if video.video_file else None
    if not source_file or not source_file.exists():
        _mark_failed(video, job, "Uploaded video file is missing.")
        return

    video.download_status = ProcessingState.PROCESSING
    video.download_error_message = ""
    video.save(update_fields=["download_status", "download_error_message", "updated_at"])

    hls_progress = None
    if job:
        job.status = BackgroundJobState.PROCESSING
        if not job.started_at:
            job.started_at = now
        job.message = "Preparing uploaded video for playback"
        job.error_message = ""
        job.progress_percent = 15
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
            start_percent=20,
            end_percent=95,
            message="Packaging uploaded video for playback",
        )

    ffmpeg_service = FfmpegService()
    hls_output_dir = Path(settings.MEDIA_ROOT) / "master_videos" / "hls" / f"user_{video.owner_id}" / str(video.id)

    try:
        duration = ffmpeg_service.probe_duration_seconds(source_file)
        _set_job_progress(job, progress_percent=20, message="Packaging uploaded video for playback")
        hls_result = ffmpeg_service.generate_hls(
            source_path=source_file,
            output_dir=hls_output_dir,
            timeout=settings.FFMPEG_HLS_TIMEOUT,
            progress_callback=hls_progress,
            expected_duration_seconds=duration,
        )
    except SoftTimeLimitExceeded:
        _cleanup_path(hls_output_dir)
        _mark_failed(video, job, "Uploaded video processing exceeded the soft time limit and was cleaned up.")
        return
    except (FfmpegPermanentError, FfmpegTransientError) as exc:
        _cleanup_path(hls_output_dir)
        _mark_failed(video, job, f"Uploaded video processing failed: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        _cleanup_path(hls_output_dir)
        _mark_failed(video, job, f"Uploaded video processing failed: {exc}")
        return

    video.duration_seconds = duration
    video.file_size_bytes = video.file_size_bytes or source_file.stat().st_size
    video.hls_manifest_file.name = str(hls_result.manifest_path.relative_to(settings.MEDIA_ROOT))
    video.downloaded_at = timezone.now()
    video.download_status = ProcessingState.READY
    video.download_error_message = ""
    video.save(
        update_fields=[
            "duration_seconds",
            "file_size_bytes",
            "hls_manifest_file",
            "downloaded_at",
            "download_status",
            "download_error_message",
            "updated_at",
        ]
    )

    if job:
        job.status = BackgroundJobState.SUCCESS
        job.progress_percent = 100
        job.message = "Uploaded video processing completed"
        job.error_message = ""
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "progress_percent", "message", "error_message", "finished_at", "updated_at"])
