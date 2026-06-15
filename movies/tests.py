from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Movie, SearchQuery
from .views import extract_tmdb_id, extract_year, search_tmdb_web


TMDB_SEARCH_HTML = """
<html>
  <body>
    <div class="comp:media-card w-full">
      <a href="/movie/278-the-shawshank-redemption">
        <img src="https://media.themoviedb.org/t/p/w94_and_h141_face/poster.jpg" alt="쇼생크 탈출">
      </a>
      <a href="/movie/278-the-shawshank-redemption">
        <h2><span>쇼생크 탈출</span> <span>(The Shawshank Redemption)</span></h2>
      </a>
      <span class="release_date">1월 28, 1995</span>
      <p>촉망받는 은행 간부 앤디 듀프레인은 누명을 쓴다.</p>
    </div>
  </body>
</html>
"""


class FakeResponse:
    text = TMDB_SEARCH_HTML

    def raise_for_status(self):
        return None


class MoviesFlowTests(TestCase):
    def test_navbar_has_movies_main_menu(self):
        response = self.client.get(reverse("landing"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Movies")
        self.assertContains(response, reverse("movies:search"))

    def test_search_page_requires_login(self):
        response = self.client.get(reverse("movies:search"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("platform_auth:login"), response["Location"])

    def test_search_page_renders_for_authenticated_user(self):
        user = get_user_model().objects.create_user(username="movie-user", password="pw123456")
        self.client.force_login(user)

        response = self.client.get(reverse("movies:search"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Movie picks")
        self.assertContains(response, 'data-search-url="/movies/api/search/"')
        self.assertContains(response, 'data-watch-url-template="/movies/watch/__TMDB__/"')

    def test_extract_tmdb_id_and_year(self):
        self.assertEqual(extract_tmdb_id("/movie/278-the-shawshank-redemption"), "278")
        self.assertIsNone(extract_tmdb_id("/movie/top-rated"))
        self.assertEqual(extract_year("1월 28, 1995"), 1995)
        self.assertIsNone(extract_year("개봉일 없음"))

    @patch("movies.views.requests.get", return_value=FakeResponse())
    def test_search_tmdb_web_parses_movie_cards(self, mock_get):
        results = search_tmdb_web("the shawshank redemption")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["tmdb_id"], "278")
        self.assertEqual(results[0]["year"], 1995)
        self.assertEqual(results[0]["player_url"], "https://www.vidsrc.win/watch/278")
        self.assertIn("쇼생크 탈출", results[0]["title"])
        mock_get.assert_called_once()

    @patch("movies.views.search_tmdb_web")
    def test_search_api_uses_tmdb_on_cache_miss(self, mock_search):
        mock_search.return_value = [
            {
                "title": "쇼생크 탈출 (The Shawshank Redemption)",
                "year": 1995,
                "url": "https://www.themoviedb.org/movie/278-the-shawshank-redemption",
                "thumbnail": "https://media.themoviedb.org/poster.jpg",
                "large_cover": "https://media.themoviedb.org/poster.jpg",
                "rating": None,
                "genres": [],
                "summary": "촉망받는 은행 간부 앤디 듀프레인은 누명을 쓴다.",
                "tmdb_id": "278",
                "tmdb_url": "https://www.themoviedb.org/movie/278-the-shawshank-redemption",
                "player_url": "https://www.vidsrc.win/watch/278",
                "torrents": [],
            }
        ]

        response = self.client.get(reverse("movies:api-search"), {"query": "shawshank"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["from_cache"])
        self.assertEqual(data["official"], [])
        self.assertEqual(data["api"], [])
        self.assertEqual(data["tmdb"][0]["tmdb_id"], "278")
        self.assertTrue(Movie.objects.filter(source="tmdb", tmdb_id="278").exists())

    @patch("movies.views.search_tmdb_web")
    def test_search_api_returns_cache_without_external_lookup(self, mock_search):
        search_query = SearchQuery.objects.create(query="shawshank")
        Movie.objects.create(
            search_query=search_query,
            source="tmdb",
            title="쇼생크 탈출",
            year=1995,
            url="https://www.themoviedb.org/movie/278-the-shawshank-redemption",
            tmdb_id="278",
        )

        response = self.client.get(reverse("movies:api-search"), {"query": "shawshank"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["from_cache"])
        self.assertEqual(data["tmdb"][0]["tmdb_id"], "278")
        self.assertEqual(data["tmdb"][0]["player_url"], "https://www.vidsrc.win/watch/278")
        mock_search.assert_not_called()

    def test_watch_page_uses_tmdb_player_without_sandbox(self):
        response = self.client.get(reverse("movies:watch", kwargs={"tmdb_id": "278"}))
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("https://www.vidsrc.win/watch/278", html)
        self.assertNotIn("sandbox=", html)
