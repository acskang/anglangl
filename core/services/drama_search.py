import requests
from bs4 import BeautifulSoup
from django.db import transaction

from core.models import DramaEpisodeCache, DramaSeriesCache

YTS_TV_BASE_URL = "https://ytstv.hair"
YTS_TV_SEARCH_URL = f"{YTS_TV_BASE_URL}/searchtv"
YTS_TV_WATCH_URL = f"{YTS_TV_BASE_URL}/watch-tv/"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": YTS_TV_BASE_URL,
}


def _build_embed_url(tmdb: str, season: str, episode: str) -> str:
    return f"https://vidapi.xyz/embedmulti/tv/{tmdb}&s={season}&e={episode}"


def _to_int(value: str, default: int = 1) -> int:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return default


def _fetch_watch_page(tmdb: str, season: str = "1", episode: str = "1") -> BeautifulSoup:
    response = requests.post(
        YTS_TV_WATCH_URL,
        data={
            "tmdb": tmdb,
            "season": season,
            "episode": episode,
        },
        headers=REQUEST_HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def _extract_title(soup: BeautifulSoup) -> str:
    title_text = ""
    if soup.title and soup.title.string:
        title_text = soup.title.string.replace(" - YTS TV", "").strip()
    if not title_text:
        heading = soup.select_one(".heading-name a")
        title_text = heading.get_text(strip=True) if heading else "드라마"
    return title_text or "드라마"


def _extract_seasons(soup: BeautifulSoup, selected_season: str) -> list[dict]:
    seasons = []
    seen_seasons = set()
    for season_item in soup.select("li.list"):
        form_node = season_item.find("form")
        if form_node is None:
            continue
        season_input = form_node.find("input", attrs={"name": "season"})
        episode_input = form_node.find("input", attrs={"name": "episode"})
        season_value = (season_input.get("value", "") if season_input else "").strip()
        episode_value = (episode_input.get("value", "") if episode_input else "").strip() or "1"
        if not season_value or season_value in seen_seasons:
            continue
        seen_seasons.add(season_value)
        seasons.append(
            {
                "season": season_value,
                "episode": episode_value,
                "label": f"Season {season_value}",
                "selected": season_value == selected_season,
            }
        )
    return seasons


def _extract_episodes(soup: BeautifulSoup, title_text: str, tmdb: str, selected_season: str, selected_episode: str) -> list[dict]:
    episodes = []
    seen_episode_keys = set()
    for anchor in soup.select("a.btn-eps"):
        form_node = anchor.find_next_sibling("form")
        if form_node is None:
            continue
        episode_input = form_node.find("input", attrs={"name": "episode"})
        season_input = form_node.find("input", attrs={"name": "season"})
        tmdb_input = form_node.find("input", attrs={"name": "tmdb"})
        episode_value = (episode_input.get("value", "") if episode_input else "").strip()
        season_value = (season_input.get("value", "") if season_input else "").strip() or selected_season
        tmdb_value = (tmdb_input.get("value", "") if tmdb_input else "").strip() or tmdb
        key = (season_value, episode_value)
        if not episode_value or key in seen_episode_keys:
            continue
        seen_episode_keys.add(key)
        label = anchor.get_text(" ", strip=True).replace("\xa0", " ")
        episodes.append(
            {
                "episode": episode_value,
                "season": season_value,
                "label": label,
                "selected": episode_value == selected_episode and season_value == selected_season,
                "embed_url": _build_embed_url(tmdb_value, season_value, episode_value),
                "title": f"{title_text} · S{season_value}E{episode_value}",
            }
        )
    return episodes


def _parse_watch_page(tmdb: str, selected_season: str, selected_episode: str) -> dict:
    soup = _fetch_watch_page(tmdb, selected_season, selected_episode)
    title_text = _extract_title(soup)
    seasons = _extract_seasons(soup, selected_season)
    all_episodes = _extract_episodes(soup, title_text, tmdb, selected_season, selected_episode)

    for season in seasons:
        season_value = season["season"]
        if season_value == selected_season:
            continue
        season_soup = _fetch_watch_page(tmdb, season_value, "1")
        all_episodes.extend(_extract_episodes(season_soup, title_text, tmdb, season_value, "1"))

    episodes = [
        episode for episode in sorted(
            all_episodes,
            key=lambda item: (_to_int(item["season"]), _to_int(item["episode"]))
        )
        if episode["season"] == selected_season
    ]

    seasons = []
    seen_seasons = set()
    for episode in sorted(all_episodes, key=lambda item: (_to_int(item["season"]), _to_int(item["episode"]))):
        season_value = str(episode["season"])
        if season_value in seen_seasons:
            continue
        seen_seasons.add(season_value)
        seasons.append(
            {
                "season": season_value,
                "episode": "1",
                "label": f"Season {season_value}",
                "selected": season_value == selected_season,
            }
        )

    return {
        "tmdb": tmdb,
        "title": title_text or "드라마",
        "selected_season": selected_season,
        "selected_episode": selected_episode,
        "seasons": seasons,
        "episodes": episodes,
        "all_episodes": all_episodes,
    }


def _build_detail_from_cache(series: DramaSeriesCache, selected_season: str, selected_episode: str) -> dict:
    episode_rows = list(series.episodes.all().order_by("season_number", "episode_number"))
    if not episode_rows:
        return {}

    seasons = []
    seen_seasons = set()
    episodes = []
    for row in episode_rows:
        season_value = str(row.season_number)
        episode_value = str(row.episode_number)
        if season_value not in seen_seasons:
            seen_seasons.add(season_value)
            seasons.append(
                {
                    "season": season_value,
                    "episode": "1",
                    "label": f"Season {season_value}",
                    "selected": season_value == selected_season,
                }
            )
        if season_value != selected_season:
            continue
        episodes.append(
            {
                "episode": episode_value,
                "season": season_value,
                "label": row.label or f"EP{episode_value}",
                "selected": episode_value == selected_episode,
                "embed_url": row.embed_url,
                "title": f"{series.title or '드라마'} · S{season_value}E{episode_value}",
            }
        )

    return {
        "tmdb": series.tmdb,
        "title": series.title or "드라마",
        "selected_season": selected_season,
        "selected_episode": selected_episode,
        "seasons": seasons,
        "episodes": episodes,
    }


def _persist_detail_cache(payload: dict) -> None:
    tmdb = str(payload.get("tmdb") or "").strip()
    if not tmdb:
        return

    with transaction.atomic():
        series, _ = DramaSeriesCache.objects.update_or_create(
            tmdb=tmdb,
            defaults={"title": payload.get("title") or ""},
        )
        DramaEpisodeCache.objects.filter(series=series).delete()
        DramaEpisodeCache.objects.bulk_create(
            [
                DramaEpisodeCache(
                    series=series,
                    season_number=_to_int(item.get("season"), 1),
                    episode_number=_to_int(item.get("episode"), 1),
                    label=item.get("label") or "",
                    embed_url=item.get("embed_url") or "",
                )
                for item in payload.get("all_episodes") or payload.get("episodes") or []
                if item.get("embed_url")
            ]
        )


def search_dramas(query: str) -> dict:
    normalized_query = (query or "").strip()
    if not normalized_query:
        raise ValueError("검색어를 입력해주세요.")

    try:
        response = requests.post(
            YTS_TV_SEARCH_URL,
            data={
                "q": normalized_query,
                "category": "tv",
            },
            headers=REQUEST_HEADERS,
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException:
        return {
            "query": normalized_query,
            "results": [],
        }

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen_keys = set()

    for item in soup.select(".ml-item"):
        title_node = item.select_one(".mli-info h2")
        image_node = item.select_one("img")
        year_node = item.select_one(".mli-quality")
        rating_node = item.select_one(".mli-imdbnum")
        form_node = item.find("form")

        if form_node is None:
            continue

        tmdb_input = form_node.find("input", attrs={"name": "tmdb"})
        season_input = form_node.find("input", attrs={"name": "season"})
        episode_input = form_node.find("input", attrs={"name": "episode"})
        tmdb = (tmdb_input.get("value", "") if tmdb_input else "").strip()
        season = (season_input.get("value", "") if season_input else "").strip() or "1"
        episode = (episode_input.get("value", "") if episode_input else "").strip() or "1"

        if not tmdb:
            continue

        key = (tmdb, season, episode)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        thumbnail = (image_node.get("src", "") if image_node else "").strip()
        if thumbnail.startswith("/"):
            thumbnail = f"{YTS_TV_BASE_URL}{thumbnail}"

        title = (title_node.get_text(strip=True) if title_node else "").strip() or "제목 없음"
        year_text = (year_node.get_text(strip=True) if year_node else "").strip()
        rating_text = (rating_node.get_text(strip=True) if rating_node else "").strip()

        results.append(
            {
                "title": title,
                "thumbnail": thumbnail,
                "year": year_text,
                "rating": rating_text,
                "tmdb": tmdb,
                "season": season,
                "episode": episode,
                "embed_url": _build_embed_url(tmdb, season, episode),
            }
        )

    return {
        "query": normalized_query,
        "results": results[:24],
    }


def get_drama_detail(tmdb: str, *, season: str = "1", episode: str = "1") -> dict:
    normalized_tmdb = str(tmdb or "").strip()
    selected_season = str(season or "1").strip() or "1"
    selected_episode = str(episode or "1").strip() or "1"
    if not normalized_tmdb:
        raise ValueError("드라마 식별자가 없습니다.")

    cached_series = DramaSeriesCache.objects.prefetch_related("episodes").filter(tmdb=normalized_tmdb).first()
    if cached_series and cached_series.episodes.exists():
        return _build_detail_from_cache(cached_series, selected_season, selected_episode)

    payload = _parse_watch_page(normalized_tmdb, selected_season, selected_episode)
    _persist_detail_cache(payload)
    return payload
