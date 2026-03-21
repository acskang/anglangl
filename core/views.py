import json
import mimetypes
from pathlib import Path
from types import SimpleNamespace

import requests
from django.conf import settings
from django.db import connections
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView

from clips.models import Clip
from clips.services.ffmpeg import FfmpegError, FfmpegService
from core.models import ProcessingState
from core.services.movie_search import search_movies
from dramaNlearn.models import Video as DramaVideo
from videos.models import MasterVideo


class LandingPageView(TemplateView):
    template_name = "landing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_authenticated:
            context["recently_studied_clips"] = []
            context["latest_public_clips"] = []
        else:
            context["latest_public_clips"] = []
            context["recently_studied_clips"] = []
        return context


class PlayerPageView(TemplateView):
    template_name = "player/home.html"

    def _build_file_playback_profile(self, media_field) -> dict:
        if not media_field:
            return {}

        extension = Path(media_field.name or "").suffix.lower()
        mime_type, _ = mimetypes.guess_type(media_field.name or "")
        profile = {
            "extension": extension,
            "mime_type": mime_type or "",
            "container": "",
            "video_codec": "",
            "audio_codec": "",
        }

        file_path = getattr(media_field, "path", "")
        if not file_path:
            return profile

        try:
            media_profile = FfmpegService().probe_media_profile(Path(file_path))
        except (FfmpegError, NotImplementedError, OSError):
            return profile

        profile["container"] = media_profile.container
        profile["video_codec"] = media_profile.video_codec
        profile["audio_codec"] = media_profile.audio_codec
        return profile

    def _get_video_items(self):
        return MasterVideo.objects.select_related("owner").filter(
            download_status=ProcessingState.READY,
            is_active=True,
        ).exclude(video_file="")

    def _get_clip_items(self):
        return Clip.objects.select_related("owner", "master_video").filter(
            file_status=ProcessingState.READY,
            is_active=True,
        ).exclude(clip_file="")

    def _get_m3u8_items(self):
        return DramaVideo.objects.select_related("owner").filter(status="ready").exclude(m3u8_url="")

    def _resolve_selected_item(self):
        source_kind = self.request.GET.get("source") or "m3u8"
        source_id = self.request.GET.get("id")
        movie_imdb = (self.request.GET.get("imdb") or "").strip()
        movie_title = (self.request.GET.get("title") or "").strip()

        video_items = self._get_video_items()
        clip_items = self._get_clip_items()
        m3u8_items = self._get_m3u8_items()

        selected_kind = source_kind
        selected_item = None

        if source_kind == "movie" and movie_imdb:
            selected_kind = "movie"
            selected_item = SimpleNamespace(
                title=movie_title or "영화 시청",
                imdb_code=movie_imdb,
                owner_id=None,
            )
            return selected_kind, selected_item, video_items, clip_items, m3u8_items

        if source_id and source_id.isdigit():
            if source_kind == "video":
                selected_item = video_items.filter(pk=int(source_id)).first()
            elif source_kind == "clip":
                selected_item = clip_items.filter(pk=int(source_id)).first()
            else:
                selected_kind = "m3u8"
                selected_item = m3u8_items.filter(pk=int(source_id)).first()

        if selected_item is None:
            # Prefer HLS sources first because they fit browser playback and
            # long-form streaming better than direct file delivery in this project.
            if m3u8_items.exists():
                selected_kind = "m3u8"
                selected_item = m3u8_items.first()
            elif video_items.exists():
                selected_kind = "video"
                selected_item = video_items.first()
            elif clip_items.exists():
                selected_kind = "clip"
                selected_item = clip_items.first()

        return selected_kind, selected_item, video_items, clip_items, m3u8_items

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_kind, selected_item, video_items, clip_items, m3u8_items = self._resolve_selected_item()
        subtitle_tracks = []
        player_source_url = ""
        player_source_type = ""
        playback_profile = {}

        if selected_item is not None:
            if selected_kind == "movie":
                player_source_url = f"https://vidsrc.net/embed/movie/{selected_item.imdb_code}"
                player_source_type = "embed"
            elif selected_kind == "m3u8":
                player_source_url = selected_item.m3u8_url
                player_source_type = "hls"
                subtitle_tracks = selected_item.subtitle_tracks_list()
            elif selected_kind == "video":
                if selected_item.hls_manifest_file:
                    player_source_url = selected_item.hls_manifest_file.url
                    player_source_type = "hls"
                else:
                    player_source_url = selected_item.video_file.url
                    player_source_type = "file"
                    playback_profile = self._build_file_playback_profile(selected_item.video_file)
            elif selected_kind == "clip":
                if selected_item.hls_manifest_file:
                    player_source_url = selected_item.hls_manifest_file.url
                    player_source_type = "hls"
                else:
                    player_source_url = selected_item.clip_file.url
                    player_source_type = "file"
                    playback_profile = self._build_file_playback_profile(selected_item.clip_file)

        context["selected_kind"] = selected_kind
        context["selected_item"] = selected_item
        context["video_items"] = video_items[:100]
        context["clip_items"] = clip_items[:100]
        context["m3u8_items"] = m3u8_items[:100]
        context["player_source_url"] = player_source_url
        context["player_source_type"] = player_source_type
        context["player_playback_profile_json"] = json.dumps(playback_profile, ensure_ascii=False)
        context["can_play"] = self.request.user.is_authenticated
        can_update_thumbnail = (
            self.request.user.is_authenticated
            and selected_kind == "video"
            and selected_item is not None
            and selected_item.owner_id == self.request.user.id
        )
        context["can_update_thumbnail"] = can_update_thumbnail
        context["thumbnail_update_url"] = reverse("videos:thumbnail-update", args=[selected_item.id]) if can_update_thumbnail else ""
        context["subtitle_tracks_json"] = json.dumps(subtitle_tracks, ensure_ascii=False)
        return context


@require_GET
def player_movie_search_api(request):
    query = request.GET.get("query", "").strip()
    if not query:
        return JsonResponse({"error": "검색어를 입력해주세요."}, status=400)

    try:
        results = search_movies(query)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except requests.HTTPError as exc:
        return JsonResponse({"error": f"영화 검색 응답 오류: {exc}"}, status=502)
    except requests.RequestException as exc:
        return JsonResponse({"error": f"영화 검색 네트워크 오류: {exc}"}, status=502)

    return JsonResponse(results)


@require_GET
def health_check(request):
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        database_ok = True
        database_error = ""
    except Exception as exc:
        database_ok = False
        database_error = str(exc)

    payload = {
        "status": "ok" if database_ok else "degraded",
        "service": "anglangl",
        "settings_module": settings.SETTINGS_MODULE,
        "database": {
            "ok": database_ok,
            "engine": settings.DATABASES["default"]["ENGINE"],
            "error": database_error,
        },
    }
    return JsonResponse(payload, status=200 if database_ok else 503)
