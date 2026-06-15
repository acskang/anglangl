from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from django.utils import timezone

from core.models import BackgroundJobState, ProcessingState
from videos.models import MasterVideo
from workers.models import BackgroundJob, BackgroundJobType

STALE_PENDING_MASTER_VIDEO_TIMEOUT = timedelta(minutes=10)
STALE_PENDING_MASTER_VIDEO_ERROR = "Video processing was left pending without an active background job and was marked as failed."

# Backward-compatible aliases kept while older imports are updated.
STALE_PENDING_YOUTUBE_TIMEOUT = STALE_PENDING_MASTER_VIDEO_TIMEOUT
STALE_PENDING_YOUTUBE_ERROR = STALE_PENDING_MASTER_VIDEO_ERROR


def normalize_stale_pending_master_videos(*, video_ids: Iterable[int] | None = None) -> list[int]:
    cutoff = timezone.now() - STALE_PENDING_MASTER_VIDEO_TIMEOUT
    queryset = MasterVideo.objects.filter(
        download_status=ProcessingState.PENDING,
        updated_at__lt=cutoff,
    )

    if video_ids is not None:
        queryset = queryset.filter(id__in=list(video_ids))

    candidate_ids = list(queryset.values_list("id", flat=True))
    if not candidate_ids:
        return []

    active_job_video_ids = set(
        BackgroundJob.objects.filter(
            related_object_type="master_video",
            related_object_id__in=[str(video_id) for video_id in candidate_ids],
            job_type__in=[
                BackgroundJobType.YOUTUBE_DOWNLOAD,
                BackgroundJobType.MASTER_VIDEO_UPLOAD_PROCESS,
            ],
            status__in=[
                BackgroundJobState.PENDING,
                BackgroundJobState.QUEUED,
                BackgroundJobState.PROCESSING,
            ],
        ).values_list("related_object_id", flat=True)
    )

    stale_ids = [video_id for video_id in candidate_ids if str(video_id) not in active_job_video_ids]
    if not stale_ids:
        return []

    MasterVideo.objects.filter(id__in=stale_ids).update(
        download_status=ProcessingState.FAILED,
        download_error_message=STALE_PENDING_MASTER_VIDEO_ERROR,
        updated_at=timezone.now(),
    )
    return stale_ids


def normalize_stale_pending_youtube_videos(*, video_ids: Iterable[int] | None = None) -> list[int]:
    return normalize_stale_pending_master_videos(video_ids=video_ids)
