import json

import requests
from celery import shared_task
from django.utils import timezone

from core.models import BackgroundJobState
from workers.models import BackgroundJob, BackgroundJobType

from . import extractor
from .models import Video


def _get_related_job(video: Video) -> BackgroundJob | None:
    return (
        BackgroundJob.objects.filter(
            related_object_type="drama_video",
            related_object_id=str(video.id),
            job_type=BackgroundJobType.DRAMA_VIDEO_EXTRACT,
        )
        .order_by("-created_at")
        .first()
    )


def _set_job_progress(job: BackgroundJob | None, *, progress_percent: int, message: str | None = None) -> None:
    if not job:
        return
    progress_percent = max(0, min(100, progress_percent))
    update_fields = ["updated_at"]
    if job.progress_percent != progress_percent:
        job.progress_percent = progress_percent
        update_fields.append("progress_percent")
    if message is not None and job.message != message:
        job.message = message
        update_fields.append("message")
    if len(update_fields) > 1:
        job.save(update_fields=update_fields)


def _mark_failed(video: Video, job: BackgroundJob | None, error_message: str) -> None:
    video.status = "error"
    video.error_msg = error_message
    video.save(update_fields=["status", "error_msg", "updated_at"])
    if job:
        job.status = BackgroundJobState.FAILED
        job.error_message = error_message
        job.message = "Drama extraction failed"
        job.progress_percent = 100
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "message", "progress_percent", "finished_at", "updated_at"])


def _friendly_drama_error_message(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.lower()
    if isinstance(exc, requests.Timeout):
        return "외부 소스 응답 시간이 너무 길어 추출이 중단되었습니다. 잠시 후 재시도하세요."
    if isinstance(exc, requests.RequestException):
        return f"외부 소스 네트워크 오류로 추출에 실패했습니다: {message}"
    if "m3u8 url" in lowered or "사이트 구조가 변경" in message:
        return "플레이어 구조가 바뀌어 m3u8 추출에 실패했습니다. 소스 사이트 구조를 확인해야 합니다."
    if "subtitle" in lowered:
        return f"자막 메타데이터를 읽는 중 오류가 발생했습니다: {message}"
    return message


@shared_task(bind=True, queue="default")
def extract_drama_video(self, video_id: int):
    try:
        video = Video.objects.get(pk=video_id)
    except Video.DoesNotExist:
        return

    job = _get_related_job(video)
    if job and job.status == BackgroundJobState.CANCELED:
        video.status = "canceled"
        video.error_msg = ""
        video.save(update_fields=["status", "error_msg", "updated_at"])
        return
    video.status = "fetching"
    video.error_msg = ""
    video.save(update_fields=["status", "error_msg", "updated_at"])

    if job:
        job.status = BackgroundJobState.PROCESSING
        job.error_message = ""
        job.message = "Analyzing source page"
        job.progress_percent = 15
        job.celery_task_id = self.request.id or job.celery_task_id
        if not job.started_at:
            job.started_at = timezone.now()
        job.save(
            update_fields=[
                "status",
                "error_message",
                "message",
                "progress_percent",
                "celery_task_id",
                "started_at",
                "updated_at",
            ]
        )

    try:
        _set_job_progress(job, progress_percent=45, message="Extracting player and subtitle metadata")
        info = extractor.extract(video.source_url)
    except Exception as exc:  # noqa: BLE001
        _mark_failed(video, job, _friendly_drama_error_message(exc))
        return

    video.player_url = info.get("player_url", "")
    video.m3u8_url = info.get("m3u8_url", "")
    video.thumbnail = info.get("thumbnail", "")
    video.duration = info.get("duration", 0)
    video.subtitle_tracks = json.dumps(info.get("subtitles", []), ensure_ascii=False)
    video.status = "ready"
    video.error_msg = ""
    if not video.title or video.title == "추출 중...":
        video.title = video.source_url.rstrip("/").split("/")[-1]
    video.save(
        update_fields=[
            "player_url",
            "m3u8_url",
            "thumbnail",
            "duration",
            "subtitle_tracks",
            "status",
            "error_msg",
            "title",
            "updated_at",
        ]
    )

    if job:
        job.status = BackgroundJobState.SUCCESS
        job.message = "Drama extraction completed"
        job.error_message = ""
        job.progress_percent = 100
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "message", "error_message", "progress_percent", "finished_at", "updated_at"])
