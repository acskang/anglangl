from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clips.models import Clip, ClipSourceType
from core.models import ProcessingState
from dramaNlearn.models import Video
from videos.models import MasterVideo, MasterVideoSourceType


class PlayerPageViewTests(TestCase):
    def test_player_page_is_available(self):
        response = self.client.get(reverse("player"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Player")

    def test_player_page_uses_latest_ready_drama_video(self):
        user = get_user_model().objects.create_user(username="viewer", password="pw123456")
        Video.objects.create(
            title="Old Ready",
            source_url="https://send2video.com/old",
            owner=user,
            m3u8_url="https://example.com/old.m3u8",
            status="ready",
        )
        latest = Video.objects.create(
            title="Latest Ready",
            source_url="https://send2video.com/latest",
            owner=user,
            m3u8_url="https://example.com/latest.m3u8",
            status="ready",
        )

        response = self.client.get(reverse("player"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_item"], latest)
        self.assertEqual(response.context["selected_kind"], "m3u8")
        self.assertEqual(response.context["player_source_type"], "hls")
        self.assertContains(response, "Latest Ready")
        self.assertContains(response, ">HLS<", html=False)

    def test_player_page_can_select_master_video(self):
        user = get_user_model().objects.create_user(username="owner", password="pw123456")
        video = MasterVideo.objects.create(
            owner=user,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Master Upload",
            video_file="videos/files/sample.mp4",
            hls_manifest_file="master_videos/hls/user_1/1/index.m3u8",
            download_status=ProcessingState.READY,
        )

        response = self.client.get(reverse("player"), {"source": "video", "id": video.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_item"], video)
        self.assertEqual(response.context["selected_kind"], "video")
        self.assertEqual(response.context["player_source_type"], "hls")
        self.assertContains(response, ">video<", html=False)
        self.assertContains(response, ">local<", html=False)

    def test_player_page_can_select_clip(self):
        user = get_user_model().objects.create_user(username="owner2", password="pw123456")
        master = MasterVideo.objects.create(
            owner=user,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Parent Video",
            video_file="videos/files/parent.mp4",
            duration_seconds=120,
            download_status=ProcessingState.READY,
        )
        clip = Clip.objects.create(
            owner=user,
            source_type=ClipSourceType.EXTRACTED,
            master_video=master,
            title="Test Clip",
            start_time_seconds=0,
            end_time_seconds=10,
            duration_seconds=10,
            clip_file="uploaded_clips/user_1/batch_none/clip.mp4",
            hls_manifest_file="clips/hls/user_1/clip_1/index.m3u8",
            file_status=ProcessingState.READY,
        )

        response = self.client.get(reverse("player"), {"source": "clip", "id": clip.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_item"], clip)
        self.assertEqual(response.context["selected_kind"], "clip")
        self.assertEqual(response.context["player_source_type"], "hls")
        self.assertContains(response, ">clip<", html=False)

    @patch("core.services.movie_search.search_yts_api")
    @patch("core.services.movie_search.search_yts_official")
    def test_player_movie_search_api_returns_results(self, official_mock, api_mock):
        official_mock.return_value = [
            {"title": "Inception", "year": 2010, "url": "https://yts.example/inception", "thumbnail": ""}
        ]
        api_mock.return_value = [
            {
                "title": "Inception",
                "year": 2010,
                "url": "https://yts-api.example/inception",
                "thumbnail": "",
                "large_cover": "",
                "rating": 8.8,
                "genres": ["Sci-Fi"],
                "summary": "dream",
                "imdb_code": "tt1375666",
                "imdb_url": "https://www.imdb.com/title/tt1375666/",
                "torrents": [],
            }
        ]

        response = self.client.get(reverse("player-movie-search"), {"query": "Inception"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["query"], "Inception")
        self.assertEqual(payload["effective_query"], "Inception")
        self.assertEqual(len(payload["official"]), 1)
        self.assertEqual(len(payload["api"]), 1)

    @patch("core.services.movie_search.search_yts_api")
    @patch("core.services.movie_search.search_yts_official")
    @patch("core.services.movie_search.translate_title_ko2en")
    def test_player_movie_search_api_translates_korean_query_when_no_direct_results(
        self,
        translate_mock,
        official_mock,
        api_mock,
    ):
        official_mock.side_effect = [
            [],
            [{"title": "Parasite", "year": 2019, "url": "https://yts.example/parasite", "thumbnail": ""}],
        ]
        api_mock.side_effect = [[], []]
        translate_mock.return_value = ("Parasite", [{"movieNm": "기생충", "movieNmEn": "Parasite"}])

        response = self.client.get(reverse("player-movie-search"), {"query": "기생충"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["effective_query"], "Parasite")
        self.assertEqual(payload["translated_query"], "Parasite")
        self.assertEqual(payload["translation_candidates"][0]["movieNm"], "기생충")

    def test_player_movie_search_api_requires_query(self):
        response = self.client.get(reverse("player-movie-search"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "검색어를 입력해주세요.")

    def test_player_page_can_render_movie_embed_source(self):
        user = get_user_model().objects.create_user(username="movieviewer", password="pw123456")
        self.client.force_login(user)

        response = self.client.get(
            reverse("player"),
            {"source": "movie", "imdb": "tt0111161", "title": "쇼생크 탈출"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_kind"], "movie")
        self.assertEqual(response.context["player_source_type"], "embed")
        self.assertContains(response, "https://vidsrc.net/embed/movie/tt0111161")
        self.assertContains(response, "쇼생크 탈출")
