from typing import Any

import requests


KOBIS_MOVIE_LIST_JSON = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/movie/searchMovieList.json"


def _norm(value: str) -> str:
    return "".join(value.split()).lower()


def fetch_movie_list(
    *,
    api_key: str,
    movie_nm: str,
    cur_page: int = 1,
    item_per_page: int = 10,
    open_start_dt: str | None = None,
    open_end_dt: str | None = None,
    prdt_start_year: str | None = None,
    prdt_end_year: str | None = None,
) -> list[dict[str, Any]]:
    params = {
        "key": api_key,
        "curPage": str(cur_page),
        "itemPerPage": str(item_per_page),
        "movieNm": movie_nm,
    }
    if open_start_dt:
        params["openStartDt"] = open_start_dt
    if open_end_dt:
        params["openEndDt"] = open_end_dt
    if prdt_start_year:
        params["prdtStartYear"] = prdt_start_year
    if prdt_end_year:
        params["prdtEndYear"] = prdt_end_year

    response = requests.get(KOBIS_MOVIE_LIST_JSON, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    movie_list = data.get("movieListResult", {}).get("movieList", [])
    return movie_list if isinstance(movie_list, list) else []


def pick_best_match(movie_nm_ko: str, movie_list: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not movie_list:
        return None

    target = _norm(movie_nm_ko)
    scored = []
    for movie in movie_list:
        ko_title = str(movie.get("movieNm", ""))
        normalized_ko = _norm(ko_title)
        if normalized_ko == target:
            score = 300
        elif target and (target in normalized_ko or normalized_ko in target):
            score = 200
        else:
            score = 100
        if str(movie.get("movieNmEn", "")).strip():
            score += 10
        if str(movie.get("openDt", "")).strip():
            score += 3
        scored.append((score, movie))

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def ko_title_to_en_title(*, api_key: str, movie_nm_ko: str, item_per_page: int = 20):
    movie_list = fetch_movie_list(api_key=api_key, movie_nm=movie_nm_ko, item_per_page=item_per_page)
    best = pick_best_match(movie_nm_ko, movie_list)
    if not best:
        return None, movie_list
    return str(best.get("movieNmEn", "")).strip() or None, movie_list
