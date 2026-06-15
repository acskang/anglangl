import re

import requests
from bs4 import BeautifulSoup
from django.conf import settings

from dramaNlearn.services.title_ko2en import ko_title_to_en_title


KOREAN_RE = re.compile(r"[가-힣]")
DEFAULT_KOBIS_API_KEY = "05955d0620d1e271b88e8ea747711a78"
YTS_OFFICIAL_BASE_URL = "https://www.yts-official.cc"
YTS_API_URLS = (
    "https://yts.mx/api/v2/list_movies.json",
    "https://yts.lt/api/v2/list_movies.json",
    "https://yts.am/api/v2/list_movies.json",
)
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def _normalize_movie_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _pick_candidate_preview(title_en: str, prdt_year: str = "") -> dict:
    if not title_en:
        return {}

    candidates = search_yts_api(title_en)
    if not candidates:
        return {}

    target_key = _normalize_movie_key(title_en)
    target_year = str(prdt_year or "").strip()
    scored = []
    for item in candidates[:10]:
        movie_title = str(item.get("title") or "")
        movie_key = _normalize_movie_key(movie_title)
        score = 0
        if movie_key == target_key:
            score += 300
        elif target_key and (target_key in movie_key or movie_key in target_key):
            score += 200
        if target_year and str(item.get("year") or "") == target_year:
            score += 80
        if item.get("imdb_code"):
            score += 10
        scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    best = scored[0][1] if scored else {}
    return {
        "preview_title": best.get("title") or title_en,
        "thumbnail": best.get("large_cover") or best.get("thumbnail") or "",
        "imdb_code": best.get("imdb_code") or "",
        "preview_year": best.get("year"),
    }


def search_movies(query: str, *, skip_korean_title_translation: bool = False) -> dict:
    normalized_query = (query or "").strip()
    if not normalized_query:
        raise ValueError("검색어를 입력해주세요.")

    effective_query = normalized_query
    translated_title = None
    translation_candidates = []
    search_query = normalized_query
    needs_title_selection = False

    if KOREAN_RE.search(normalized_query) and not skip_korean_title_translation:
        translated_title, translation_candidates = translate_title_ko2en(normalized_query)
        if translation_candidates:
            needs_title_selection = True
            effective_query = normalized_query
            return {
                "query": normalized_query,
                "effective_query": effective_query,
                "translated_query": translated_title,
                "translation_candidates": translation_candidates[:5],
                "needs_title_selection": needs_title_selection,
                "official": [],
                "api": [],
            }

    official_results = search_yts_official(search_query)
    api_results = search_yts_api(search_query)

    return {
        "query": normalized_query,
        "effective_query": effective_query,
        "translated_query": translated_title,
        "translation_candidates": translation_candidates[:5],
        "needs_title_selection": needs_title_selection,
        "official": official_results,
        "api": api_results,
    }


def translate_title_ko2en(movie_nm_ko: str):
    api_key = getattr(settings, "KOBIS_API_KEY", "") or DEFAULT_KOBIS_API_KEY
    if not api_key:
        return None, []

    en_title, candidates = ko_title_to_en_title(
        api_key=api_key,
        movie_nm_ko=movie_nm_ko,
    )
    translated_candidates = []
    for movie in candidates[:5]:
        movie_nm_en = str(movie.get("movieNmEn") or "").strip()
        preview = _pick_candidate_preview(movie_nm_en, str(movie.get("prdtYear") or "").strip()) if movie_nm_en else {}
        translated_candidates.append(
            {
                "movieNm": movie.get("movieNm"),
                "movieNmEn": movie_nm_en,
                "openDt": movie.get("openDt"),
                "prdtYear": movie.get("prdtYear"),
                "thumbnail": preview.get("thumbnail", ""),
                "imdb_code": preview.get("imdb_code", ""),
                "preview_title": preview.get("preview_title", movie_nm_en),
                "preview_year": preview.get("preview_year"),
            }
        )
    return en_title, translated_candidates


def search_yts_official(query: str):
    try:
        response = requests.get(
            f"{YTS_OFFICIAL_BASE_URL}/ajax/search",
            params={"query": query},
            headers={
                **REQUEST_HEADERS,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": YTS_OFFICIAL_BASE_URL,
            },
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen_urls = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if "/movies/" not in href:
            continue

        full_url = href if href.startswith("http") else f"{YTS_OFFICIAL_BASE_URL}{href}"
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        image = link.find("img")
        thumbnail = image.get("src", "") if image else ""
        if thumbnail and not thumbnail.startswith("http"):
            thumbnail = f"{YTS_OFFICIAL_BASE_URL}{thumbnail}"

        title_element = link.find("div", class_="movie-title")
        year_element = link.find("div", class_="movie-year")
        year = None
        year_text = year_element.text.strip() if year_element else ""
        if year_text:
            try:
                year = int(year_text)
            except (TypeError, ValueError):
                year = None

        results.append(
            {
                "title": title_element.text.strip() if title_element else link.text.strip(),
                "year": year,
                "url": full_url,
                "thumbnail": thumbnail,
            }
        )

    return results


def search_yts_api(query: str):
    params = {
        "query_term": query,
        "limit": 30,
        "sort_by": "year",
        "order_by": "desc",
    }

    for api_url in YTS_API_URLS:
        try:
            response = requests.get(
                api_url,
                params=params,
                headers=REQUEST_HEADERS,
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException:
            continue

        data = response.json()
        movies = data.get("data", {}).get("movies") or []
        if not movies:
            continue

        return [
            {
                "title": movie.get("title"),
                "year": movie.get("year"),
                "url": movie.get("url"),
                "thumbnail": movie.get("medium_cover_image") or movie.get("small_cover_image") or "",
                "large_cover": movie.get("large_cover_image") or "",
                "rating": movie.get("rating"),
                "genres": movie.get("genres") or [],
                "summary": movie.get("summary") or "",
                "imdb_code": movie.get("imdb_code") or "",
                "imdb_url": f"https://www.imdb.com/title/{movie.get('imdb_code')}/" if movie.get("imdb_code") else "",
                "torrents": movie.get("torrents") or [],
            }
            for movie in movies
        ]

    return []
