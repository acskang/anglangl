import requests


KOBIS_MOVIE_LIST_JSON = (
    "https://www.kobis.or.kr/kobisopenapi/webservice/rest/movie/searchMovieList.json"
)


def _norm(value: str) -> str:
    return "".join((value or "").split()).lower()


def fetch_movie_list(api_key: str, movie_nm: str, item_per_page: int = 20):
    response = requests.get(
        KOBIS_MOVIE_LIST_JSON,
        params={
            "key": api_key,
            "curPage": "1",
            "itemPerPage": str(item_per_page),
            "movieNm": movie_nm,
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("movieListResult", {}).get("movieList", []) or []


def pick_best_match(movie_nm_ko: str, movie_list):
    if not movie_list:
        return None

    target = _norm(movie_nm_ko)
    scored = []
    for movie in movie_list:
        ko_title = str(movie.get("movieNm", ""))
        ko_norm = _norm(ko_title)
        score = 100
        if ko_norm == target:
            score = 300
        elif target and (target in ko_norm or ko_norm in target):
            score = 200

        if str(movie.get("movieNmEn", "")).strip():
            score += 10
        if str(movie.get("openDt", "")).strip():
            score += 3
        scored.append((score, movie))

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def ko_title_to_en_title(api_key: str, movie_nm_ko: str, item_per_page: int = 20):
    movie_list = fetch_movie_list(api_key=api_key, movie_nm=movie_nm_ko, item_per_page=item_per_page)
    best = pick_best_match(movie_nm_ko, movie_list)
    if not best:
        return None, movie_list
    en_title = str(best.get("movieNmEn", "")).strip() or None
    return en_title, movie_list
