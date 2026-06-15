import re
from urllib.parse import quote

import requests
from django.db import transaction
from django.utils.html import strip_tags

from core.models import ImdbDramaEpisodeCache, ImdbDramaSeriesCache


IMDB_ID_RE = re.compile(r"^tt\d{7,10}$", re.IGNORECASE)
CINEMETA_META_URL = "https://v3-cinemeta.strem.io/meta/series/{imdb_id}.json"
CINEMETA_SEARCH_URL = "https://v3-cinemeta.strem.io/catalog/series/top/search={query}.json"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
}


class ImdbDramaLookupError(Exception):
    pass


def build_stream_url(imdb_id: str, season_number: int, episode_number: int) -> str:
    return f"https://vidfast.pro/tv/{imdb_id}/{season_number}/{episode_number}?autoPlay=true"


def normalize_imdb_id(value: str) -> str:
    candidate = str(value or "").strip()
    if not IMDB_ID_RE.match(candidate):
        return ""
    return candidate.lower()


def search_imdb_drama_catalog(query: str) -> dict:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("검색어를 입력해주세요.")

    imdb_id = normalize_imdb_id(normalized_query)
    if imdb_id:
        cached_series = _get_cached_series(imdb_id)
        selected_source = "cache" if cached_series and cached_series.episodes.exists() else "fetched"
        series = cached_series if cached_series and cached_series.episodes.exists() else _ensure_cached_series(imdb_id)
        return {
            "query": normalized_query,
            "selected": build_series_detail_payload(series),
            "selected_source": selected_source,
            "results": [build_series_summary_payload(series, source="cache")],
        }

    cached_matches = _search_cached_series(normalized_query)
    if cached_matches:
        return {
            "query": normalized_query,
            "selected": build_series_detail_payload(cached_matches[0]),
            "selected_source": "cache",
            "results": [build_series_summary_payload(item, source="cache") for item in cached_matches],
        }

    external_matches = _search_cinemeta_series(normalized_query)
    if not external_matches:
        return {
            "query": normalized_query,
            "selected": None,
            "selected_source": "",
            "results": [],
        }

    selected_series = _ensure_cached_series(external_matches[0]["imdb_id"])
    results = []
    for item in external_matches[:8]:
        if item["imdb_id"] == selected_series.imdb_id:
            results.append(build_series_summary_payload(selected_series, source="fetched"))
            continue
        results.append(item)

    return {
        "query": normalized_query,
        "selected": build_series_detail_payload(selected_series),
        "selected_source": "fetched",
        "results": results,
    }


def build_series_summary_payload(series: ImdbDramaSeriesCache, *, source: str = "cache") -> dict:
    return {
        "imdb_id": series.imdb_id,
        "title": series.title or series.imdb_id,
        "poster_url": series.poster_url or "",
        "summary": series.summary or "",
        "source": source,
    }


def build_series_detail_payload(
    series: ImdbDramaSeriesCache,
    *,
    selected_season: int | None = None,
    selected_episode: int | None = None,
) -> dict:
    episode_rows = list(series.episodes.all().order_by("season_number", "episode_number"))
    if not episode_rows:
        raise ImdbDramaLookupError("저장된 에피소드 정보가 없습니다.")

    episodes_by_season: dict[str, list[dict]] = {}
    season_numbers: list[int] = []

    for row in episode_rows:
        season_key = str(row.season_number)
        if season_key not in episodes_by_season:
            episodes_by_season[season_key] = []
            season_numbers.append(row.season_number)
        episodes_by_season[season_key].append(
            {
                "season_number": row.season_number,
                "episode_number": row.episode_number,
                "episode_title": row.episode_title or f"Episode {row.episode_number}",
                "stream_url": row.stream_url,
                "resolved_m3u8_url": row.resolved_m3u8_url or "",
                "resolved_source_available": bool(row.resolved_m3u8_url),
                "label": f"S{row.season_number}E{row.episode_number} · {row.episode_title or f'Episode {row.episode_number}'}",
            }
        )

    default_season = selected_season if selected_season in season_numbers else season_numbers[0]
    season_episodes = episodes_by_season[str(default_season)]
    valid_episode_numbers = [item["episode_number"] for item in season_episodes]
    default_episode = selected_episode if selected_episode in valid_episode_numbers else valid_episode_numbers[0]
    selected_episode_payload = next(
        item for item in season_episodes if item["episode_number"] == default_episode
    )

    return {
        "imdb_id": series.imdb_id,
        "title": series.title or series.imdb_id,
        "poster_url": series.poster_url or "",
        "summary": series.summary or "",
        "seasons": [
            {
                "value": season_number,
                "label": f"Season {season_number}",
            }
            for season_number in season_numbers
        ],
        "episodes": season_episodes,
        "episodes_by_season": episodes_by_season,
        "selected_season": default_season,
        "selected_episode": default_episode,
        "selected_episode_title": selected_episode_payload["episode_title"],
        "selected_stream_url": selected_episode_payload["stream_url"],
        "selected_resolved_m3u8_url": selected_episode_payload["resolved_m3u8_url"],
        "selected_resolved_source_available": selected_episode_payload["resolved_source_available"],
    }


def _ensure_cached_series(imdb_id: str) -> ImdbDramaSeriesCache:
    cached_series = _get_cached_series(imdb_id)
    if cached_series and cached_series.episodes.exists():
        return cached_series

    detail = _fetch_cinemeta_series_detail(imdb_id)
    return _persist_series_payload(detail)


def _search_cached_series(query: str) -> list[ImdbDramaSeriesCache]:
    normalized_query = _normalize_title_key(query)
    rows = list(
        ImdbDramaSeriesCache.objects.prefetch_related("episodes")
        .filter(title__icontains=query)
        .order_by("title", "imdb_id")[:8]
    )
    return sorted(
        rows,
        key=lambda row: (
            0 if _normalize_title_key(row.title) == normalized_query else 1,
            0 if _normalize_title_key(row.title).startswith(normalized_query) else 1,
            row.title.lower(),
            row.imdb_id,
        ),
    )


def _normalize_title_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _search_cinemeta_series(query: str) -> list[dict]:
    response = requests.get(
        CINEMETA_SEARCH_URL.format(query=quote(query)),
        headers=REQUEST_HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    metas = payload.get("metas") or []
    results = []
    seen_imdb_ids = set()

    for item in metas:
        imdb_id = normalize_imdb_id(item.get("imdb_id") or item.get("id") or "")
        if not imdb_id or imdb_id in seen_imdb_ids:
            continue
        if item.get("type") and item["type"] != "series":
            continue
        seen_imdb_ids.add(imdb_id)
        results.append(
            {
                "imdb_id": imdb_id,
                "title": (item.get("name") or "").strip() or imdb_id,
                "poster_url": (item.get("poster") or item.get("background") or "").strip(),
                "summary": strip_tags(item.get("description") or "").strip(),
                "source": "external",
            }
        )

    return results


def _fetch_cinemeta_series_detail(imdb_id: str) -> dict:
    response = requests.get(
        CINEMETA_META_URL.format(imdb_id=imdb_id),
        headers=REQUEST_HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    meta = payload.get("meta") or {}
    if not meta:
        raise ImdbDramaLookupError("외부 드라마 정보를 찾지 못했습니다.")

    title = (meta.get("name") or "").strip() or imdb_id
    poster_url = (meta.get("poster") or meta.get("background") or "").strip()
    summary = strip_tags(meta.get("description") or "").strip()
    raw_episodes = meta.get("videos") or []

    episodes = []
    seen_pairs = set()
    for item in raw_episodes:
        season_number = _coerce_positive_int(item.get("season"))
        episode_number = _coerce_positive_int(item.get("episode") or item.get("number"))
        if season_number is None or episode_number is None:
            continue
        key = (season_number, episode_number)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        episode_title = (
            strip_tags(item.get("name") or item.get("title") or "").strip()
            or f"Episode {episode_number}"
        )
        episodes.append(
            {
                "season_number": season_number,
                "episode_number": episode_number,
                "episode_title": episode_title,
                "stream_url": build_stream_url(imdb_id, season_number, episode_number),
            }
        )

    episodes.sort(key=lambda item: (item["season_number"], item["episode_number"]))
    if not episodes:
        raise ImdbDramaLookupError("외부 드라마 에피소드 정보를 찾지 못했습니다.")

    return {
        "imdb_id": imdb_id,
        "title": title,
        "poster_url": poster_url,
        "summary": summary,
        "episodes": episodes,
    }


def _persist_series_payload(payload: dict) -> ImdbDramaSeriesCache:
    imdb_id = normalize_imdb_id(payload.get("imdb_id") or "")
    if not imdb_id:
        raise ImdbDramaLookupError("유효한 IMDb ID가 없습니다.")

    with transaction.atomic():
        series, _created = ImdbDramaSeriesCache.objects.update_or_create(
            imdb_id=imdb_id,
            defaults={
                "title": payload.get("title") or imdb_id,
                "poster_url": payload.get("poster_url") or "",
                "summary": payload.get("summary") or "",
            },
        )
        ImdbDramaEpisodeCache.objects.filter(series=series).delete()
        ImdbDramaEpisodeCache.objects.bulk_create(
            [
                ImdbDramaEpisodeCache(
                    series=series,
                    season_number=item["season_number"],
                    episode_number=item["episode_number"],
                    episode_title=item.get("episode_title") or "",
                    stream_url=item["stream_url"],
                )
                for item in payload.get("episodes") or []
            ]
        )

    return ImdbDramaSeriesCache.objects.prefetch_related("episodes").get(pk=series.pk)


def _get_cached_series(imdb_id: str) -> ImdbDramaSeriesCache | None:
    return (
        ImdbDramaSeriesCache.objects.prefetch_related("episodes")
        .filter(imdb_id=imdb_id)
        .first()
    )


def _coerce_positive_int(value) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None
    if parsed < 1:
        return None
    return parsed
