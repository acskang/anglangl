import json
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import requests
from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.exceptions import ValidationError
from django.utils.text import get_valid_filename
from django.core.validators import URLValidator
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_POST
from PIL import Image, ImageOps

from .forms import ThumbnailAssetForm
from .models import ThumbnailAsset, Video
from . import extractor


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
        status='fetching',
    )

    try:
        info = extractor.extract(source_url)
        video.player_url = info.get('player_url', '')
        video.m3u8_url = info.get('m3u8_url', '')
        video.thumbnail = info.get('thumbnail', '')
        video.duration = info.get('duration', 0)
        video.subtitle_tracks = json.dumps(info.get('subtitles', []), ensure_ascii=False)
        video.status = 'ready'
        if not title:
            video.title = source_url.rstrip('/').split('/')[-1]
        video.save()
        return {
            'ok': True,
            'video_id': video.id,
            'redirect': reverse('dramaNlearn:player', args=[video.id]),
            'url': source_url,
            'title': title,
            'existing': False,
        }
    except Exception as e:
        video.status = 'error'
        video.error_msg = str(e)
        video.save()
        return {'ok': False, 'error': str(e), 'video_id': video.id, 'url': source_url, 'title': title}


def home(request):
    videos = Video.objects.all()
    return render(request, "dramaNlearn/home.html", {
        "videos": videos,
        "ready_count": videos.filter(status="ready").count(),
        "error_count": videos.filter(status="error").count(),
    })


@login_required
def url_manage(request):
    videos = Video.objects.filter(owner=request.user).order_by("-created_at")
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
    video.status = 'fetching'
    video.save(update_fields=['status'])
    try:
        info = extractor.extract(video.source_url)
        video.player_url = info.get('player_url', '')
        video.m3u8_url   = info.get('m3u8_url', '')
        video.thumbnail  = info.get('thumbnail', '')
        video.duration   = info.get('duration', 0)
        video.subtitle_tracks = json.dumps(info.get('subtitles', []), ensure_ascii=False)
        video.status     = 'ready'
        video.error_msg  = ''
        video.save()
        return JsonResponse({
            'ok': True,
            'm3u8_url': video.m3u8_url,
            'subtitles': video.subtitle_tracks_list(),
        })
    except Exception as e:
        video.status    = 'error'
        video.error_msg = str(e)
        video.save()
        return JsonResponse({'ok': False, 'error': str(e)})


@require_POST
def delete_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    if not request.user.is_authenticated:
        return json_login_required()
    if video.owner_id != request.user.id:
        return JsonResponse({'ok': False, 'error': '내가 등록한 영상만 삭제할 수 있습니다.'}, status=403)
    video.delete()
    return JsonResponse({'ok': True})


def player(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    can_play = request.user.is_authenticated
    if can_play:
        video.view_count += 1
        video.save(update_fields=['view_count'])
    related = Video.objects.filter(status='ready').exclude(id=video_id)[:6]
    is_owner = can_play and video.owner_id == request.user.id
    return render(request, "dramaNlearn/player.html", {
        'video': video,
        'related': related,
        'is_owner': is_owner,
        'can_play': can_play,
        'subtitle_tracks_json': json.dumps(video.subtitle_tracks_list(), ensure_ascii=False),
    })


def api_video_status(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    return JsonResponse({
        'id': video.id, 'status': video.status,
        'm3u8_url': video.m3u8_url, 'thumbnail': video.thumbnail,
        'duration': video.duration, 'error': video.error_msg,
        'subtitles': video.subtitle_tracks_list(),
    })


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
