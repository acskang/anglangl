from django.http import HttpRequest

from clips.models import Clip, ClipUploadBatch
from videos.models import MasterVideo


def _abs_uri(request: HttpRequest, maybe_relative: str) -> str:
    if not maybe_relative:
        return ""
    if maybe_relative.startswith("http://") or maybe_relative.startswith("https://"):
        return maybe_relative
    return request.build_absolute_uri(maybe_relative)


def _owner_display(user) -> str:
    full_name = (user.get_full_name() or "").strip()
    if full_name:
        return full_name
    return user.get_username()


def clip_summary(request: HttpRequest, clip: Clip) -> dict:
    thumbnail_url = ""
    if clip.thumbnail_file:
        thumbnail_url = _abs_uri(request, clip.thumbnail_file.url)
    elif clip.master_video and clip.master_video.thumbnail_url:
        thumbnail_url = _abs_uri(request, clip.master_video.thumbnail_url)

    return {
        "id": clip.id,
        "title": clip.title,
        "description": clip.description,
        "duration_seconds": clip.duration_seconds,
        "source_type": clip.source_type,
        "is_public": clip.is_public,
        "thumbnail_url": thumbnail_url,
    }


def clip_detail(request: HttpRequest, clip: Clip) -> dict:
    payload = clip_summary(request, clip)
    payload.update(
        {
            "owner_display": _owner_display(clip.owner),
            "master_video_summary": None,
            "upload_batch_summary": None,
        }
    )

    if clip.master_video:
        payload["master_video_summary"] = {
            "id": clip.master_video.id,
            "title": clip.master_video.title,
            "youtube_video_id": clip.master_video.youtube_video_id,
            "thumbnail_url": _abs_uri(request, clip.master_video.thumbnail_url),
        }

    if clip.upload_batch:
        payload["upload_batch_summary"] = {
            "id": clip.upload_batch.id,
            "title": clip.upload_batch.title,
            "status": clip.upload_batch.status,
        }

    return payload


def master_video_summary(request: HttpRequest, video: MasterVideo) -> dict:
    return {
        "id": video.id,
        "title": video.title,
        "description": video.description,
        "youtube_video_id": video.youtube_video_id,
        "youtube_url": video.youtube_url,
        "duration_seconds": video.duration_seconds,
        "thumbnail_url": _abs_uri(request, video.thumbnail_url),
        "download_status": video.download_status,
    }


def upload_batch_detail(_: HttpRequest, batch: ClipUploadBatch) -> dict:
    return {
        "id": batch.id,
        "title": batch.title,
        "description": batch.description,
        "status": batch.status,
        "total_files": batch.total_files,
        "success_files": batch.success_files,
        "failed_files": batch.failed_files,
        "created_at": batch.created_at.isoformat(),
        "updated_at": batch.updated_at.isoformat(),
    }
