from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clips.models import Clip, ClipSourceType
from core.models import ImdbDramaEpisodeCache, ImdbDramaSeriesCache, ProcessingState
from dramaNlearn.models import Video
from study.models import StudyMaterial
from videos.models import MasterVideo, MasterVideoSourceType


class PlayerPageViewTests(TestCase):
    def test_landing_page_has_primary_navigation_dropdowns(self):
        response = self.client.get(reverse("landing"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="youtubeNavbarDropdown"', html=False)
        self.assertContains(response, "Youtube")
        self.assertContains(response, reverse("videos:create-youtube"))
        self.assertContains(response, reverse("videos:linked-list"))
        self.assertContains(response, reverse("clips:bulk-upload"))
        self.assertContains(response, reverse("clips:batch-list"))
        self.assertContains(response, reverse("clips:album-upload"))
        self.assertContains(response, reverse("videos:thumbnail-album"))
        self.assertContains(response, "블로그편집")
        self.assertContains(response, "썸네일 이미지 앨범")
        self.assertContains(response, "클립 업로드")
        self.assertContains(response, "업로드 배치")
        self.assertContains(response, "이미지 등록")
        self.assertContains(response, 'id="adminNavbarDropdown"', html=False)
        self.assertContains(response, reverse("clips:create"))
        self.assertContains(response, "자막클립생성")
        self.assertContains(response, 'id="materialsNavbarDropdown"', html=False)
        self.assertContains(response, "Materials")
        self.assertContains(response, reverse("study:list"))
        self.assertContains(response, reverse("study:explore"))
        self.assertContains(response, "Drama")
        self.assertContains(response, "드라마보기")
        self.assertContains(response, reverse("dramaNlearn:imdb"))
        self.assertContains(response, "IMDB")
        self.assertContains(response, "드라마URL생성")
        self.assertContains(response, 'data-auth-open="login"', html=False)
        self.assertContains(response, 'data-auth-open="signup"', html=False)
        self.assertNotContains(response, 'id="downloadNavbarDropdown"', html=False)
        self.assertNotContains(response, ">Videos<", html=False)
        self.assertNotContains(response, ">Clips<", html=False)
        self.assertNotContains(response, ">Album<", html=False)
        self.assertNotContains(response, "flash-wrap", html=False)
        self.assertNotContains(response, 'alert alert-', html=False)
        self.assertNotContains(response, "ThePeach")

    def test_player_page_is_available(self):
        response = self.client.get(reverse("player"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Player")

    def test_player_page_has_imdb_selection_button(self):
        response = self.client.get(reverse("player"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-bs-target="#imdbListModal"', html=False)
        self.assertContains(response, ">IMDB<", html=False)
        self.assertContains(response, "?source=imdb&imdb_id=")
        self.assertContains(response, 'id="playerFrameSaveBtn"', html=False)

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
        self.assertContains(response, reverse("study:create"))
        self.assertContains(response, "source_type=drama_video")
        self.assertContains(response, f"drama_video_id={latest.id}")

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
        self.assertContains(response, reverse("study:create"))
        self.assertContains(response, "source_type=master_video")
        self.assertContains(response, f"master_video_id={video.id}")

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
        self.assertContains(response, reverse("study:create"))
        self.assertContains(response, "source_type=clip")
        self.assertContains(response, f"clip_id={clip.id}")

    def test_player_clip_source_can_create_and_open_study_material(self):
        user = get_user_model().objects.create_user(username="clipflow", password="pw123456")
        self.client.force_login(user)
        master = MasterVideo.objects.create(
            owner=user,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Flow Parent Video",
            video_file="videos/files/flow-parent.mp4",
            duration_seconds=90,
            download_status=ProcessingState.READY,
        )
        clip = Clip.objects.create(
            owner=user,
            source_type=ClipSourceType.EXTRACTED,
            master_video=master,
            title="Flow Clip",
            subtitle="First line\nSecond line",
            start_time_seconds=5,
            end_time_seconds=15,
            duration_seconds=10,
            clip_file="uploaded_clips/user_1/batch_none/flow-clip.mp4",
            file_status=ProcessingState.READY,
        )

        player_response = self.client.get(reverse("player"), {"source": "clip", "id": clip.id})

        self.assertEqual(player_response.status_code, 200)
        create_url = reverse("study:create") + f"?source_type=clip&clip_id={clip.id}"
        self.assertContains(player_response, create_url)

        response = self.client.post(
            create_url,
            data={
                "title": "Flow Clip Material",
                "material_type": "shadowing_script",
                "purpose": "shadowing",
                "difficulty": "intermediate",
                "visibility": "private",
                "generated_content": "First line\nSecond line",
                "editable_notes": "clip note",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        material = StudyMaterial.objects.get(owner=user, title="Flow Clip Material")
        self.assertEqual(material.source_type, "clip")
        self.assertEqual(material.source_clip, clip)
        self.assertContains(response, "Flow Clip Material")
        self.assertContains(response, "First line")

    def test_player_master_video_source_can_create_and_open_study_material(self):
        user = get_user_model().objects.create_user(username="videoflow", password="pw123456")
        self.client.force_login(user)
        video = MasterVideo.objects.create(
            owner=user,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="flowvideo123",
            youtube_url="https://youtube.com/watch?v=flowvideo123",
            title="Flow Master Video",
            duration_seconds=180,
            download_status=ProcessingState.READY,
            video_file="videos/files/flow-master.mp4",
            hls_manifest_file="master_videos/hls/user_1/flow/index.m3u8",
        )

        player_response = self.client.get(reverse("player"), {"source": "video", "id": video.id})

        self.assertEqual(player_response.status_code, 200)
        create_url = reverse("study:create") + f"?source_type=master_video&master_video_id={video.id}"
        self.assertContains(player_response, create_url)

        response = self.client.post(
            create_url,
            data={
                "title": "Flow Video Listening Note",
                "material_type": "learning_note",
                "purpose": "listening",
                "difficulty": "intermediate",
                "visibility": "private",
                "generated_content": "Video-backed listening note",
                "editable_notes": "video note",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        material = StudyMaterial.objects.get(owner=user, title="Flow Video Listening Note")
        self.assertEqual(material.source_type, "master_video")
        self.assertEqual(material.source_master_video, video)
        self.assertContains(response, "Flow Video Listening Note")
        self.assertContains(response, "Video-backed listening note")

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
    def test_player_movie_search_api_returns_translation_candidates_before_yts_search_for_korean_query(
        self,
        translate_mock,
        official_mock,
        api_mock,
    ):
        translate_mock.return_value = (
            "Parasite",
            [{"movieNm": "기생충", "movieNmEn": "Parasite", "thumbnail": "https://img.example/parasite.jpg", "imdb_code": "tt6751668"}],
        )

        response = self.client.get(reverse("player-movie-search"), {"query": "기생충"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["effective_query"], "기생충")
        self.assertEqual(payload["translated_query"], "Parasite")
        self.assertEqual(payload["translation_candidates"][0]["movieNm"], "기생충")
        self.assertEqual(payload["translation_candidates"][0]["imdb_code"], "tt6751668")
        self.assertTrue(payload["needs_title_selection"])
        self.assertEqual(payload["official"], [])
        self.assertEqual(payload["api"], [])
        official_mock.assert_not_called()

    @patch("core.services.movie_search.search_yts_api")
    @patch("core.services.movie_search.search_yts_official")
    def test_player_movie_search_api_searches_selected_english_title_when_skip_flag_is_set(self, official_mock, api_mock):
        official_mock.return_value = [
            {"title": "Parasite", "year": 2019, "url": "https://yts.example/parasite", "thumbnail": ""}
        ]
        api_mock.return_value = []

        response = self.client.get(
            reverse("player-movie-search"),
            {"query": "Parasite", "skip_korean_title_translation": "1"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["needs_title_selection"])
        self.assertEqual(payload["effective_query"], "Parasite")
        official_mock.assert_called_once_with("Parasite")
        api_mock.assert_called_once_with("Parasite")

    def test_player_movie_search_api_requires_query(self):
        response = self.client.get(reverse("player-movie-search"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "검색어를 입력해주세요.")

    def test_player_imdb_search_api_returns_cached_series(self):
        series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt1190634",
            title="The Boys",
            poster_url="https://images.example.com/the-boys.jpg",
            summary="Superhero satire.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=series,
            season_number=1,
            episode_number=1,
            episode_title="Pilot",
            stream_url="https://vidfast.pro/tv/tt1190634/1/1?autoPlay=true",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=series,
            season_number=1,
            episode_number=2,
            episode_title="Cherry",
            stream_url="https://vidfast.pro/tv/tt1190634/1/2?autoPlay=true",
        )

        response = self.client.get(reverse("player-imdb-search"), {"query": "boys"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["query"], "boys")
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["imdb_id"], "tt1190634")
        self.assertEqual(payload["results"][0]["title"], "The Boys")
        self.assertEqual(payload["results"][0]["season_count"], 1)
        self.assertEqual(payload["results"][0]["episode_count"], 2)

    def test_player_imdb_search_api_excludes_series_without_saved_stream_url(self):
        valid_series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt1190634",
            title="The Boys",
            poster_url="https://images.example.com/the-boys.jpg",
            summary="Superhero satire.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=valid_series,
            season_number=1,
            episode_number=1,
            episode_title="Pilot",
            stream_url="https://vidfast.pro/tv/tt1190634/1/1?autoPlay=true",
        )
        invalid_series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt28793987",
            title="The Fiery Priest",
            poster_url="https://images.example.com/fiery-priest.jpg",
            summary="Action comedy.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=invalid_series,
            season_number=2,
            episode_number=3,
            episode_title="Someday",
            stream_url="",
        )

        response = self.client.get(reverse("player-imdb-search"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["imdb_id"], "tt1190634")
        self.assertEqual(payload["results"][0]["title"], "The Boys")

    def test_player_imdb_detail_api_returns_cached_episode_play_options(self):
        series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt1190634",
            title="The Boys",
            poster_url="https://images.example.com/the-boys.jpg",
            summary="Superhero satire.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=series,
            season_number=1,
            episode_number=1,
            episode_title="Pilot",
            stream_url="https://vidfast.pro/tv/tt1190634/1/1?autoPlay=true",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=series,
            season_number=1,
            episode_number=2,
            episode_title="Cherry",
            stream_url="https://vidfast.pro/tv/tt1190634/1/2?autoPlay=true",
        )

        response = self.client.get(
            reverse("player-imdb-detail"),
            {"imdb_id": "tt1190634", "season": "1", "episode": "2"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["imdb_id"], "tt1190634")
        self.assertEqual(payload["title"], "The Boys")
        self.assertEqual(payload["selected_season"], 1)
        self.assertEqual(payload["selected_episode"], 2)
        self.assertEqual(payload["selected_episode_title"], "Cherry")
        self.assertEqual(payload["selected_stream_url"], "https://vidfast.pro/tv/tt1190634/1/2?autoPlay=true")

    def test_player_imdb_detail_api_rejects_series_without_saved_stream_url(self):
        series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt28793987",
            title="The Fiery Priest",
            poster_url="https://images.example.com/fiery-priest.jpg",
            summary="Action comedy.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=series,
            season_number=2,
            episode_number=3,
            episode_title="Someday",
            stream_url="",
        )

        response = self.client.get(
            reverse("player-imdb-detail"),
            {"imdb_id": "tt28793987", "season": "2", "episode": "3"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "저장된 IMDb 드라마를 찾지 못했습니다.")

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
        self.assertContains(response, reverse("study:create"))
        self.assertContains(response, "source_type=movie")
        self.assertContains(response, "imdb=tt0111161")
        self.assertContains(response, "title=%EC%87%BC%EC%83%9D%ED%81%AC")
        self.assertContains(response, "이미지 저장 불가")
        self.assertContains(response, "외부 embed 재생은 브라우저 보안 정책 때문에 정지 화면 캡처를 지원하지 않습니다.")
        self.assertContains(response, 'id="playerFrameSaveBtn"', html=False)
        self.assertContains(response, 'id="playerCaptionSizeSelect"', html=False)

    def test_player_page_can_render_imdb_drama_embed_source(self):
        user = get_user_model().objects.create_user(username="dramaviewer", password="pw123456")
        self.client.force_login(user)
        stream_url = "https://vidfast.pro/tv/tt1190634/1/1?autoPlay=true"

        response = self.client.get(
            reverse("player"),
            {"source": "drama", "embed": stream_url, "title": "The Boys · S1E1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_kind"], "drama")
        self.assertEqual(response.context["player_source_type"], "embed")
        self.assertContains(response, "tt1190634/1/1")
        self.assertContains(response, "The Boys")
        self.assertContains(response, ">IMDB<", html=False)

    def test_player_page_falls_back_to_embed_for_unresolved_imdb_episode(self):
        user = get_user_model().objects.create_user(username="imdbfallback", password="pw123456")
        self.client.force_login(user)
        series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt1190634",
            title="The Boys",
            poster_url="https://images.example.com/the-boys.jpg",
            summary="Superhero satire.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=series,
            season_number=1,
            episode_number=1,
            episode_title="Pilot",
            stream_url="https://vidfast.pro/tv/tt1190634/1/1?autoPlay=true",
        )

        response = self.client.get(
            reverse("player"),
            {"source": "imdb", "imdb_id": "tt1190634", "season": "1", "episode": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_kind"], "imdb")
        self.assertEqual(response.context["player_source_type"], "embed")
        self.assertContains(response, "tt1190634/1/1")
        self.assertContains(response, "embed 재생으로 대체됩니다.")

    def test_player_page_updates_last_played_at_for_imdb_series(self):
        user = get_user_model().objects.create_user(username="imdbrecent", password="pw123456")
        self.client.force_login(user)
        series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt1190634",
            title="The Boys",
            poster_url="https://images.example.com/the-boys.jpg",
            summary="Superhero satire.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=series,
            season_number=1,
            episode_number=1,
            episode_title="Pilot",
            stream_url="https://vidfast.pro/tv/tt1190634/1/1?autoPlay=true",
        )

        response = self.client.get(
            reverse("player"),
            {"source": "imdb", "imdb_id": "tt1190634", "season": "1", "episode": "1"},
        )

        self.assertEqual(response.status_code, 200)
        series.refresh_from_db()
        self.assertIsNotNone(series.last_played_at)

    def test_player_page_can_auto_open_imdb_modal_from_query(self):
        user = get_user_model().objects.create_user(username="imdbmodal", password="pw123456")
        self.client.force_login(user)

        response = self.client.get(
            reverse("player"),
            {"imdb_modal": "1", "imdb_id": "tt1190634"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "var PLAYER_IMDB_AUTO_OPEN = true;", html=False)
        self.assertContains(response, 'var PLAYER_IMDB_AUTO_OPEN_ID = "tt1190634";', html=False)

    def test_player_page_does_not_fallback_to_other_media_for_imdb_without_saved_stream_url(self):
        user = get_user_model().objects.create_user(username="imdbguard", password="pw123456")
        self.client.force_login(user)
        fallback_video = Video.objects.create(
            title="Ready Drama",
            source_url="https://send2video.com/watch/ready",
            owner=user,
            m3u8_url="https://example.com/ready.m3u8",
            status="ready",
        )
        series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt28793987",
            title="The Fiery Priest",
            poster_url="https://images.example.com/fiery-priest.jpg",
            summary="Action comedy.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=series,
            season_number=2,
            episode_number=3,
            episode_title="Someday",
            stream_url="",
        )

        response = self.client.get(
            reverse("player"),
            {"source": "imdb", "imdb_id": "tt28793987", "season": "2", "episode": "3"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_kind"], "imdb")
        self.assertIsNone(response.context["selected_item"])
        self.assertEqual(response.context["player_source_type"], "")
        self.assertContains(response, "Player의 IMDb 재생은 저장된 URL이 있는 드라마에서만 선택할 수 있습니다.")
        self.assertContains(response, "저장된 IMDb URL이 없습니다.")
        self.assertContains(response, "IMDb 화면에서 먼저 저장된 드라마를 만든 뒤, Player의 IMDB 목록에서 선택해 주세요.")
        self.assertNotContains(response, "https://example.com/ready.m3u8")

    def test_player_page_uses_cached_hls_for_imdb_episode_when_available(self):
        user = get_user_model().objects.create_user(username="imdbhls", password="pw123456")
        self.client.force_login(user)
        series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt1190634",
            title="The Boys",
            poster_url="https://images.example.com/the-boys.jpg",
            summary="Superhero satire.",
        )
        episode = ImdbDramaEpisodeCache.objects.create(
            series=series,
            season_number=1,
            episode_number=2,
            episode_title="Cherry",
            stream_url="https://vidfast.pro/tv/tt1190634/1/2?autoPlay=true",
            resolved_m3u8_url="https://cdn.example.com/the-boys/s01e02/master.m3u8",
            subtitle_tracks='[{"src":"https://cdn.example.com/the-boys/s01e02/en.vtt","label":"English","srclang":"en","kind":"subtitles","default":true}]',
        )

        response = self.client.get(
            reverse("player"),
            {"source": "imdb", "imdb_id": "tt1190634", "season": "1", "episode": "2"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_kind"], "imdb")
        self.assertEqual(response.context["player_source_type"], "hls")
        self.assertEqual(response.context["player_source_url"], episode.resolved_m3u8_url)
        self.assertIn("English", response.context["subtitle_tracks_json"])
        self.assertNotContains(response, "embed 재생으로 대체됩니다.")

    def test_player_movie_source_can_create_and_open_study_material(self):
        user = get_user_model().objects.create_user(username="movieflow", password="pw123456")
        self.client.force_login(user)

        player_response = self.client.get(
            reverse("player"),
            {"source": "movie", "imdb": "tt1375666", "title": "인셉션"},
        )

        self.assertEqual(player_response.status_code, 200)
        create_url = reverse("study:create") + "?source_type=movie&imdb=tt1375666&title=%EC%9D%B8%EC%85%89%EC%85%98"
        self.assertContains(player_response, create_url)

        response = self.client.post(
            reverse("study:create") + "?source_type=movie&imdb=tt1375666&title=%EC%9D%B8%EC%85%89%EC%85%98",
            data={
                "title": "인셉션 표현 노트",
                "material_type": "expressions",
                "purpose": "speaking",
                "difficulty": "intermediate",
                "visibility": "private",
                "generated_content": "Dream within a dream",
                "editable_notes": "movie note",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        material = StudyMaterial.objects.get(owner=user, title="인셉션 표현 노트")
        self.assertEqual(material.source_type, "movie")
        self.assertEqual(material.imdb_code, "tt1375666")
        self.assertContains(response, "인셉션 표현 노트")
        self.assertContains(response, "Dream within a dream")
