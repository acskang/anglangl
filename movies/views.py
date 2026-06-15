import logging
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .models import Movie, SearchQuery
from .services.title_ko2en import ko_title_to_en_title


logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["GET"])
def search_page(request):
    recent_queries = SearchQuery.objects.all()[:10]
    return render(request, "movies/search.html", {"recent_queries": recent_queries})


@require_http_methods(["GET"])
def translate_title_ko2en(request):
    movie_nm_ko = request.GET.get("title", "").strip()
    if not movie_nm_ko:
        return JsonResponse({"error": "영화 제목을 입력해주세요."}, status=400)

    api_key = getattr(settings, "KOBIS_API_KEY", "")
    if not api_key:
        return JsonResponse({"error": "KOBIS API 키가 설정되지 않았습니다."}, status=503)

    try:
        en_title, candidates = ko_title_to_en_title(api_key=api_key, movie_nm_ko=movie_nm_ko)
    except requests.HTTPError as exc:
        return JsonResponse({"error": f"KOBIS 응답 오류: {exc}"}, status=502)
    except requests.RequestException as exc:
        return JsonResponse({"error": f"네트워크 오류: {exc}"}, status=502)

    if not en_title:
        return JsonResponse({"error": "영문 제목을 찾지 못했습니다."}, status=404)

    preview_candidates = [
        {
            "movieNm": movie.get("movieNm"),
            "movieNmEn": movie.get("movieNmEn"),
            "openDt": movie.get("openDt"),
            "prdtYear": movie.get("prdtYear"),
        }
        for movie in candidates[:5]
    ]
    return JsonResponse({"en_title": en_title, "candidates": preview_candidates})


def watch_movie(request, tmdb_id):
    movie = Movie.objects.filter(tmdb_id=tmdb_id).first()
    return render(
        request,
        "movies/watch.html",
        {
            "tmdb_id": tmdb_id,
            "movie_title": movie.title if movie else "영화 시청",
            "player_url": f"https://www.vidsrc.win/watch/{tmdb_id}",
        },
    )


@require_http_methods(["GET"])
def search_movies(request):
    query = request.GET.get("query", "").strip()
    if not query:
        return JsonResponse({"error": "검색어를 입력해주세요."}, status=400)

    try:
        search_query = SearchQuery.objects.get(query=query)
        search_query.search_count += 1
        search_query.save()
        movies_from_db = Movie.objects.filter(search_query=search_query).order_by("id")
        if movies_from_db.exists():
            results = {"from_cache": True, "official": [], "api": [], "tmdb": []}
            for movie in movies_from_db:
                movie_data = {
                    "title": movie.title,
                    "year": movie.year,
                    "url": movie.url,
                    "thumbnail": movie.thumbnail,
                    "large_cover": movie.large_cover,
                    "rating": movie.rating,
                    "genres": movie.genres,
                    "summary": movie.summary,
                    "imdb_code": movie.imdb_code,
                    "imdb_url": movie.imdb_url,
                    "tmdb_id": movie.tmdb_id,
                    "tmdb_url": movie.tmdb_url,
                    "player_url": movie.player_url,
                    "torrents": movie.torrents,
                }
                if movie.source == "tmdb":
                    results["tmdb"].append(movie_data)
                elif movie.source == "official":
                    results["official"].append(movie_data)
                else:
                    results["api"].append(movie_data)
            return JsonResponse(results)
    except SearchQuery.DoesNotExist:
        search_query = SearchQuery.objects.create(query=query)

    tmdb_results = search_tmdb_web(query)

    with transaction.atomic():
        for movie_data in tmdb_results:
            Movie.objects.update_or_create(
                title=movie_data["title"],
                year=movie_data.get("year"),
                source="tmdb",
                search_query=search_query,
                defaults={
                    "url": movie_data["url"],
                    "thumbnail": movie_data.get("thumbnail"),
                    "large_cover": movie_data.get("large_cover"),
                    "rating": movie_data.get("rating"),
                    "genres": movie_data.get("genres", []),
                    "summary": movie_data.get("summary"),
                    "tmdb_id": movie_data.get("tmdb_id"),
                    "torrents": movie_data.get("torrents", []),
                },
            )

    return JsonResponse({"from_cache": False, "official": [], "api": [], "tmdb": tmdb_results})


def search_tmdb_web(query):
    base_url = "https://www.themoviedb.org"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        response = requests.get(f"{base_url}/search/movie", params={"query": query}, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("TMDB search failed for query %r: %s", query, exc)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen_ids = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        tmdb_id = extract_tmdb_id(href)
        if not tmdb_id or tmdb_id in seen_ids:
            continue

        card = link.find_parent("div", class_=lambda value: value and "comp:media-card" in value)
        if card is None:
            continue

        title_elem = card.find("h2")
        title = title_elem.get_text(" ", strip=True) if title_elem else link.get_text(" ", strip=True)
        if not title:
            continue

        seen_ids.add(tmdb_id)
        release_elem = card.find(class_="release_date")
        release_text = release_elem.get_text(" ", strip=True) if release_elem else ""
        summary_elem = card.find("p")
        img = card.find("img")
        thumbnail = img.get("src") if img else ""
        movie_url = urljoin(base_url, href)

        results.append(
            {
                "title": title,
                "year": extract_year(release_text),
                "url": movie_url,
                "thumbnail": thumbnail,
                "large_cover": thumbnail,
                "rating": None,
                "genres": [],
                "summary": summary_elem.get_text(" ", strip=True) if summary_elem else "",
                "tmdb_id": tmdb_id,
                "tmdb_url": movie_url,
                "player_url": f"https://www.vidsrc.win/watch/{tmdb_id}",
                "torrents": [],
            }
        )

    return results


def extract_tmdb_id(href):
    match = re.match(r"^/movie/(\d+)(?:-|$)", href or "")
    if match:
        return match.group(1)
    return None


def extract_year(text):
    match = re.search(r"\b(19|20)\d{2}\b", text or "")
    if match:
        return int(match.group(0))
    return None


def get_recent_searches(request):
    recent = SearchQuery.objects.all()[:20]
    return JsonResponse([{"query": item.query, "count": item.search_count} for item in recent], safe=False)
