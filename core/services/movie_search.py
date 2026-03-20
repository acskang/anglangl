import re

import requests
from bs4 import BeautifulSoup
from django.conf import settings

from dramaNlearn.services.title_ko2en import ko_title_to_en_title


KOREAN_RE = re.compile(r"[가-힣]")
YTS_OFFICIAL_BASE_URL = "https://www.yts-official.cc"
YTS_API_URLS = (
    "https://yts.mx/api/v2/list_movies.json",
    "https://yts.lt/api/v2/list_movies.json",
    "https://yts.am/api/v2/list_movies.json",
)
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def search_movies(query: str) -> dict:
    normalized_query = (query or "").strip()
    if not normalized_query:
        raise ValueError("검색어를 입력해주세요.")

    effective_query = normalized_query
    translated_title = None
    translation_candidates = []
    official_results = search_yts_official(normalized_query)
    api_results = search_yts_api(normalized_query)

    if not official_results and not api_results and KOREAN_RE.search(normalized_query):
        translated_title, translation_candidates = translate_title_ko2en(normalized_query)
        if translated_title:
            effective_query = translated_title
            official_results = search_yts_official(translated_title)
            api_results = search_yts_api(translated_title)

    return {
        "query": normalized_query,
        "effective_query": effective_query,
        "translated_query": translated_title,
        "translation_candidates": translation_candidates[:5],
        "official": official_results,
        "api": api_results,
    }


def translate_title_ko2en(movie_nm_ko: str):
    api_key = getattr(settings, "KOBIS_API_KEY", "")
    if not api_key:
        return None, []

    en_title, candidates = ko_title_to_en_title(
        api_key=api_key,
        movie_nm_ko=movie_nm_ko,
    )
    return en_title, [
        {
            "movieNm": movie.get("movieNm"),
            "movieNmEn": movie.get("movieNmEn"),
            "openDt": movie.get("openDt"),
            "prdtYear": movie.get("prdtYear"),
        }
        for movie in candidates
    ]


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
