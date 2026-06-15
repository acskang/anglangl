import json
import re
from html import unescape
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from PIL import Image, ImageOps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import get_valid_filename
from django.views import View
from django.views.generic import DetailView, FormView, ListView, UpdateView

from clips.models import AlbumImage, Clip, ClipImage
from core.models import BackgroundJobState, ProcessingState
from workers.models import BackgroundJob, BackgroundJobType

from .forms import MasterVideoCreateForm, MasterVideoMetadataForm
from .models import MasterVideo, MasterVideoSourceType
from .services.download_state import normalize_stale_pending_master_videos
from .services.youtube import InvalidYouTubeInput, normalize_youtube_input
from .services.ytdlp import YtDlpService, YtDlpTransientError
from .tasks import download_youtube_video, process_uploaded_master_video


THUMBNAIL_OUTPUT_SIZE = (960, 540)
THUMBNAIL_TARGET_MAX_BYTES = 250 * 1024
ACTIVE_MASTER_VIDEO_JOB_TYPES = [
    BackgroundJobType.YOUTUBE_DOWNLOAD,
    BackgroundJobType.MASTER_VIDEO_UPLOAD_PROCESS,
]
META_TAG_PATTERN = re.compile(r"<meta\b([^>]+)/?>", re.IGNORECASE)
META_ATTR_PATTERN = re.compile(
    r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""",
    re.IGNORECASE,
)


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


def _delete_thumbnail_field(file_field) -> None:
    if file_field:
        file_field.delete(save=False)


def _safe_next_url(request, fallback: str) -> str:
    next_url = (request.POST.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback


def _library_url_for_source(source_type: str | None = None) -> str:
    if source_type == MasterVideoSourceType.YOUTUBE:
        return reverse("videos:linked-list")
    if source_type == MasterVideoSourceType.UPLOAD:
        return reverse("videos:upload-list")
    return reverse("dashboard:home")


def _save_thumbnail_url(*, request, video: MasterVideo, uploaded_file, preferred_name: str = "") -> None:
    if preferred_name.strip():
        uploaded_file.name = preferred_name.strip()
    processed_image = _build_thumbnail_content(uploaded_file)
    _delete_thumbnail_field(video.custom_thumbnail_file)
    video.custom_thumbnail_file.save(processed_image.name, processed_image, save=False)


def _youtube_thumbnail_candidates(video: MasterVideo) -> list[str]:
    candidates: list[str] = []
    if video.thumbnail_url:
        candidates.append(video.thumbnail_url)
    if video.youtube_video_id:
        for name in ("maxresdefault.jpg", "hqdefault.jpg", "mqdefault.jpg", "sddefault.jpg"):
            candidates.append(f"https://img.youtube.com/vi/{video.youtube_video_id}/{name}")
    return candidates


def _fetch_youtube_oembed_metadata(normalized_input) -> dict | None:
    oembed_url = (
        "https://www.youtube.com/oembed"
        f"?url=https://www.youtube.com/watch?v={normalized_input.youtube_video_id}&format=json"
    )
    request = Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None

    return {
        "title": payload.get("title") or f"Video {normalized_input.youtube_video_id}",
        "description": "",
        "thumbnail": f"https://img.youtube.com/vi/{normalized_input.youtube_video_id}/maxresdefault.jpg",
        "duration": 0,
        "uploader": payload.get("author_name") or "",
        "channel": payload.get("author_name") or "",
    }


def _iter_html_meta_tags(html_text: str):
    for raw_attrs in META_TAG_PATTERN.findall(html_text or ""):
        attrs: dict[str, str] = {}
        for match in META_ATTR_PATTERN.finditer(raw_attrs):
            value = match.group(2) or match.group(3) or match.group(4) or ""
            attrs[match.group(1).lower()] = unescape(value.strip())
        if attrs:
            yield attrs


def _extract_meta_content(html_text: str, *names: str) -> str:
    candidates = {value.lower() for value in names}
    for attrs in _iter_html_meta_tags(html_text):
        name = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        if name in candidates:
            return (attrs.get("content") or "").strip()
    return ""


def _fetch_youtube_page_metadata(normalized_input) -> dict | None:
    request = Request(
        normalized_input.youtube_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            headers = getattr(response, "headers", None)
            charset = None
            if headers is not None:
                get_content_charset = getattr(headers, "get_content_charset", None)
                if callable(get_content_charset):
                    charset = get_content_charset()
            html_text = response.read().decode(charset or "utf-8", errors="ignore")
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None

    description = _extract_meta_content(html_text, "og:description", "description", "twitter:description")
    title = _extract_meta_content(html_text, "og:title", "twitter:title")
    thumbnail = _extract_meta_content(html_text, "og:image", "twitter:image")
    if not any((description, title, thumbnail)):
        return None

    return {
        "title": title,
        "description": description,
        "thumbnail": thumbnail,
        "duration": 0,
        "uploader": "",
        "channel": "",
    }


def _fetch_youtube_fallback_metadata(normalized_input) -> dict | None:
    oembed_metadata = _fetch_youtube_oembed_metadata(normalized_input) or {}
    page_metadata = _fetch_youtube_page_metadata(normalized_input) or {}
    if not oembed_metadata and not page_metadata:
        return None

    return {
        "title": oembed_metadata.get("title") or page_metadata.get("title") or f"Video {normalized_input.youtube_video_id}",
        "description": page_metadata.get("description") or oembed_metadata.get("description") or "",
        "thumbnail": page_metadata.get("thumbnail")
        or oembed_metadata.get("thumbnail")
        or f"https://img.youtube.com/vi/{normalized_input.youtube_video_id}/maxresdefault.jpg",
        "duration": oembed_metadata.get("duration") or page_metadata.get("duration") or 0,
        "uploader": oembed_metadata.get("uploader")
        or oembed_metadata.get("channel")
        or page_metadata.get("uploader")
        or page_metadata.get("channel")
        or "",
        "channel": oembed_metadata.get("channel")
        or oembed_metadata.get("uploader")
        or page_metadata.get("channel")
        or page_metadata.get("uploader")
        or "",
    }


def _fetch_youtube_metadata(normalized_input) -> dict | None:
    service = YtDlpService()
    try:
        return service.fetch_metadata(normalized_input.youtube_url)
    except YtDlpTransientError:
        return _fetch_youtube_fallback_metadata(normalized_input)


def _coerce_duration_seconds(raw_duration) -> int:
    if isinstance(raw_duration, int):
        return raw_duration
    if isinstance(raw_duration, float):
        return int(raw_duration)
    try:
        return int(raw_duration or 0)
    except (TypeError, ValueError):
        return 0


def _fill_missing_youtube_metadata(normalized_input, metadata: dict) -> dict:
    needs_description = not (metadata.get("description") or "").strip()
    needs_title = not (metadata.get("title") or "").strip()
    needs_thumbnail = not (metadata.get("thumbnail_url") or "").strip()
    needs_channel = not (metadata.get("channel") or "").strip()
    needs_duration = not _coerce_duration_seconds(metadata.get("duration"))

    if not any((needs_description, needs_title, needs_thumbnail, needs_channel, needs_duration)):
        return metadata

    fallback_metadata = _fetch_youtube_metadata(normalized_input) or {}
    if not fallback_metadata:
        return metadata

    enriched = dict(metadata)
    if needs_description:
        enriched["description"] = (fallback_metadata.get("description") or "").strip()
    if needs_title:
        enriched["title"] = (fallback_metadata.get("title") or "").strip()
    if needs_thumbnail:
        enriched["thumbnail_url"] = (fallback_metadata.get("thumbnail") or "").strip()
    if needs_channel:
        enriched["channel"] = (
            fallback_metadata.get("uploader") or fallback_metadata.get("channel") or ""
        ).strip()
    if needs_duration:
        enriched["duration"] = _coerce_duration_seconds(fallback_metadata.get("duration"))
    return enriched


def _save_remote_thumbnail_file(video: MasterVideo) -> bool:
    if video.saved_thumbnail_file:
        return True

    for candidate in _youtube_thumbnail_candidates(video):
        try:
            request = Request(candidate, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=10) as response:
                image_bytes = response.read()
                content_type = response.headers.get("Content-Type", "")
        except (HTTPError, URLError, TimeoutError, ValueError):
            continue

        if not image_bytes or len(image_bytes) < 1024:
            continue

        suffix = ".jpg"
        lowered = content_type.lower()
        if "png" in lowered:
            suffix = ".png"
        elif "webp" in lowered:
            suffix = ".webp"

        file_name = f"video-{video.id or 'new'}-saved{suffix}"
        _delete_thumbnail_field(video.saved_thumbnail_file)
        video.saved_thumbnail_file.save(file_name, ContentFile(image_bytes, name=file_name), save=False)
        return True

    return False


def _build_clipmaster_clip_title(video: MasterVideo, seq_no: int) -> str:
    return f"{video.title}_{seq_no:02d}"


def _enqueue_linked_video(video: MasterVideo, *, request_user, queue_message: str) -> tuple[bool, str]:
    job = BackgroundJob.objects.create(
        user=request_user,
        job_type=BackgroundJobType.YOUTUBE_DOWNLOAD,
        related_object_type="master_video",
        related_object_id=str(video.id),
        status=BackgroundJobState.QUEUED,
        progress_percent=0,
        message=queue_message,
    )
    try:
        async_result = download_youtube_video.delay(video.id)
    except Exception as exc:  # noqa: BLE001
        video.download_status = ProcessingState.FAILED
        video.download_error_message = f"Failed to enqueue task: {exc}"
        video.save(update_fields=["download_status", "download_error_message", "updated_at"])
        job.status = BackgroundJobState.FAILED
        job.error_message = str(exc)
        job.message = "Failed to enqueue source import task"
        job.save(update_fields=["status", "error_message", "message", "updated_at"])
        return False, str(exc)

    job.celery_task_id = async_result.id
    job.save(update_fields=["celery_task_id", "updated_at"])
    return True, ""


def _delete_hls_artifacts(file_field) -> None:
    if not file_field:
        return

    manifest_path = Path(file_field.path)
    hls_dir = manifest_path.parent
    file_field.delete(save=False)
    if not hls_dir.exists():
        return

    for child in hls_dir.iterdir():
        if child.is_file():
            child.unlink()
    try:
        hls_dir.rmdir()
    except OSError:
        pass


def _delete_album_image_file(album_image: AlbumImage) -> None:
    if not album_image.image:
        return

    clip_image_name = ""
    if album_image.clip_image and album_image.clip_image.image:
        clip_image_name = album_image.clip_image.image.name

    if clip_image_name and clip_image_name == album_image.image.name:
        return

    album_image.image.delete(save=False)


def _delete_clip_image_and_refs(clip_image: ClipImage) -> None:
    for album_ref in list(clip_image.album_refs.all()):
        album_ref.delete()

    if clip_image.image:
        clip_image.image.delete(save=False)
    clip_image.delete()


def _delete_clip_assets(clip: Clip) -> None:
    for album_image in list(AlbumImage.objects.filter(clip=clip)):
        _delete_album_image_file(album_image)
        album_image.delete()

    for clip_image in list(ClipImage.objects.filter(clip=clip)):
        _delete_clip_image_and_refs(clip_image)

    if clip.thumbnail_file:
        clip.thumbnail_file.delete(save=False)
    if clip.hls_manifest_file:
        _delete_hls_artifacts(clip.hls_manifest_file)
    if clip.clip_file:
        clip.clip_file.delete(save=False)
    clip.delete()


class VideoVisibilityQuerySetMixin(LoginRequiredMixin):
    def get_queryset(self):
        normalize_stale_pending_master_videos()
        return MasterVideo.objects.filter(owner=self.request.user, is_active=True).select_related("owner", "source_drama_video")


class VideoLibraryView(VideoVisibilityQuerySetMixin, ListView):
    model = MasterVideo
    template_name = "videos/video_list.html"
    context_object_name = "videos"

    def get_source_filter(self) -> str:
        value = (self.request.GET.get("source") or "").strip().lower()
        if value in {MasterVideoSourceType.YOUTUBE, MasterVideoSourceType.UPLOAD}:
            return value
        return ""

    def get_search_query(self) -> str:
        return (self.request.GET.get("q") or "").strip()

    def get_page_kicker(self) -> str:
        return "Library"

    def get_page_description(self) -> str:
        return "소스 비디오를 등록하고, 상태를 확인하고, 클립 작업으로 이어가는 비디오 라이브러리입니다."

    def get_page_title(self) -> str:
        source_filter = self.get_source_filter()
        return {
            MasterVideoSourceType.YOUTUBE: "Linked Videos",
            MasterVideoSourceType.UPLOAD: "Uploads",
        }.get(source_filter, "Videos")

    def get_empty_message(self) -> str:
        return "등록된 비디오가 없습니다."

    def get_create_url(self) -> str:
        source_filter = self.get_source_filter()
        if source_filter == MasterVideoSourceType.YOUTUBE:
            return reverse("videos:create-youtube")
        if source_filter == MasterVideoSourceType.UPLOAD:
            return reverse("videos:create-video")
        return reverse("videos:create")

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .filter(source_drama_video__isnull=True)
            .annotate(clip_count=Count("clips", filter=Q(clips__is_active=True), distinct=True))
        )
        source_filter = self.get_source_filter()
        if source_filter:
            queryset = queryset.filter(source_type=source_filter)

        query = self.get_search_query()
        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(description__icontains=query)
                | Q(youtube_video_id__icontains=query)
                | Q(youtube_url__icontains=query)
            )
        return queryset.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        source_filter = self.get_source_filter()
        context.update(
            {
                "page_title": self.get_page_title(),
                "page_kicker": self.get_page_kicker(),
                "page_description": self.get_page_description(),
                "empty_message": self.get_empty_message(),
                "source_filter": source_filter,
                "search_query": self.get_search_query(),
                "create_url": self.get_create_url(),
                "is_linked_library": source_filter == MasterVideoSourceType.YOUTUBE,
            }
        )
        return context


class YoutubeVideoListView(VideoLibraryView):
    def get_source_filter(self) -> str:
        return MasterVideoSourceType.YOUTUBE

    def get_page_title(self) -> str:
        return "저장된 영상"

    def get_page_kicker(self) -> str:
        return "Youtube"

    def get_page_description(self) -> str:
        return "등록된 YouTube 영상을 모아 보고, 상태를 확인하고, 클립 작업으로 이어가는 목록입니다."

    def get_empty_message(self) -> str:
        return "등록된 YouTube 영상이 없습니다."


class UploadedVideoListView(VideoLibraryView):
    def get_source_filter(self) -> str:
        return MasterVideoSourceType.UPLOAD


class ThumbnailAlbumView(VideoVisibilityQuerySetMixin, ListView):
    model = MasterVideo
    template_name = "videos/thumbnail_album.html"
    context_object_name = "videos"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(source_drama_video__isnull=True)
            .filter(
                Q(custom_thumbnail_file__gt="")
                | Q(saved_thumbnail_file__gt="")
                | Q(thumbnail_url__gt="")
            )
            .annotate(clip_count=Count("clips", filter=Q(clips__is_active=True), distinct=True))
            .order_by("-updated_at", "-created_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_kicker": "Youtube",
                "page_title": "썸네일 이미지 앨범",
                "page_description": "저장된 영상의 썸네일 이미지를 모아 보고, 블로그편집이나 클립 추출로 바로 이어갈 수 있는 앨범입니다.",
                "empty_message": "등록된 썸네일 이미지가 없습니다.",
            }
        )
        return context


class MasterVideoDetailView(VideoVisibilityQuerySetMixin, DetailView):
    model = MasterVideo
    template_name = "videos/video_extract_detail.html"
    context_object_name = "video"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        show_inline_player = bool(
            (self.object.hls_manifest_file and self.object.hls_manifest_file.name)
            or (self.object.video_file and self.object.video_file.name)
            or self.object.remote_playback_url
        )
        is_drama_bridge = bool(self.object.source_drama_video_id)
        context["can_manage"] = self.object.owner_id == self.request.user.id
        context["can_reload"] = (
            context["can_manage"]
            and self.object.source_type == MasterVideoSourceType.YOUTUBE
            and self.object.download_status in {ProcessingState.FAILED, ProcessingState.PENDING}
        )
        context["job"] = (
            BackgroundJob.objects.filter(
                user=self.request.user,
                related_object_type="master_video",
                related_object_id=str(self.object.id),
                job_type__in=ACTIVE_MASTER_VIDEO_JOB_TYPES,
            )
            .order_by("-created_at")
            .first()
        )
        context["clips"] = self.object.clips.filter(is_active=True).order_by("-created_at")
        context["subtitle_url"] = self.object.subtitle_file.url if self.object.subtitle_file else ""
        context["download_url"] = reverse("videos:download", kwargs={"pk": self.object.id}) if self.object.video_file else ""
        context["thumbnail_proxy_url"] = reverse("videos:thumbnail-proxy", kwargs={"pk": self.object.id})
        context["show_local_player"] = show_inline_player
        context["show_youtube_embed"] = self.object.source_type == MasterVideoSourceType.YOUTUBE and not show_inline_player

        if self.object.hls_manifest_file:
            context["playback_url"] = self.object.hls_manifest_file.url
            context["playback_type"] = "hls"
        elif self.object.remote_playback_url:
            context["playback_url"] = self.object.remote_playback_url
            context["playback_type"] = "hls"
        elif self.object.video_file:
            context["playback_url"] = self.object.video_file.url
            context["playback_type"] = "file"
        else:
            context["playback_url"] = ""
            context["playback_type"] = ""

        if is_drama_bridge:
            context["list_url"] = reverse("dramaNlearn:player", args=[self.object.source_drama_video_id])
            context["list_label"] = "드라마보기"
            context["page_kicker"] = "Drama"
            context["source_link_url"] = self.object.source_drama_video.source_url
            context["source_link_label"] = "원본 페이지"
        else:
            context["list_url"] = _library_url_for_source(self.object.source_type)
            if self.object.source_type == MasterVideoSourceType.YOUTUBE:
                context["list_label"] = "저장된 영상"
            elif self.object.source_type == MasterVideoSourceType.UPLOAD:
                context["list_label"] = "업로드 영상"
            else:
                context["list_label"] = "Dashboard"
            context["page_kicker"] = "Youtube"
            context["source_link_url"] = self.object.url
            context["source_link_label"] = "YouTube"
        return context


class MasterVideoCreateView(LoginRequiredMixin, FormView):
    template_name = "videos/video_form.html"
    form_class = MasterVideoCreateForm
    preferred_source_type = ""

    def get_preferred_source_type(self) -> str:
        query_value = (self.request.GET.get("source") or "").strip().lower()
        if query_value in {MasterVideoSourceType.YOUTUBE, MasterVideoSourceType.UPLOAD}:
            return query_value
        if self.preferred_source_type in {MasterVideoSourceType.YOUTUBE, MasterVideoSourceType.UPLOAD}:
            return self.preferred_source_type
        return MasterVideoSourceType.YOUTUBE

    def get_initial(self):
        initial = super().get_initial()
        initial["source_type"] = self.get_preferred_source_type()
        return initial

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["source_type"].initial = self.get_preferred_source_type()
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["preferred_source_type"] = self.get_preferred_source_type()
        context["recent_videos"] = self.get_recent_videos()
        return context

    def get_recent_videos(self):
        return MasterVideo.objects.filter(owner=self.request.user, is_active=True).order_by("-created_at")[:8]

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
            messages.info(self.request, "This linked video is already in your library.")
            return redirect("videos:detail", pk=existing.id)

        _save_remote_thumbnail_file(video)
        video.save(update_fields=["saved_thumbnail_file", "updated_at"])
        ok, _ = _enqueue_linked_video(video, request_user=self.request.user, queue_message="Queued for source video import")
        if not ok:
            messages.error(self.request, "Video was registered, but queueing failed.")
            return redirect("videos:detail", pk=video.id)

        messages.success(self.request, "Linked video registered and queued for processing.")
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

        messages.success(self.request, "Uploaded video registered and queued for processing.")
        return redirect("videos:detail", pk=video.id)


class RegisterYoutubeView(MasterVideoCreateView):
    preferred_source_type = MasterVideoSourceType.YOUTUBE
    template_name = "videos/video_add.html"

    def get_recent_videos(self):
        return (
            MasterVideo.objects.filter(
                owner=self.request.user,
                is_active=True,
                source_type=MasterVideoSourceType.YOUTUBE,
            )
            .order_by("-created_at")[:8]
        )


class RegisterUploadVideoView(MasterVideoCreateView):
    preferred_source_type = MasterVideoSourceType.UPLOAD
    template_name = "videos/video_form.html"


class MasterVideoOwnerRequiredMixin(LoginRequiredMixin):
    def get_queryset(self):
        return MasterVideo.objects.filter(owner=self.request.user, is_active=True).select_related("owner")


class MasterVideoEditView(MasterVideoOwnerRequiredMixin, UpdateView):
    model = MasterVideo
    form_class = MasterVideoMetadataForm
    template_name = "videos/video_edit_clipmaster.html"
    context_object_name = "video"

    def get_context_data(self, **kwargs):
        if self.object.source_type == MasterVideoSourceType.YOUTUBE and not (self.object.description or "").strip():
            try:
                normalized = normalize_youtube_input(self.object.youtube_url or self.object.youtube_video_id)
            except InvalidYouTubeInput:
                normalized = None
            if normalized is not None:
                metadata = _fill_missing_youtube_metadata(
                    normalized,
                    {
                        "title": self.object.title,
                        "description": self.object.description,
                        "thumbnail_url": self.object.thumbnail_url,
                        "duration": self.object.duration_seconds,
                        "channel": self.object.channel_name,
                    },
                )
                description = (metadata.get("description") or "").strip()
                if description and description != self.object.description:
                    self.object.description = description
                    self.object.save(update_fields=["description", "updated_at"])

        context = super().get_context_data(**kwargs)
        context["category_choices"] = self.object._meta.get_field("category").choices
        context["thumbnail_proxy_url"] = reverse("videos:thumbnail-proxy", kwargs={"pk": self.object.id})
        if self.object.hls_manifest_file:
            context["playback_url"] = self.object.hls_manifest_file.url
            context["playback_type"] = "hls"
        elif self.object.remote_playback_url:
            context["playback_url"] = self.object.remote_playback_url
            context["playback_type"] = "hls"
        elif self.object.video_file:
            context["playback_url"] = self.object.video_file.url
            context["playback_type"] = "file"
        else:
            context["playback_url"] = ""
            context["playback_type"] = ""
        return context

    def form_valid(self, form):
        video = form.save(commit=False)
        update_fields = ["title", "description", "category", "updated_at"]

        if form.cleaned_data.get("remove_thumbnail"):
            _delete_thumbnail_field(video.custom_thumbnail_file)
            if "custom_thumbnail_file" not in update_fields:
                update_fields.append("custom_thumbnail_file")

        thumbnail_file = form.cleaned_data.get("thumbnail_file")
        if thumbnail_file:
            _save_thumbnail_url(request=self.request, video=video, uploaded_file=thumbnail_file)
            if "custom_thumbnail_file" not in update_fields:
                update_fields.append("custom_thumbnail_file")

        subtitle_file = form.cleaned_data.get("subtitle_file")
        if subtitle_file and video.source_type == MasterVideoSourceType.UPLOAD:
            if video.subtitle_file:
                video.subtitle_file.delete(save=False)
            video.subtitle_file.save(subtitle_file.name, subtitle_file, save=False)
            update_fields.append("subtitle_file")

        video.save(update_fields=update_fields)
        messages.success(self.request, "Video metadata updated.")
        return redirect("videos:detail", pk=video.id)


class MasterVideoDownloadView(MasterVideoOwnerRequiredMixin, View):
    def get(self, request, pk: int):
        video = get_object_or_404(self.get_queryset(), pk=pk)
        if not video.video_file:
            raise Http404

        return FileResponse(
            open(video.video_file.path, "rb"),
            as_attachment=True,
            filename=Path(video.video_file.name).name,
        )


class MasterVideoDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        video = get_object_or_404(MasterVideo, pk=pk, owner=request.user, is_active=True)
        next_url = _safe_next_url(request, _library_url_for_source(video.source_type))

        for album_image in list(AlbumImage.objects.filter(master_video=video)):
            _delete_album_image_file(album_image)
            album_image.delete()

        for clip in list(video.clips.all()):
            _delete_clip_assets(clip)

        if video.video_file:
            video.video_file.delete(save=False)
        if video.subtitle_file:
            video.subtitle_file.delete(save=False)
        if video.hls_manifest_file:
            _delete_hls_artifacts(video.hls_manifest_file)
        if video.custom_thumbnail_file:
            video.custom_thumbnail_file.delete(save=False)
        if video.saved_thumbnail_file:
            video.saved_thumbnail_file.delete(save=False)
        _delete_previous_thumbnail_file(video.thumbnail_url)

        video.delete()
        messages.success(request, "Video deleted.")
        return redirect(next_url)


class MasterVideoSubtitleUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        video = get_object_or_404(MasterVideo, pk=pk, source_type=MasterVideoSourceType.UPLOAD, owner=request.user)

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
        video = get_object_or_404(MasterVideo, pk=pk, owner=request.user)
        fallback_url = reverse("videos:detail", kwargs={"pk": video.id})

        if video.source_type != MasterVideoSourceType.YOUTUBE:
            messages.info(request, "Reload is only available for linked source videos.")
            return redirect(_safe_next_url(request, fallback_url))

        if video.download_status not in {ProcessingState.FAILED, ProcessingState.PENDING}:
            messages.info(request, "Only failed or pending downloads can be reloaded.")
            return redirect(_safe_next_url(request, fallback_url))

        video.download_status = ProcessingState.QUEUED
        video.download_error_message = ""
        video.save(update_fields=["download_status", "download_error_message", "updated_at"])

        job = BackgroundJob.objects.create(
            user=request.user,
            job_type=BackgroundJobType.YOUTUBE_DOWNLOAD,
            related_object_type="master_video",
            related_object_id=str(video.id),
            status=BackgroundJobState.QUEUED,
            progress_percent=0,
            message="Reload queued",
        )
        try:
            async_result = download_youtube_video.delay(video.id)
        except Exception as exc:  # noqa: BLE001
            video.download_status = ProcessingState.FAILED
            video.download_error_message = f"Failed to enqueue reload task: {exc}"
            video.save(update_fields=["download_status", "download_error_message", "updated_at"])
            job.status = BackgroundJobState.FAILED
            job.error_message = str(exc)
            job.message = "Failed to enqueue reload task"
            job.save(update_fields=["status", "error_message", "message", "updated_at"])
            messages.error(request, "Reload could not be queued.")
            return redirect(_safe_next_url(request, fallback_url))

        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])

        messages.success(request, "Reload queued.")
        return redirect(_safe_next_url(request, fallback_url))


class MasterVideoJobStatusView(LoginRequiredMixin, View):
    def get(self, request, pk: int):
        video = get_object_or_404(MasterVideo, pk=pk, owner=request.user)
        job = (
            BackgroundJob.objects.filter(
                user=request.user,
                related_object_type="master_video",
                related_object_id=str(video.id),
                job_type__in=ACTIVE_MASTER_VIDEO_JOB_TYPES,
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
        video = get_object_or_404(MasterVideo, pk=pk, owner=request.user)
        uploaded_file = request.FILES.get("thumbnail_file")
        if not uploaded_file:
            return JsonResponse({"ok": False, "error": "썸네일 파일을 선택해주세요."}, status=400)

        preferred_name = (request.POST.get("thumbnail_filename") or "").strip()
        _save_thumbnail_url(
            request=request,
            video=video,
            uploaded_file=uploaded_file,
            preferred_name=preferred_name,
        )

        update_fields = ["custom_thumbnail_file", "updated_at"]
        if "thumbnail_description" in request.POST:
            video.custom_thumbnail_description = (request.POST.get("thumbnail_description") or "").strip()
            update_fields.append("custom_thumbnail_description")

        video.save(update_fields=update_fields)
        return JsonResponse(
            {
                "ok": True,
                "thumbnail_url": video.thumbnail,
                "thumbnail_description": video.custom_thumbnail_description,
                "thumbnail_file_name": Path(video.custom_thumbnail_file.name).name if video.custom_thumbnail_file else "",
            }
        )


class MasterVideoFetchInfoView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)

        raw_url = (payload.get("url") or "").strip()
        if not raw_url:
            return JsonResponse({"ok": False, "error": "URL을 입력해주세요."}, status=400)

        try:
            normalized = normalize_youtube_input(raw_url)
        except InvalidYouTubeInput as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)

        existing = MasterVideo.objects.filter(
            owner=request.user,
            youtube_video_id=normalized.youtube_video_id,
            is_active=True,
        ).first()
        if existing:
            return JsonResponse(
                {
                    "ok": True,
                    "exists": True,
                    "id": existing.id,
                    "video_id": existing.youtube_video_id,
                    "title": existing.title,
                    "description": existing.description,
                    "thumbnail_url": existing.thumbnail_url or existing.thumbnail,
                    "duration": existing.duration_seconds or 0,
                    "channel": existing.channel_name,
                }
            )

        metadata = _fetch_youtube_metadata(normalized)
        if metadata is None:
            return JsonResponse({"ok": False, "error": "영상 정보를 가져오지 못했습니다."}, status=400)

        duration = _coerce_duration_seconds(metadata.get("duration"))

        return JsonResponse(
            {
                "ok": True,
                "exists": False,
                "video_id": normalized.youtube_video_id,
                "title": metadata.get("title") or f"Video {normalized.youtube_video_id}",
                "description": (metadata.get("description") or "")[:3000],
                "thumbnail_url": metadata.get("thumbnail") or normalized.youtube_url,
                "duration": duration if isinstance(duration, int) else 0,
                "channel": metadata.get("uploader") or metadata.get("channel") or "",
            }
        )


class MasterVideoSaveAjaxView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)

        raw_url = (payload.get("url") or "").strip()
        try:
            normalized = normalize_youtube_input(raw_url)
        except InvalidYouTubeInput as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)

        metadata = _fill_missing_youtube_metadata(
            normalized,
            {
                "title": (payload.get("title") or "").strip() or f"Video {normalized.youtube_video_id}",
                "description": (payload.get("description") or "").strip(),
                "thumbnail_url": (payload.get("thumbnail_url") or "").strip(),
                "duration": payload.get("duration") or 0,
                "channel": (payload.get("channel") or "").strip(),
            },
        )
        defaults = {
            "source_type": MasterVideoSourceType.YOUTUBE,
            "youtube_url": normalized.youtube_url,
            "title": (metadata.get("title") or "").strip() or f"Video {normalized.youtube_video_id}",
            "description": (metadata.get("description") or "").strip(),
            "thumbnail_url": (metadata.get("thumbnail_url") or "").strip(),
            "duration_seconds": _coerce_duration_seconds(metadata.get("duration")) or None,
            "channel_name": (metadata.get("channel") or "").strip(),
            "download_status": ProcessingState.QUEUED,
        }

        video, created = MasterVideo.objects.get_or_create(
            owner=request.user,
            youtube_video_id=normalized.youtube_video_id,
            defaults=defaults,
        )

        if not created:
            updated = False
            for field_name in ("youtube_url", "title", "description", "thumbnail_url", "channel_name"):
                new_value = defaults[field_name]
                if new_value and getattr(video, field_name) != new_value:
                    setattr(video, field_name, new_value)
                    updated = True
            if defaults["duration_seconds"] and video.duration_seconds != defaults["duration_seconds"]:
                video.duration_seconds = defaults["duration_seconds"]
                updated = True
            if updated:
                video.save(update_fields=["youtube_url", "title", "description", "thumbnail_url", "channel_name", "duration_seconds", "updated_at"])
            if not video.saved_thumbnail_file:
                if _save_remote_thumbnail_file(video):
                    video.save(update_fields=["saved_thumbnail_file", "updated_at"])
            return JsonResponse({"ok": True, "id": video.id, "created": False})

        if _save_remote_thumbnail_file(video):
            video.save(update_fields=["saved_thumbnail_file", "updated_at"])

        ok, error_message = _enqueue_linked_video(video, request_user=request.user, queue_message="Queued for source video import")
        if not ok:
            return JsonResponse({"ok": False, "error": error_message or "Failed to queue source video import."}, status=500)

        return JsonResponse({"ok": True, "id": video.id, "created": True})


class MasterVideoAjaxUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        video = get_object_or_404(MasterVideo, pk=pk, owner=request.user, is_active=True)
        title = (request.POST.get("title") or "").strip()
        if title:
            video.title = title
        video.description = (request.POST.get("description") or "").strip()

        category = (request.POST.get("category") or "").strip()
        valid_categories = {choice for choice, _ in video._meta.get_field("category").choices}
        if category in valid_categories:
            video.category = category

        reset_thumb = request.POST.get("reset_thumbnail") == "1"
        thumb_file = request.FILES.get("custom_thumbnail")
        if reset_thumb:
            _delete_thumbnail_field(video.custom_thumbnail_file)
        elif thumb_file:
            _save_thumbnail_url(request=request, video=video, uploaded_file=thumb_file)

        video.save(update_fields=["title", "description", "category", "custom_thumbnail_file", "updated_at"])
        return JsonResponse({"ok": True, "thumbnail": video.thumbnail, "title": video.title, "category": video.category})


class MasterVideoThumbnailProxyView(LoginRequiredMixin, View):
    def get(self, request, pk: int):
        video = get_object_or_404(MasterVideo, pk=pk, owner=request.user, is_active=True)
        for field in (video.custom_thumbnail_file, video.saved_thumbnail_file):
            if not field:
                continue
            path = Path(field.path)
            if path.exists():
                content_type = "image/webp" if path.suffix.lower() == ".webp" else "image/jpeg"
                with open(path, "rb") as file_handle:
                    return HttpResponse(file_handle.read(), content_type=content_type, headers={"Cache-Control": "public,max-age=86400"})
        if video.thumbnail_url:
            return HttpResponseRedirect(video.thumbnail_url)
        raise Http404
