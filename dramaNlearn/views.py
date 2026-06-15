import json
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode, urlparse
from uuid import uuid4

import requests
from celery import current_app
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import F, Prefetch
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import get_valid_filename
from django.core.validators import URLValidator
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from PIL import Image, ImageOps

from core.models import BackgroundJobState, ImdbDramaEpisodeCache, ImdbDramaSeriesCache
from workers.models import BackgroundJob, BackgroundJobType
from videos.models import MasterVideo, MasterVideoSourceType
from .forms import ThumbnailAssetForm
from .models import ThumbnailAsset, Video
from .services.imdb_lookup import ImdbDramaLookupError, normalize_imdb_id, search_imdb_drama_catalog
from .tasks import extract_drama_video


THUMBNAIL_OUTPUT_SIZE = (960, 540)
THUMBNAIL_BASE_QUALITY = 75
THUMBNAIL_TARGET_MAX_BYTES = 250 * 1024


def _build_thumbnail_content(uploaded_file, fallback_name: str) -> ContentFile:
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
        selected_quality = THUMBNAIL_BASE_QUALITY
        for quality in (75, 72, 68, 65, 60):
            output.seek(0)
            output.truncate(0)
            fitted.save(output, format="WEBP", quality=quality, method=6)
            data = output.getvalue()
            selected_bytes = data
            selected_quality = quality
            if len(data) <= THUMBNAIL_TARGET_MAX_BYTES:
                break

        final_name = f"{Path(fallback_name).stem or 'thumbnail'}.webp"
        content = ContentFile(selected_bytes, name=final_name)
        content.thumbnail_quality = selected_quality
        return content


def json_login_required():
    return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.', 'login_required': True}, status=401)


def _expects_json_response(request) -> bool:
    accept = request.headers.get("Accept", "")
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in accept


def _safe_next_url(request, fallback: str) -> str:
    next_url = (request.POST.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback


def _is_supported_send2video_url(source_url: str) -> bool:
    parsed = urlparse(source_url.strip())
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").strip()
    if "send2video.com" not in host:
        return False
    return bool(path and path != "/")


def _extract_video_for_user(*, owner, source_url: str, title: str = "", require_title: bool = False):
    source_url = (source_url or "").strip()
    title = (title or "").strip()

    if not source_url:
        return {'ok': False, 'error': 'URL을 입력해주세요.', 'url': source_url}
    if require_title and not title:
        return {'ok': False, 'error': '제목을 입력해주세요.', 'url': source_url}
    if not _is_supported_send2video_url(source_url):
        return {'ok': False, 'error': 'send2video 상세 페이지 URL을 입력해주세요.', 'url': source_url}

    existing = Video.objects.filter(source_url=source_url).first()
    if existing:
        return {
            'ok': True,
            'video_id': existing.id,
            'message': '이미 등록된 영상입니다.',
            'redirect': reverse('dramaNlearn:player', args=[existing.id]),
            'url': source_url,
            'existing': True,
        }

    video = Video.objects.create(
        title=title or '추출 중...',
        source_url=source_url,
        owner=owner,
        status='queued',
    )

    ok, error = _enqueue_drama_extract(video=video, user=owner, message="Queued for drama extraction")
    if ok:
        return {
            'ok': True,
            'video_id': video.id,
            'redirect': reverse('dramaNlearn:url_manage'),
            'url': source_url,
            'title': title,
            'existing': False,
            'queued': True,
        }
    return {'ok': False, 'error': error, 'video_id': video.id, 'url': source_url, 'title': title}


def _get_video_job(video: Video) -> BackgroundJob | None:
    return (
        BackgroundJob.objects.filter(
            related_object_type="drama_video",
            related_object_id=str(video.id),
            job_type=BackgroundJobType.DRAMA_VIDEO_EXTRACT,
        )
        .order_by("-created_at")
        .first()
    )


def _enqueue_drama_extract(*, video: Video, user, message: str) -> tuple[bool, str]:
    video.status = 'queued'
    video.error_msg = ''
    video.save(update_fields=['status', 'error_msg', 'updated_at'])
    try:
        job = BackgroundJob.objects.create(
            user=user,
            job_type=BackgroundJobType.DRAMA_VIDEO_EXTRACT,
            related_object_type="drama_video",
            related_object_id=str(video.id),
            status=BackgroundJobState.QUEUED,
            progress_percent=0,
            message=message,
        )
        async_result = extract_drama_video.delay(video.id)
        job.celery_task_id = async_result.id or ""
        job.save(update_fields=["celery_task_id", "updated_at"])
        return True, ""
    except Exception as exc:  # noqa: BLE001
        video.status = 'error'
        video.error_msg = str(exc)
        video.save(update_fields=['status', 'error_msg', 'updated_at'])
        BackgroundJob.objects.create(
            user=user,
            job_type=BackgroundJobType.DRAMA_VIDEO_EXTRACT,
            related_object_type="drama_video",
            related_object_id=str(video.id),
            status=BackgroundJobState.FAILED,
            progress_percent=100,
            message="Failed to enqueue drama extraction",
            error_message=str(exc),
            finished_at=timezone.now(),
        )
        return False, str(exc)


def _sync_drama_master_video(video: Video) -> MasterVideo:
    bridge, _created = MasterVideo.objects.get_or_create(
        source_drama_video=video,
        defaults={
            "owner": video.owner,
            "source_type": MasterVideoSourceType.UPLOAD,
            "title": video.title or "Drama Source",
            "description": video.source_url,
            "thumbnail_url": video.thumbnail or "",
            "duration_seconds": int(round(video.duration or 0)) or None,
            "channel_name": "Drama",
            "remote_playback_url": video.m3u8_url or "",
            "download_status": "ready" if video.status == "ready" and video.m3u8_url else "pending",
            "download_error_message": video.error_msg or "",
        },
    )

    update_fields: list[str] = []
    expected_duration = int(round(video.duration or 0)) or None
    expected_status = "ready" if video.status == "ready" and video.m3u8_url else "failed" if video.status == "error" else "pending"
    expected_error = video.error_msg or ""
    field_updates = {
        "owner": video.owner,
        "source_type": MasterVideoSourceType.UPLOAD,
        "title": video.title or "Drama Source",
        "description": video.source_url,
        "thumbnail_url": video.thumbnail or "",
        "duration_seconds": expected_duration,
        "channel_name": "Drama",
        "remote_playback_url": video.m3u8_url or "",
        "download_status": expected_status,
        "download_error_message": expected_error,
    }
    for field_name, expected_value in field_updates.items():
        if getattr(bridge, field_name) != expected_value:
            setattr(bridge, field_name, expected_value)
            update_fields.append(field_name)

    if update_fields:
        update_fields.append("updated_at")
        bridge.save(update_fields=update_fields)
    return bridge


IMDB_SAVED_SORT_CHOICES = (
    ("manual", "직접 순서"),
    ("recent", "최근"),
    ("oldest", "오래된"),
    ("recent_played", "최근 재생"),
)


def _normalize_imdb_saved_sort(value: str) -> str:
    candidate = str(value or "").strip().lower()
    allowed_values = {item[0] for item in IMDB_SAVED_SORT_CHOICES}
    return candidate if candidate in allowed_values else "manual"


def _build_imdb_sort_url(*, query: str, saved_sort: str) -> str:
    params = {"saved_sort": saved_sort}
    if query:
        params["query"] = query
    return f"{reverse('dramaNlearn:imdb')}?{urlencode(params)}"


def _build_imdb_delete_return_url(*, saved_sort: str) -> str:
    if saved_sort == "manual":
        return reverse("dramaNlearn:imdb")
    return f"{reverse('dramaNlearn:imdb')}?{urlencode({'saved_sort': saved_sort})}"


def _build_imdb_player_open_url(imdb_id: str) -> str:
    return f"{reverse('player')}?{urlencode({'imdb_modal': '1', 'imdb_id': imdb_id})}"


def _home_imdb_series_queryset(*, saved_sort: str = "manual"):
    cached_episode_queryset = (
        ImdbDramaEpisodeCache.objects.exclude(stream_url="")
        .order_by("season_number", "episode_number")
    )
    queryset = (
        ImdbDramaSeriesCache.objects.prefetch_related(
            Prefetch("episodes", queryset=cached_episode_queryset)
        )
        .filter(episodes__stream_url__gt="")
        .distinct()
    )
    normalized_sort = _normalize_imdb_saved_sort(saved_sort)
    if normalized_sort == "manual":
        return queryset.order_by("manual_order", "-updated_at", "title", "imdb_id")
    if normalized_sort == "oldest":
        return queryset.order_by("updated_at", "title", "imdb_id")
    if normalized_sort == "recent_played":
        return queryset.order_by(
            F("last_played_at").desc(nulls_last=True),
            "-updated_at",
            "title",
            "imdb_id",
        )
    return queryset.order_by("-updated_at", "title", "imdb_id")


def _build_home_video_card(video: Video, *, viewer_id: int | None) -> dict:
    play_url = reverse("dramaNlearn:player", args=[video.id]) if video.status == "ready" else ""
    can_manage = viewer_id is not None and video.owner_id == viewer_id
    delete_requires_login = viewer_id is None
    if viewer_id is None:
        delete_disabled_reason = "로그인 후 삭제할 수 있습니다."
    elif not can_manage:
        delete_disabled_reason = "내가 등록한 영상만 삭제할 수 있습니다."
    else:
        delete_disabled_reason = ""
    return {
        "kind": "video",
        "status": video.status,
        "sort_created": int(video.created_at.timestamp()),
        "sort_views": video.view_count,
        "click_url": play_url,
        "play_url": play_url,
        "thumbnail_url": video.thumbnail,
        "duration_text": video.duration_str(),
        "title": video.title,
        "display_date": video.created_at,
        "view_count": video.view_count,
        "owner_label": f"@{video.owner.username}" if video.owner else "공유 영상",
        "error_message": video.error_msg,
        "can_manage": can_manage,
        "can_delete": can_manage,
        "delete_requires_login": delete_requires_login,
        "delete_disabled_reason": delete_disabled_reason,
        "video_id": video.id,
        "delete_url": reverse("dramaNlearn:delete_video", args=[video.id]),
    }


def _build_home_imdb_card(series: ImdbDramaSeriesCache, *, viewer_id: int | None) -> dict:
    return {
        "kind": "imdb",
        "status": "ready",
        "sort_created": int(series.updated_at.timestamp()),
        "sort_views": 0,
        "click_url": series.home_player_url,
        "play_url": series.home_player_url,
        "thumbnail_url": series.poster_url,
        "title": series.title or series.imdb_id,
        "summary": series.summary,
        "display_date": series.updated_at,
        "imdb_id": series.imdb_id,
        "season_count": series.home_season_count,
        "episode_count": series.home_episode_count,
        "imdb_url": series.home_imdb_url,
        "can_delete": viewer_id is not None,
        "delete_requires_login": viewer_id is None,
        "delete_url": reverse("dramaNlearn:delete_imdb_series", args=[series.imdb_id]),
    }


def _build_imdb_browser_saved_card(series: ImdbDramaSeriesCache) -> dict:
    episode_rows = list(series.episodes.all())
    return {
        "imdb_id": series.imdb_id,
        "title": series.title or series.imdb_id,
        "poster_url": series.poster_url,
        "summary": series.summary,
        "season_count": len({row.season_number for row in episode_rows}),
        "episode_count": len(episode_rows),
        "last_played_at": series.last_played_at,
        "manual_order": series.manual_order,
        "query_url": f"{reverse('dramaNlearn:imdb')}?query={series.imdb_id}",
        "player_open_url": _build_imdb_player_open_url(series.imdb_id),
        "delete_url": reverse("dramaNlearn:delete_imdb_series", args=[series.imdb_id]),
    }


def home(request):
    videos = list(Video.objects.all())
    imdb_series_rows = list(_home_imdb_series_queryset(saved_sort="recent")[:12])
    for series in imdb_series_rows:
        episode_rows = list(series.episodes.all())
        series.home_episode_count = len(episode_rows)
        series.home_season_count = len({row.season_number for row in episode_rows})
        series.home_player_url = (
            f"{reverse('player')}?source=imdb&imdb_id={series.imdb_id}"
        )
        series.home_imdb_url = f"{reverse('dramaNlearn:imdb')}?query={series.imdb_id}"

    viewer_id = request.user.id if request.user.is_authenticated else None
    home_cards = [
        *[_build_home_video_card(video, viewer_id=viewer_id) for video in videos],
        *[_build_home_imdb_card(series, viewer_id=viewer_id) for series in imdb_series_rows],
    ]
    home_cards.sort(key=lambda card: (card["sort_created"], card["sort_views"]), reverse=True)

    return render(request, "dramaNlearn/home.html", {
        "home_cards": home_cards,
        "home_card_count": len(home_cards),
        "ready_count": sum(1 for card in home_cards if card["status"] == "ready"),
        "error_count": sum(1 for video in videos if video.status == "error"),
        "imdb_series_count": len(imdb_series_rows),
    })


def imdb_browser(request):
    query = (request.GET.get("query") or "").strip()
    saved_sort = _normalize_imdb_saved_sort(request.GET.get("saved_sort", "manual"))
    lookup = None
    error_message = ""
    saved_series_rows = list(_home_imdb_series_queryset(saved_sort=saved_sort)[:48])

    if query:
        try:
            lookup = search_imdb_drama_catalog(query)
        except ValueError as exc:
            error_message = str(exc)
        except ImdbDramaLookupError as exc:
            error_message = str(exc)
        except requests.RequestException as exc:
            error_message = f"외부 드라마 정보를 불러오지 못했습니다: {exc}"

    selected = lookup.get("selected") if lookup else None
    return render(
        request,
        "dramaNlearn/imdb.html",
        {
            "query": query,
            "results": lookup.get("results") if lookup else [],
            "saved_series": [_build_imdb_browser_saved_card(series) for series in saved_series_rows],
            "saved_sort": saved_sort,
            "saved_sort_options": [
                {
                    "value": value,
                    "label": label,
                    "url": _build_imdb_sort_url(query=query, saved_sort=value),
                    "active": value == saved_sort,
                }
                for value, label in IMDB_SAVED_SORT_CHOICES
            ],
            "saved_series_return_url": _build_imdb_delete_return_url(saved_sort=saved_sort),
            "can_delete_saved_series": request.user.is_authenticated,
            "can_reorder_saved_series": request.user.is_authenticated and saved_sort == "manual",
            "selected": selected,
            "selected_source": lookup.get("selected_source") if lookup else "",
            "error_message": error_message,
        },
    )


@require_POST
def reorder_imdb_series(request):
    if not request.user.is_authenticated:
        return json_login_required()

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "잘못된 요청입니다."}, status=400)

    ordered_ids = payload.get("imdb_ids")
    if not isinstance(ordered_ids, list) or not ordered_ids:
        return JsonResponse({"ok": False, "error": "정렬 대상이 없습니다."}, status=400)

    normalized_ids = []
    seen_ids = set()
    for item in ordered_ids:
        normalized_id = normalize_imdb_id(item)
        if not normalized_id or normalized_id in seen_ids:
            continue
        normalized_ids.append(normalized_id)
        seen_ids.add(normalized_id)

    if not normalized_ids:
        return JsonResponse({"ok": False, "error": "유효한 IMDb ID가 없습니다."}, status=400)

    series_rows = list(ImdbDramaSeriesCache.objects.filter(imdb_id__in=normalized_ids))
    series_by_id = {row.imdb_id: row for row in series_rows}
    if len(series_by_id) != len(normalized_ids):
        return JsonResponse({"ok": False, "error": "정렬 대상 중 일부를 찾지 못했습니다."}, status=400)

    with transaction.atomic():
        trailing_rows = list(
            ImdbDramaSeriesCache.objects.exclude(imdb_id__in=normalized_ids).order_by(
                "manual_order",
                "-updated_at",
                "title",
                "imdb_id",
            )
        )
        updated_rows = []
        next_order = 1
        for imdb_id in normalized_ids:
            row = series_by_id[imdb_id]
            row.manual_order = next_order
            updated_rows.append(row)
            next_order += 1
        for row in trailing_rows:
            row.manual_order = next_order
            updated_rows.append(row)
            next_order += 1
        ImdbDramaSeriesCache.objects.bulk_update(updated_rows, ["manual_order"])

    return JsonResponse({"ok": True, "count": len(normalized_ids)})


@require_POST
def delete_imdb_series(request, imdb_id):
    normalized_imdb_id = normalize_imdb_id(imdb_id)
    if not request.user.is_authenticated:
        return json_login_required()
    if not normalized_imdb_id:
        return redirect(reverse("dramaNlearn:imdb"))

    series = get_object_or_404(ImdbDramaSeriesCache, imdb_id=normalized_imdb_id)
    return_url = _safe_next_url(request, reverse("dramaNlearn:imdb"))
    series.delete()
    messages.success(request, "저장된 IMDb 드라마를 삭제했습니다.")
    return redirect(return_url)


@login_required
def url_manage(request):
    videos = Video.objects.filter(owner=request.user).order_by("-created_at")
    for video in videos:
        video.latest_job = _get_video_job(video)
    return render(request, "dramaNlearn/url_manage.html", {
        "videos": videos,
        "ready_count": videos.filter(status="ready").count(),
        "error_count": videos.filter(status="error").count(),
    })


@require_POST
def add_video(request):
    if not request.user.is_authenticated:
        return json_login_required()

    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    raw_urls = data.get('urls')
    raw_items = data.get('items')
    title = (data.get('title') or '').strip()

    items = []

    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            items.append({
                'url': str(item.get('url') or '').strip(),
                'title': str(item.get('title') or '').strip(),
            })

    if isinstance(raw_urls, list):
        for url in raw_urls:
            items.append({'url': str(url or '').strip(), 'title': title})

    source_url = (data.get('url') or '').strip()
    if source_url:
        items.append({'url': source_url, 'title': title})

    items = [item for item in items if item.get('url')]
    if not items:
        return JsonResponse({'ok': False, 'error': 'URL을 하나 이상 입력해주세요.'})

    requires_title = isinstance(raw_items, list)
    results = [
        _extract_video_for_user(
            owner=request.user,
            source_url=item['url'],
            title=item.get('title', ''),
            require_title=requires_title,
        )
        for item in items
    ]
    success_count = sum(1 for item in results if item.get('ok') and not item.get('existing'))
    existing_count = sum(1 for item in results if item.get('existing'))
    failed_count = sum(1 for item in results if not item.get('ok'))

    if len(results) == 1:
        payload = dict(results[0])
        payload.update({
            'results': results,
            'success_count': success_count,
            'existing_count': existing_count,
            'failed_count': failed_count,
        })
        return JsonResponse(payload, status=200 if payload.get('ok') else 400)

    return JsonResponse({
        'ok': success_count > 0 or existing_count > 0,
        'results': results,
        'success_count': success_count,
        'existing_count': existing_count,
        'failed_count': failed_count,
        'requested_count': len(items),
    })


@require_POST
def update_title(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    if not request.user.is_authenticated:
        return json_login_required()
    if video.owner_id != request.user.id:
        return JsonResponse({'ok': False, 'error': '내가 등록한 영상만 편집할 수 있습니다.'}, status=403)
    try:
        data  = json.loads(request.body)
        title = data.get('title', '').strip()
        if title:
            video.title = title
            video.save(update_fields=['title'])
        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)})


@require_POST
def update_thumbnail(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    if not request.user.is_authenticated:
        return json_login_required()
    if video.owner_id != request.user.id:
        return JsonResponse({'ok': False, 'error': '내가 등록한 영상만 편집할 수 있습니다.'}, status=403)

    uploaded_file = request.FILES.get('thumbnail_file')
    if uploaded_file:
        allowed_content_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/avif'}
        content_type = (uploaded_file.content_type or '').lower()
        if content_type and content_type not in allowed_content_types:
            return JsonResponse({'ok': False, 'error': 'jpg, png, webp, gif, avif 이미지만 업로드할 수 있습니다.'}, status=400)

        safe_name = get_valid_filename(Path(uploaded_file.name).name or 'thumbnail')
        storage_path = Path('thumbnails') / f"video-{video.id}-{uuid4().hex}-{safe_name}"
        saved_path = default_storage.save(str(storage_path), uploaded_file)
        video.thumbnail = request.build_absolute_uri(default_storage.url(saved_path))
        video.save(update_fields=['thumbnail'])
        return JsonResponse({'ok': True, 'thumbnail': video.thumbnail})

    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    thumbnail = (data.get('thumbnail') or '').strip()
    if thumbnail:
        validator = URLValidator(schemes=['http', 'https'])
        try:
            validator(thumbnail)
        except ValidationError:
            return JsonResponse({'ok': False, 'error': 'http 또는 https 썸네일 URL만 사용할 수 있습니다.'}, status=400)

    video.thumbnail = thumbnail
    video.save(update_fields=['thumbnail'])
    return JsonResponse({'ok': True, 'thumbnail': video.thumbnail})


@require_POST
def refresh_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    if not request.user.is_authenticated:
        return json_login_required()
    if video.owner_id != request.user.id:
        return JsonResponse({'ok': False, 'error': '내가 등록한 영상만 갱신할 수 있습니다.'}, status=403)
    ok, error = _enqueue_drama_extract(video=video, user=request.user, message="Queued for drama refresh")
    if ok:
        return JsonResponse({
            'ok': True,
            'queued': True,
            'video_id': video.id,
        })
    return JsonResponse({'ok': False, 'error': error})


@require_POST
def retry_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    if not request.user.is_authenticated:
        return json_login_required()
    if video.owner_id != request.user.id:
        return JsonResponse({'ok': False, 'error': '내가 등록한 영상만 재시도할 수 있습니다.'}, status=403)
    ok, error = _enqueue_drama_extract(video=video, user=request.user, message="Queued for drama retry")
    if ok:
        return JsonResponse({'ok': True, 'queued': True, 'video_id': video.id})
    return JsonResponse({'ok': False, 'error': error})


@require_POST
def cancel_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    if not request.user.is_authenticated:
        return json_login_required()
    if video.owner_id != request.user.id:
        return JsonResponse({'ok': False, 'error': '내가 등록한 영상만 취소할 수 있습니다.'}, status=403)

    job = _get_video_job(video)
    if not job or job.status not in {BackgroundJobState.PENDING, BackgroundJobState.QUEUED}:
        return JsonResponse({'ok': False, 'error': '대기 중인 추출 작업만 취소할 수 있습니다.'}, status=400)

    if job.celery_task_id:
        current_app.control.revoke(job.celery_task_id)

    job.status = BackgroundJobState.CANCELED
    job.message = "Drama extraction canceled"
    job.error_message = ""
    job.progress_percent = 100
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "message", "error_message", "progress_percent", "finished_at", "updated_at"])

    video.status = "canceled"
    video.error_msg = ""
    video.save(update_fields=["status", "error_msg", "updated_at"])
    return JsonResponse({'ok': True, 'canceled': True, 'video_id': video.id})


@require_POST
def delete_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    fallback_url = reverse('dramaNlearn:url_manage')
    if not request.user.is_authenticated:
        if _expects_json_response(request):
            return json_login_required()
        messages.error(request, "로그인이 필요합니다.")
        return redirect(_safe_next_url(request, fallback_url))
    if video.owner_id != request.user.id:
        if _expects_json_response(request):
            return JsonResponse({'ok': False, 'error': '내가 등록한 영상만 삭제할 수 있습니다.'}, status=403)
        messages.error(request, "내가 등록한 영상만 삭제할 수 있습니다.")
        return redirect(_safe_next_url(request, fallback_url))
    video.delete()
    if _expects_json_response(request):
        return JsonResponse({'ok': True})
    messages.success(request, "삭제되었습니다.")
    return redirect(_safe_next_url(request, fallback_url))


def player(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    can_play = request.user.is_authenticated
    if can_play:
        video.view_count += 1
        video.save(update_fields=['view_count'])
    related = Video.objects.filter(status='ready').exclude(id=video_id)[:6]
    is_owner = can_play and video.owner_id == request.user.id
    clip_extract_url = reverse("dramaNlearn:clip_extract", args=[video.id]) if is_owner else ""
    return render(request, "dramaNlearn/player.html", {
        'video': video,
        'related': related,
        'is_owner': is_owner,
        'can_play': can_play,
        'subtitle_tracks_json': json.dumps(video.subtitle_tracks_list(), ensure_ascii=False),
        'clip_extract_url': clip_extract_url,
    })


@login_required
def open_clip_extract(request, video_id):
    video = get_object_or_404(Video, id=video_id, owner=request.user)
    if video.status != "ready" or not video.m3u8_url:
        messages.error(request, "재생 가능한 드라마 스트림이 준비된 뒤에 클립을 추출할 수 있습니다.")
        return redirect("dramaNlearn:player", video_id=video.id)

    master_video = _sync_drama_master_video(video)
    return redirect("videos:detail", pk=master_video.id)


def api_video_status(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    is_owner = request.user.is_authenticated and video.owner_id == request.user.id
    job = _get_video_job(video) if is_owner else None
    payload = {
        'id': video.id, 'status': video.status,
        'm3u8_url': video.m3u8_url, 'thumbnail': video.thumbnail,
        'duration': video.duration, 'error': video.error_msg,
        'subtitles': video.subtitle_tracks_list(),
    }
    if is_owner:
        payload['job'] = {
            'status': job.status if job else '',
            'status_label': job.get_status_display() if job else '',
            'progress_percent': job.progress_percent if job else 0,
            'message': job.message if job else '',
            'error_message': job.error_message if job else '',
        }
    return JsonResponse(payload)


def api_static_images(request):
    if not request.user.is_authenticated:
        return json_login_required()

    items = [
        {
            "id": asset.id,
            "name": asset.name,
            "path": asset.image.name,
            "url": request.build_absolute_uri(asset.image.url),
            "source": "uploaded",
        }
        for asset in ThumbnailAsset.objects.exclude(image="").order_by("name", "-created_at")
        if asset.image
    ]

    static_root = Path(settings.BASE_DIR) / "static" / "dramaNlearn"
    allowed_exts = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif'}
    if static_root.exists():
        for path in sorted(static_root.rglob('*')):
            if not path.is_file() or path.suffix.lower() not in allowed_exts:
                continue
            rel_path = (Path("dramaNlearn") / path.relative_to(static_root)).as_posix()
            items.append({
                'id': None,
                'name': path.name,
                'path': rel_path,
                'url': request.build_absolute_uri(static(rel_path)),
                'source': 'static',
            })

    return JsonResponse({'ok': True, 'images': items})


@login_required
def thumbnail_list(request):
    if request.method == "POST":
        row_indexes_raw = (request.POST.get("row_indexes") or "").strip()
        if row_indexes_raw:
            row_indexes = [idx for idx in row_indexes_raw.split(",") if idx.strip()]
            items = []
            invalid_rows = []
            for idx in row_indexes:
                name = (request.POST.get(f"name_{idx}") or "").strip()
                image = request.FILES.get(f"image_{idx}")
                if not name and not image:
                    continue
                if not name or not image:
                    invalid_rows.append(idx)
                    continue
                items.append((name, image))

            if invalid_rows:
                messages.error(request, "각 줄마다 이름과 이미지를 모두 선택해야 합니다.")
            elif not items:
                messages.error(request, "등록할 썸네일을 하나 이상 입력해주세요.")
            else:
                created_count = 0
                for name, image in items:
                    processed_image = _build_thumbnail_content(image, image.name or name)
                    ThumbnailAsset.objects.create(
                        name=name,
                        image=processed_image,
                        created_by=request.user,
                    )
                    created_count += 1
                messages.success(request, f"썸네일 {created_count}개가 등록되었습니다.")
                return redirect("thumbnail_admin:list")
        else:
            form = ThumbnailAssetForm(request.POST, request.FILES)
            if form.is_valid():
                asset = form.save(commit=False)
                asset.created_by = request.user
                if request.FILES.get("image"):
                    asset.image = _build_thumbnail_content(request.FILES["image"], request.FILES["image"].name or asset.name)
                asset.save()
                messages.success(request, "썸네일이 등록되었습니다.")
                return redirect("thumbnail_admin:list")

    assets = ThumbnailAsset.objects.order_by("name", "-created_at")
    return render(
        request,
        "dramaNlearn/thumbnail_list.html",
        {
            "assets": assets,
        },
    )


@login_required
def thumbnail_edit(request, asset_id):
    asset = get_object_or_404(ThumbnailAsset, pk=asset_id)
    old_image_name = asset.image.name if asset.image else ""

    if request.method == "POST":
        form = ThumbnailAssetForm(request.POST, request.FILES, instance=asset)
        if form.is_valid():
            updated_asset = form.save(commit=False)
            if request.FILES.get("image"):
                updated_asset.image = _build_thumbnail_content(request.FILES["image"], request.FILES["image"].name or updated_asset.name)
            updated_asset.save()
            if old_image_name and request.FILES.get("image") and old_image_name != updated_asset.image.name:
                storage = updated_asset.image.storage
                if storage.exists(old_image_name):
                    storage.delete(old_image_name)
            messages.success(request, "썸네일이 수정되었습니다.")
            return redirect("thumbnail_admin:list")
    else:
        form = ThumbnailAssetForm(instance=asset)

    return render(
        request,
        "dramaNlearn/thumbnail_form.html",
        {
            "form": form,
            "asset": asset,
        },
    )


@login_required
@require_POST
def thumbnail_delete(request, asset_id):
    asset = get_object_or_404(ThumbnailAsset, pk=asset_id)
    image_name = asset.image.name if asset.image else ""
    storage = asset.image.storage if asset.image else None
    asset.delete()
    if storage and image_name and storage.exists(image_name):
        storage.delete(image_name)
    messages.success(request, "썸네일이 삭제되었습니다.")
    return redirect("thumbnail_admin:list")
