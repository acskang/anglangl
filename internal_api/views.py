import logging

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from clips.models import Clip, ClipUploadBatch
from clips.services.playback_links import generate_clip_playback_link, validate_clip_playback_token
from internal_api.auth import require_internal_user
from internal_api.serializers import clip_detail, clip_summary, master_video_summary, upload_batch_detail
from internal_api.utils import parse_bool_param, parse_int_param, safe_text
from study.models import ClipStudyHistory
from videos.models import MasterVideo

logger = logging.getLogger(__name__)


@require_GET
def clips_search(request: HttpRequest):
    user, error = require_internal_user(request)
    if error:
        return error

    query = safe_text(request.GET.get("query"))
    visibility = safe_text(request.GET.get("visibility")).lower() or "all"
    limit = parse_int_param(request, "limit", 20, min_value=1, max_value=100)
    offset = parse_int_param(request, "offset", 0, min_value=0, max_value=100000)

    clips = Clip.objects.select_related("owner", "master_video", "upload_batch").filter(is_active=True)

    if visibility == "public":
        clips = clips.filter(is_public=True)
    elif visibility == "private":
        clips = clips.filter(owner=user, is_public=False)
    elif visibility == "mine":
        clips = clips.filter(owner=user)
    else:
        clips = clips.filter(Q(owner=user) | Q(is_public=True))

    if query:
        clips = clips.filter(Q(title__icontains=query) | Q(description__icontains=query))

    total = clips.count()
    rows = clips.order_by("-created_at")[offset : offset + limit]

    return JsonResponse(
        {
            "items": [clip_summary(request, clip) for clip in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )


@require_GET
def clip_detail_view(request: HttpRequest, clip_id: int):
    user, error = require_internal_user(request)
    if error:
        return error

    clip = (
        Clip.objects.select_related("owner", "master_video", "upload_batch")
        .filter(id=clip_id, is_active=True)
        .first()
    )
    if not clip:
        return JsonResponse({"error": "not_found"}, status=404)

    if clip.owner_id != user.id and not clip.is_public:
        return JsonResponse({"error": "not_found"}, status=404)

    return JsonResponse(clip_detail(request, clip))


@csrf_exempt
@require_POST
def clip_playback_link(request: HttpRequest, clip_id: int):
    user, error = require_internal_user(request)
    if error:
        return error

    clip = Clip.objects.select_related("owner").filter(id=clip_id, is_active=True).first()
    if not clip:
        return JsonResponse({"error": "not_found"}, status=404)

    try:
        payload = generate_clip_playback_link(request, clip=clip, user=user)
    except PermissionDenied:
        return JsonResponse({"error": "forbidden"}, status=403)
    except Exception:  # noqa: BLE001
        logger.exception("playback_link_generation_failed", extra={"clip_id": clip_id, "user_id": user.id})
        return JsonResponse({"error": "playback_unavailable"}, status=503)

    return JsonResponse(payload)


@require_GET
def clip_playback_file(request: HttpRequest, clip_id: int):
    token = safe_text(request.GET.get("token"))
    if not token:
        return JsonResponse({"error": "missing_token"}, status=400)

    try:
        clip = validate_clip_playback_token(clip_id=clip_id, token=token)
    except Exception:  # noqa: BLE001
        return JsonResponse({"error": "invalid_or_expired_token"}, status=403)

    content_type = clip.mime_type or "video/mp4"
    response = FileResponse(clip.clip_file.open("rb"), content_type=content_type)
    response["Content-Disposition"] = f'inline; filename="clip-{clip.id}.mp4"'
    return response


@require_GET
def study_recent(request: HttpRequest):
    user, error = require_internal_user(request)
    if error:
        return error

    limit = parse_int_param(request, "limit", 10, min_value=1, max_value=100)

    histories = (
        ClipStudyHistory.objects.select_related("clip", "clip__owner", "clip__master_video", "clip__upload_batch")
        .filter(user=user, clip__is_active=True)
        .order_by("-last_studied_at", "-updated_at")[:limit]
    )

    items = []
    for history in histories:
        clip = history.clip
        if clip.owner_id != user.id and not clip.is_public:
            continue
        items.append(
            {
                "study": {
                    "study_count": history.study_count,
                    "total_repeat_count": history.total_repeat_count,
                    "total_watch_seconds": history.total_watch_seconds,
                    "last_studied_at": history.last_studied_at.isoformat() if history.last_studied_at else None,
                },
                "clip": clip_summary(request, clip),
            }
        )

    return JsonResponse({"items": items, "limit": limit})


@require_GET
def videos_search(request: HttpRequest):
    user, error = require_internal_user(request)
    if error:
        return error

    query = safe_text(request.GET.get("query"))
    mine_only = parse_bool_param(request, "mine_only", default=True)
    limit = parse_int_param(request, "limit", 20, min_value=1, max_value=100)
    offset = parse_int_param(request, "offset", 0, min_value=0, max_value=100000)

    videos = MasterVideo.objects.filter(is_active=True)
    if mine_only:
        videos = videos.filter(owner=user)
    else:
        videos = videos.filter(owner=user)

    if query:
        videos = videos.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(youtube_video_id__icontains=query))

    total = videos.count()
    rows = videos.select_related("owner").order_by("-created_at")[offset : offset + limit]

    return JsonResponse(
        {
            "items": [master_video_summary(request, video) for video in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )


@require_GET
def video_detail(request: HttpRequest, video_id: int):
    user, error = require_internal_user(request)
    if error:
        return error

    video = MasterVideo.objects.filter(id=video_id, owner=user, is_active=True).first()
    if not video:
        return JsonResponse({"error": "not_found"}, status=404)

    payload = master_video_summary(request, video)
    payload["clip_count"] = video.clips.filter(is_active=True).count()
    return JsonResponse(payload)


@require_GET
def upload_batch_detail_view(request: HttpRequest, batch_id: int):
    user, error = require_internal_user(request)
    if error:
        return error

    batch = ClipUploadBatch.objects.filter(id=batch_id, owner=user).first()
    if not batch:
        return JsonResponse({"error": "not_found"}, status=404)

    payload = upload_batch_detail(request, batch)
    payload["clips"] = [
        {
            "id": clip.id,
            "title": clip.title,
            "file_status": clip.file_status,
            "is_public": clip.is_public,
            "duration_seconds": clip.duration_seconds,
        }
        for clip in batch.clips.filter(is_active=True).order_by("-created_at")[:100]
    ]
    return JsonResponse(payload)
