import json
import mimetypes
from pathlib import Path
from types import SimpleNamespace

import requests
from django.conf import settings
from django.db import connections
from django.db.models import Prefetch
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView

from clips.models import Clip
from clips.services.ffmpeg import FfmpegError, FfmpegService
from core.models import ImdbDramaEpisodeCache, ImdbDramaSeriesCache, ProcessingState
from core.services.drama_search import get_drama_detail, search_dramas
from core.services.movie_search import search_movies
from dramaNlearn.models import Video as DramaVideo
from dramaNlearn.services.imdb_lookup import (
    ImdbDramaLookupError,
    build_series_detail_payload,
    build_series_summary_payload,
    normalize_imdb_id,
)
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

    @staticmethod
    def _coerce_positive_int(value: str) -> int | None:
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError, AttributeError):
            return None
        return parsed if parsed > 0 else None

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
        drama_embed = (self.request.GET.get("embed") or "").strip()
        drama_title = (self.request.GET.get("title") or "").strip()
        imdb_id = normalize_imdb_id(self.request.GET.get("imdb_id", ""))
        imdb_season = self._coerce_positive_int(self.request.GET.get("season", ""))
        imdb_episode = self._coerce_positive_int(self.request.GET.get("episode", ""))

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

        if source_kind == "drama" and drama_embed:
            selected_kind = "drama"
            selected_item = SimpleNamespace(
                title=drama_title or "드라마 시청",
                embed_url=drama_embed,
                owner_id=None,
            )
            return selected_kind, selected_item, video_items, clip_items, m3u8_items

        if source_kind == "imdb" and imdb_id:
            episode_queryset = (
                ImdbDramaEpisodeCache.objects.select_related("series")
                .exclude(stream_url="")
                .filter(series__imdb_id=imdb_id)
            )
            if imdb_season is not None:
                episode_queryset = episode_queryset.filter(season_number=imdb_season)
            if imdb_episode is not None:
                episode_queryset = episode_queryset.filter(episode_number=imdb_episode)
            episode_row = episode_queryset.order_by("season_number", "episode_number").first()
            if episode_row is not None:
                episode_row.series.last_played_at = timezone.now()
                episode_row.series.save(update_fields=["last_played_at"])
                episode_label = (
                    f"S{episode_row.season_number}E{episode_row.episode_number}"
                    f" · {episode_row.episode_title or f'Episode {episode_row.episode_number}'}"
                )
                selected_kind = "imdb"
                selected_item = SimpleNamespace(
                    title=f"{episode_row.series.title or episode_row.series.imdb_id} · {episode_label}",
                    imdb_id=episode_row.series.imdb_id,
                    season_number=episode_row.season_number,
                    episode_number=episode_row.episode_number,
                    fallback_embed_url=episode_row.stream_url,
                    resolved_m3u8_url=episode_row.resolved_m3u8_url,
                    subtitle_tracks=episode_row.subtitle_tracks_list(),
                    resolution_cached=bool(episode_row.resolved_m3u8_url),
                    owner_id=None,
                )
                return selected_kind, selected_item, video_items, clip_items, m3u8_items
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
        player_imdb_auto_open = (self.request.GET.get("imdb_modal") or "").strip().lower() in {"1", "true", "yes", "open"}
        player_imdb_auto_open_id = normalize_imdb_id(self.request.GET.get("imdb_id", "")) if player_imdb_auto_open else ""
        subtitle_tracks = []
        player_source_url = ""
        player_source_type = ""
        playback_profile = {}
        player_notice_message = ""
        player_empty_title = "재생할 영상이 없습니다."
        player_empty_message = (
            "이 프로젝트는 장기적으로 HLS(m3u8)를 우선합니다. `HLS`, `video`, `clip` 목록에서 "
            "재생 가능한 항목을 선택하세요."
        )

        if selected_item is not None:
            if selected_kind == "movie":
                player_source_url = f"https://vidsrc.net/embed/movie/{selected_item.imdb_code}"
                player_source_type = "embed"
            elif selected_kind == "drama":
                player_source_url = selected_item.embed_url
                player_source_type = "embed"
            elif selected_kind == "imdb":
                if selected_item.resolution_cached:
                    player_source_url = selected_item.resolved_m3u8_url
                    player_source_type = "hls"
                    subtitle_tracks = selected_item.subtitle_tracks
                else:
                    player_source_url = selected_item.fallback_embed_url
                    player_source_type = "embed"
                    player_notice_message = (
                        "이 IMDb 에피소드는 아직 기존 Player용 HLS/자막 캐시가 없어 embed 재생으로 대체됩니다."
                    )
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
        elif selected_kind == "imdb":
            player_notice_message = "Player의 IMDb 재생은 저장된 URL이 있는 드라마에서만 선택할 수 있습니다."
            player_empty_title = "저장된 IMDb URL이 없습니다."
            player_empty_message = (
                "IMDb 화면에서 먼저 저장된 드라마를 만든 뒤, Player의 IMDB 목록에서 선택해 주세요."
            )

        context["selected_kind"] = selected_kind
        context["selected_item"] = selected_item
        context["video_items"] = video_items[:100]
        context["clip_items"] = clip_items[:100]
        context["m3u8_items"] = m3u8_items[:100]
        context["player_source_url"] = player_source_url
        context["player_source_type"] = player_source_type
        context["player_playback_profile_json"] = json.dumps(playback_profile, ensure_ascii=False)
        context["player_notice_message"] = player_notice_message
        context["player_empty_title"] = player_empty_title
        context["player_empty_message"] = player_empty_message
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
        context["player_imdb_auto_open"] = player_imdb_auto_open
        context["player_imdb_auto_open_id"] = player_imdb_auto_open_id
        return context


def _player_imdb_series_queryset():
    cached_episode_queryset = (
        ImdbDramaEpisodeCache.objects.exclude(stream_url="")
        .order_by("season_number", "episode_number")
    )
    return (
        ImdbDramaSeriesCache.objects.prefetch_related(
            Prefetch("episodes", queryset=cached_episode_queryset)
        )
        .filter(episodes__stream_url__gt="")
        .distinct()
    )


def _normalize_player_search_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _build_player_imdb_summary_payload(series: ImdbDramaSeriesCache) -> dict:
    payload = build_series_summary_payload(series, source="cache")
    episode_rows = list(series.episodes.all())
    payload["season_count"] = len({row.season_number for row in episode_rows})
    payload["episode_count"] = len(episode_rows)
    return payload


@require_GET
def player_movie_search_api(request):
    query = request.GET.get("query", "").strip()
    skip_korean_title_translation = request.GET.get("skip_korean_title_translation", "").strip() in {"1", "true", "yes"}
    if not query:
        return JsonResponse({"error": "검색어를 입력해주세요."}, status=400)

    try:
        results = search_movies(query, skip_korean_title_translation=skip_korean_title_translation)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except requests.HTTPError as exc:
        return JsonResponse({"error": f"영화 검색 응답 오류: {exc}"}, status=502)
    except requests.RequestException as exc:
        return JsonResponse({"error": f"영화 검색 네트워크 오류: {exc}"}, status=502)

    return JsonResponse(results)


@require_GET
def player_drama_search_api(request):
    query = request.GET.get("query", "").strip()
    if not query:
        return JsonResponse({"error": "검색어를 입력해주세요."}, status=400)

    try:
        results = search_dramas(query)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except requests.HTTPError as exc:
        return JsonResponse({"error": f"드라마 검색 응답 오류: {exc}"}, status=502)
    except requests.RequestException as exc:
        return JsonResponse({"error": f"드라마 검색 네트워크 오류: {exc}"}, status=502)

    return JsonResponse(results)


@require_GET
def player_drama_detail_api(request):
    tmdb = request.GET.get("tmdb", "").strip()
    season = request.GET.get("season", "").strip() or "1"
    episode = request.GET.get("episode", "").strip() or "1"
    if not tmdb:
        return JsonResponse({"error": "드라마 식별자가 없습니다."}, status=400)

    try:
        results = get_drama_detail(tmdb, season=season, episode=episode)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except requests.HTTPError as exc:
        return JsonResponse({"error": f"드라마 상세 응답 오류: {exc}"}, status=502)
    except requests.RequestException as exc:
        return JsonResponse({"error": f"드라마 상세 네트워크 오류: {exc}"}, status=502)

    return JsonResponse(results)


@require_GET
def player_imdb_search_api(request):
    query = request.GET.get("query", "").strip()
    queryset = _player_imdb_series_queryset()

    if query:
        imdb_id = normalize_imdb_id(query)
        if imdb_id:
            rows = list(queryset.filter(imdb_id=imdb_id))
        else:
            rows = list(queryset.filter(title__icontains=query)[:24])
            normalized_query = _normalize_player_search_key(query)
            rows.sort(
                key=lambda row: (
                    0 if _normalize_player_search_key(row.title) == normalized_query else 1,
                    0 if _normalize_player_search_key(row.title).startswith(normalized_query) else 1,
                    row.title.lower(),
                    row.imdb_id,
                )
            )
    else:
        rows = list(queryset.order_by("manual_order", "-updated_at", "title", "imdb_id")[:12])

    return JsonResponse(
        {
            "query": query,
            "results": [_build_player_imdb_summary_payload(row) for row in rows[:12]],
        }
    )


@require_GET
def player_imdb_detail_api(request):
    imdb_id = normalize_imdb_id(request.GET.get("imdb_id", ""))
    season = request.GET.get("season", "").strip()
    episode = request.GET.get("episode", "").strip()
    if not imdb_id:
        return JsonResponse({"error": "IMDb ID를 입력해주세요."}, status=400)

    series = _player_imdb_series_queryset().filter(imdb_id=imdb_id).first()
    if series is None:
        return JsonResponse({"error": "저장된 IMDb 드라마를 찾지 못했습니다."}, status=404)

    selected_season = int(season) if season.isdigit() else None
    selected_episode = int(episode) if episode.isdigit() else None
    try:
        payload = build_series_detail_payload(
            series,
            selected_season=selected_season,
            selected_episode=selected_episode,
        )
    except ImdbDramaLookupError as exc:
        return JsonResponse({"error": str(exc)}, status=404)

    payload["selected_source"] = "cache"
    return JsonResponse(payload)


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
