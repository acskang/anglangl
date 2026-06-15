import json
from datetime import timedelta
from types import SimpleNamespace
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core.models import ImdbDramaEpisodeCache, ImdbDramaSeriesCache, ProcessingState
from dramaNlearn.services.stream_access import prepare_drama_extract_source
from dramaNlearn.services.imdb_lookup import search_imdb_drama_catalog
from videos.models import MasterVideo, MasterVideoSourceType
from .models import ThumbnailAsset, Video
from .tasks import extract_drama_video
from workers.models import BackgroundJob, BackgroundJobType


TEST_IMAGE_BYTES = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
    b"\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00"
    b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01"
    b"\x00\x3b"
)
UPDATE_THUMBNAIL_MEDIA_ROOT = tempfile.mkdtemp()
THUMBNAIL_ADMIN_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=UPDATE_THUMBNAIL_MEDIA_ROOT)
class UpdateThumbnailTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(UPDATE_THUMBNAIL_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='owner',
            password='pw123456',
        )
        self.other_user = get_user_model().objects.create_user(
            username='other',
            password='pw123456',
        )
        self.video = Video.objects.create(
            title='Sample Video',
            source_url='https://send2video.com/watch/sample',
            owner=self.user,
            status='ready',
            thumbnail='https://cdn.example.com/old.jpg',
        )

    def test_owner_can_update_thumbnail(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dramaNlearn:update_thumbnail", args=[self.video.id]),
            data=json.dumps({'thumbnail': 'https://cdn.example.com/new.jpg'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.video.refresh_from_db()
        self.assertEqual(self.video.thumbnail, 'https://cdn.example.com/new.jpg')
        self.assertEqual(response.json()['thumbnail'], 'https://cdn.example.com/new.jpg')

    def test_owner_can_clear_thumbnail(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dramaNlearn:update_thumbnail", args=[self.video.id]),
            data=json.dumps({'thumbnail': ''}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.video.refresh_from_db()
        self.assertEqual(self.video.thumbnail, '')

    def test_rejects_invalid_thumbnail_url(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dramaNlearn:update_thumbnail", args=[self.video.id]),
            data=json.dumps({'thumbnail': 'javascript:alert(1)'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.video.refresh_from_db()
        self.assertEqual(self.video.thumbnail, 'https://cdn.example.com/old.jpg')

    def test_non_owner_cannot_update_thumbnail(self):
        self.client.force_login(self.other_user)

        response = self.client.post(
            reverse("dramaNlearn:update_thumbnail", args=[self.video.id]),
            data=json.dumps({'thumbnail': 'https://cdn.example.com/new.jpg'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.video.refresh_from_db()
        self.assertEqual(self.video.thumbnail, 'https://cdn.example.com/old.jpg')

    def test_owner_can_upload_thumbnail_file(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dramaNlearn:update_thumbnail", args=[self.video.id]),
            data={
                'thumbnail_file': SimpleUploadedFile("uploaded.gif", TEST_IMAGE_BYTES, content_type="image/gif"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.video.refresh_from_db()
        self.assertIn('/media/thumbnails/', self.video.thumbnail)
        self.assertEqual(response.json()['thumbnail'], self.video.thumbnail)

    def test_authenticated_user_can_list_static_images(self):
        self.client.force_login(self.user)
        asset = ThumbnailAsset.objects.create(
            name="Uploaded Thumb",
            image=SimpleUploadedFile("thumb.gif", TEST_IMAGE_BYTES, content_type="image/gif"),
            created_by=self.user,
        )

        response = self.client.get(reverse("dramaNlearn:api_static_images"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertTrue(any(item['id'] == asset.id for item in payload['images']))
        self.assertTrue(any(item['path'] == 'dramaNlearn/thumbnail/one-piece-s2e1.png' for item in payload['images']))
        self.assertTrue(all(item['url'].startswith('http://testserver/') for item in payload['images']))

    def test_static_images_requires_login(self):
        response = self.client.get(reverse("dramaNlearn:api_static_images"))

        self.assertEqual(response.status_code, 401)


@override_settings(MEDIA_ROOT=THUMBNAIL_ADMIN_MEDIA_ROOT)
class ThumbnailAssetAdminTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(THUMBNAIL_ADMIN_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="thumbadmin",
            password="pw123456",
        )

    def test_thumbnail_list_requires_login(self):
        response = self.client.get(reverse("thumbnail_admin:list"))
        self.assertEqual(response.status_code, 302)

    def test_can_create_thumbnail_asset(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("thumbnail_admin:list"),
            {
                "row_indexes": "0",
                "name_0": "Episode One",
                "image_0": SimpleUploadedFile("episode-one.gif", TEST_IMAGE_BYTES, content_type="image/gif"),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(ThumbnailAsset.objects.filter(name="Episode One").exists())

    def test_thumbnail_asset_is_saved_as_webp_with_target_size(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("thumbnail_admin:list"),
            {
                "row_indexes": "0",
                "name_0": "Sized Thumb",
                "image_0": SimpleUploadedFile("sized.gif", TEST_IMAGE_BYTES, content_type="image/gif"),
            },
        )

        asset = ThumbnailAsset.objects.get(name="Sized Thumb")
        self.assertTrue(asset.image.name.endswith(".webp"))
        with Image.open(asset.image.path) as saved_image:
            self.assertEqual(saved_image.size, (960, 540))
            self.assertEqual(saved_image.format, "WEBP")

    def test_can_create_multiple_thumbnail_assets(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("thumbnail_admin:list"),
            {
                "row_indexes": "0,1",
                "name_0": "Episode One",
                "image_0": SimpleUploadedFile("episode-one.gif", TEST_IMAGE_BYTES, content_type="image/gif"),
                "name_1": "Episode Two",
                "image_1": SimpleUploadedFile("episode-two.gif", TEST_IMAGE_BYTES, content_type="image/gif"),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(ThumbnailAsset.objects.filter(name="Episode One").exists())
        self.assertTrue(ThumbnailAsset.objects.filter(name="Episode Two").exists())

    def test_can_update_thumbnail_asset(self):
        self.client.force_login(self.user)
        asset = ThumbnailAsset.objects.create(
            name="Before",
            image=SimpleUploadedFile("before.gif", TEST_IMAGE_BYTES, content_type="image/gif"),
            created_by=self.user,
        )

        response = self.client.post(
            reverse("thumbnail_admin:edit", args=[asset.id]),
            {
                "name": "After",
                "image": SimpleUploadedFile("after.gif", TEST_IMAGE_BYTES, content_type="image/gif"),
            },
        )

        self.assertEqual(response.status_code, 302)
        asset.refresh_from_db()
        self.assertEqual(asset.name, "After")

    def test_can_delete_thumbnail_asset(self):
        self.client.force_login(self.user)
        asset = ThumbnailAsset.objects.create(
            name="Delete Me",
            image=SimpleUploadedFile("delete.gif", TEST_IMAGE_BYTES, content_type="image/gif"),
            created_by=self.user,
        )

        response = self.client.post(reverse("thumbnail_admin:delete", args=[asset.id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ThumbnailAsset.objects.filter(id=asset.id).exists())


class AddVideoBatchTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="batchuser",
            password="pw123456",
        )

    @patch("dramaNlearn.views.extract_drama_video.delay")
    def test_can_add_multiple_urls_in_single_request(self, delay_mock):
        self.client.force_login(self.user)
        delay_mock.side_effect = [
            SimpleNamespace(id="drama-task-1"),
            SimpleNamespace(id="drama-task-2"),
        ]

        response = self.client.post(
            reverse("dramaNlearn:add_video"),
            data=json.dumps(
                {
                    "items": [
                        {"title": "첫 번째", "url": "https://send2video.com/watch/one"},
                        {"title": "두 번째", "url": "https://send2video.com/watch/two"},
                    ]
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["success_count"], 2)
        self.assertEqual(payload["failed_count"], 0)
        self.assertEqual(payload["requested_count"], 2)
        self.assertEqual(len(payload["results"]), 2)
        self.assertTrue(Video.objects.filter(source_url="https://send2video.com/watch/one", status="queued", title="첫 번째").exists())
        self.assertTrue(Video.objects.filter(source_url="https://send2video.com/watch/two", status="queued", title="두 번째").exists())
        self.assertEqual(BackgroundJob.objects.filter(job_type=BackgroundJobType.DRAMA_VIDEO_EXTRACT).count(), 2)

    @patch("dramaNlearn.views.extract_drama_video.delay")
    def test_single_url_keeps_legacy_response_shape(self, delay_mock):
        self.client.force_login(self.user)
        delay_mock.return_value = SimpleNamespace(id="drama-task-legacy")

        response = self.client.post(
            reverse("dramaNlearn:add_video"),
            data=json.dumps({"url": "https://send2video.com/watch/legacy"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("redirect", payload)
        self.assertEqual(payload["success_count"], 1)
        self.assertTrue(payload["queued"])
        self.assertEqual(payload["redirect"], reverse("dramaNlearn:url_manage"))

    def test_batch_add_requires_title_for_each_url(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dramaNlearn:add_video"),
            data=json.dumps(
                {
                    "items": [
                        {"title": "", "url": "https://send2video.com/watch/no-title"},
                    ]
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_count"], 1)
        self.assertEqual(payload["results"][0]["error"], "제목을 입력해주세요.")

    def test_rejects_send2video_root_url(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dramaNlearn:add_video"),
            data=json.dumps({"url": "https://send2video.com", "title": "루트"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "send2video 상세 페이지 URL을 입력해주세요.")


class UrlManageViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="manager",
            password="pw123456",
        )
        self.other_user = get_user_model().objects.create_user(
            username="othermanager",
            password="pw123456",
        )
        self.video = Video.objects.create(
            title="Managed Video",
            source_url="https://send2video.com/watch/manage",
            owner=self.user,
            status="ready",
            thumbnail="https://cdn.example.com/managed.jpg",
        )
        Video.objects.create(
            title="Foreign Video",
            source_url="https://send2video.com/watch/foreign",
            owner=self.other_user,
            status="ready",
        )

    def test_url_manage_requires_login(self):
        response = self.client.get(reverse("dramaNlearn:url_manage"))
        self.assertEqual(response.status_code, 302)

    def test_url_manage_lists_only_my_videos(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dramaNlearn:url_manage"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "URL 추가/편집")
        self.assertContains(response, "Managed Video")
        self.assertNotContains(response, "Foreign Video")
        self.assertContains(response, "썸네일 저장")

    def test_url_manage_page_includes_batch_submit_helper(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dramaNlearn:url_manage"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "function submitDramaUrls(items)")
        self.assertContains(response, "이력")

    def test_url_manage_page_renders_csrf_token_for_batch_submit(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dramaNlearn:url_manage"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "var CSRF = '")
        self.assertNotContains(response, "var CSRF = 'NOTPROVIDED'")
        self.assertContains(response, "'X-Requested-With': 'XMLHttpRequest'")

    def test_url_manage_page_delete_handler_reports_non_json_failures(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dramaNlearn:url_manage"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "function parseJsonResponse(response, options)")
        self.assertContains(response, 'action="%s"' % reverse("dramaNlearn:delete_video", args=[self.video.id]))
        self.assertContains(response, 'name="next" value="%s"' % reverse("dramaNlearn:url_manage"))

    def test_owner_can_delete_video_from_form_post(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dramaNlearn:delete_video", args=[self.video.id]),
            data={"next": reverse("dramaNlearn:url_manage")},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("dramaNlearn:url_manage"))
        self.assertFalse(Video.objects.filter(id=self.video.id).exists())


class DramaHomeViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="home-user", password="pw123456")
        self.other_user = get_user_model().objects.create_user(username="home-other", password="pw123456")
        self.video = Video.objects.create(
            title="Ready Drama",
            source_url="https://send2video.com/watch/home-ready",
            owner=self.user,
            status="ready",
            m3u8_url="https://cdn.example.com/home-ready.m3u8",
        )
        self.series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt1190634",
            title="The Boys",
            poster_url="https://img.example/the-boys.jpg",
            summary="A group of vigilantes take on corrupt superheroes.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=self.series,
            season_number=1,
            episode_number=1,
            episode_title="The Name of the Game",
            stream_url="https://vidfast.pro/tv/tt1190634/1/1?autoPlay=true",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=self.series,
            season_number=1,
            episode_number=2,
            episode_title="Cherry",
            stream_url="https://vidfast.pro/tv/tt1190634/1/2?autoPlay=true",
        )

    def test_home_merges_saved_imdb_series_into_main_grid(self):
        response = self.client.get(reverse("dramaNlearn:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The Boys")
        self.assertContains(response, "tt1190634")
        self.assertContains(response, "IMDb 저장 <b>1개</b>", html=True)
        self.assertContains(response, 'data-kind="imdb"', html=False)
        self.assertContains(response, 'data-kind="video"', html=False)
        self.assertContains(
            response,
            f"{reverse('player')}?source=imdb&amp;imdb_id=tt1190634",
            html=False,
        )
        self.assertContains(
            response,
            f"{reverse('dramaNlearn:imdb')}?query=tt1190634",
            html=False,
        )
        self.assertNotContains(response, "IMDb에서 저장된 드라마")
        self.assertEqual(response.context["home_card_count"], 2)
        self.assertEqual(response.context["ready_count"], 2)
        self.assertEqual(response.context["imdb_series_count"], 1)
        self.assertTrue(any(card["kind"] == "imdb" for card in response.context["home_cards"]))
        self.assertContains(
            response,
            f'action="{reverse("dramaNlearn:delete_video", args=[self.video.id])}"',
            html=False,
        )
        self.assertContains(
            response,
            f'action="{reverse("dramaNlearn:delete_imdb_series", args=[self.series.imdb_id])}"',
            html=False,
        )
        self.assertContains(response, 'title="로그인 후 삭제할 수 있습니다."', html=False)
        self.assertNotContains(response, 'disabled title="로그인 후 삭제할 수 있습니다."', html=False)
        video_card = next(card for card in response.context["home_cards"] if card["kind"] == "video")
        self.assertFalse(video_card["can_delete"])
        self.assertTrue(video_card["delete_requires_login"])
        self.assertEqual(video_card["delete_disabled_reason"], "로그인 후 삭제할 수 있습니다.")
        imdb_card = next(card for card in response.context["home_cards"] if card["kind"] == "imdb")
        self.assertFalse(imdb_card["can_delete"])
        self.assertTrue(imdb_card["delete_requires_login"])

    def test_authenticated_non_owner_home_disables_video_delete_action(self):
        self.client.force_login(self.other_user)

        response = self.client.get(reverse("dramaNlearn:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'action="{reverse("dramaNlearn:delete_video", args=[self.video.id])}"',
            html=False,
        )
        self.assertContains(response, 'title="내가 등록한 영상만 삭제할 수 있습니다."', html=False)
        self.assertContains(
            response,
            "showToast('내가 등록한 영상만 삭제할 수 있습니다.', 'info');",
            html=False,
        )
        self.assertNotContains(response, 'disabled title="내가 등록한 영상만 삭제할 수 있습니다."', html=False)
        video_card = next(card for card in response.context["home_cards"] if card["kind"] == "video")
        self.assertFalse(video_card["can_delete"])
        self.assertFalse(video_card["delete_requires_login"])
        self.assertEqual(video_card["delete_disabled_reason"], "내가 등록한 영상만 삭제할 수 있습니다.")

    def test_authenticated_home_enables_saved_imdb_delete_action(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dramaNlearn:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'action="{reverse("dramaNlearn:delete_imdb_series", args=[self.series.imdb_id])}"',
            html=False,
        )
        self.assertContains(
            response,
            f'action="{reverse("dramaNlearn:delete_video", args=[self.video.id])}"',
            html=False,
        )
        self.assertContains(response, 'name="next" value="%s"' % reverse("dramaNlearn:home"))
        self.assertNotContains(response, 'title="로그인 후 삭제할 수 있습니다."', html=False)
        self.assertNotContains(response, 'title="내가 등록한 영상만 삭제할 수 있습니다."', html=False)
        video_card = next(card for card in response.context["home_cards"] if card["kind"] == "video")
        self.assertTrue(video_card["can_delete"])
        self.assertFalse(video_card["delete_requires_login"])
        self.assertEqual(video_card["delete_disabled_reason"], "")


class DramaPlayerViewTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="player-owner", password="pw123456")
        self.viewer = get_user_model().objects.create_user(username="player-viewer", password="pw123456")
        self.video = Video.objects.create(
            title="Ready Drama",
            source_url="https://send2video.com/watch/player",
            owner=self.owner,
            status="ready",
            m3u8_url="https://player.example/ready.m3u8",
            thumbnail="https://img.example/drama.jpg",
            duration=125.4,
        )

    def test_owner_player_page_includes_study_create_and_job_history_links(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("dramaNlearn:player", args=[self.video.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("study:create"))
        self.assertContains(response, "source_type=drama_video")
        self.assertContains(response, f"drama_video_id={self.video.id}")
        self.assertContains(response, reverse("workers:drama-video-job-history", args=[self.video.id]))
        self.assertContains(response, reverse("dramaNlearn:clip_extract", args=[self.video.id]))

    def test_non_owner_player_page_hides_job_history_link(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("dramaNlearn:player", args=[self.video.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("study:create"))
        self.assertContains(response, "source_type=drama_video")
        self.assertContains(response, f"drama_video_id={self.video.id}")
        self.assertNotContains(response, reverse("workers:drama-video-job-history", args=[self.video.id]))
        self.assertNotContains(response, reverse("dramaNlearn:clip_extract", args=[self.video.id]))

    def test_owner_can_open_shared_clip_extract_page_for_ready_drama(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("dramaNlearn:clip_extract", args=[self.video.id]), follow=True)

        self.assertEqual(response.status_code, 200)
        bridge = MasterVideo.objects.get(source_drama_video=self.video)
        self.assertEqual(bridge.owner, self.owner)
        self.assertEqual(bridge.source_type, MasterVideoSourceType.UPLOAD)
        self.assertEqual(bridge.remote_playback_url, self.video.m3u8_url)
        self.assertEqual(bridge.download_status, ProcessingState.READY)
        self.assertEqual(bridge.channel_name, "Drama")
        self.assertEqual(bridge.title, self.video.title)
        self.assertEqual(bridge.description, self.video.source_url)
        self.assertEqual(bridge.thumbnail_url, self.video.thumbnail)
        self.assertEqual(bridge.duration_seconds, 125)
        self.assertEqual(response.redirect_chain[-1][0], reverse("videos:detail", args=[bridge.id]))
        self.assertContains(response, "클립 생성")
        self.assertContains(response, "드라마보기")
        self.assertContains(response, "원본 페이지")

    def test_clip_extract_redirects_back_when_drama_stream_is_not_ready(self):
        self.client.force_login(self.owner)
        self.video.status = "error"
        self.video.m3u8_url = ""
        self.video.save(update_fields=["status", "m3u8_url", "updated_at"])

        response = self.client.get(reverse("dramaNlearn:clip_extract", args=[self.video.id]))

        self.assertRedirects(response, reverse("dramaNlearn:player", args=[self.video.id]))
        self.assertFalse(MasterVideo.objects.filter(source_drama_video=self.video).exists())

    def test_owner_can_create_study_material_from_drama_player_and_open_detail(self):
        self.client.force_login(self.owner)

        player_response = self.client.get(reverse("dramaNlearn:player", args=[self.video.id]))

        self.assertEqual(player_response.status_code, 200)
        create_url = reverse("study:create") + f"?source_type=drama_video&drama_video_id={self.video.id}"
        self.assertContains(player_response, create_url)

        response = self.client.post(
            create_url,
            data={
                "title": "Drama Shadowing Draft",
                "material_type": "shadowing_script",
                "purpose": "shadowing",
                "difficulty": "intermediate",
                "visibility": "private",
                "generated_content": "Ready drama line",
                "editable_notes": "drama note",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        from study.models import StudyMaterial

        material = StudyMaterial.objects.get(owner=self.owner, title="Drama Shadowing Draft")
        self.assertEqual(material.source_type, "drama_video")
        self.assertEqual(material.source_drama_video, self.video)
        self.assertContains(response, "Drama Shadowing Draft")
        self.assertContains(response, "Ready drama line")


class ImdbDramaCatalogServiceTests(TestCase):
    def _create_cached_series(self) -> ImdbDramaSeriesCache:
        series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt1190634",
            title="The Boys",
            poster_url="https://img.example/the-boys.jpg",
            summary="A group of vigilantes take on corrupt superheroes.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=series,
            season_number=1,
            episode_number=1,
            episode_title="The Name of the Game",
            stream_url="https://vidfast.pro/tv/tt1190634/1/1?autoPlay=true",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=series,
            season_number=1,
            episode_number=2,
            episode_title="Cherry",
            stream_url="https://vidfast.pro/tv/tt1190634/1/2?autoPlay=true",
        )
        return series

    @patch("dramaNlearn.services.imdb_lookup._fetch_cinemeta_series_detail")
    def test_lookup_by_imdb_id_uses_cached_series_without_external_fetch(self, detail_mock):
        self._create_cached_series()

        payload = search_imdb_drama_catalog("tt1190634")

        self.assertEqual(payload["selected"]["imdb_id"], "tt1190634")
        self.assertEqual(payload["selected"]["selected_stream_url"], "https://vidfast.pro/tv/tt1190634/1/1?autoPlay=true")
        detail_mock.assert_not_called()

    @patch("dramaNlearn.services.imdb_lookup._search_cinemeta_series")
    def test_lookup_by_title_uses_cached_series_without_external_search(self, search_mock):
        self._create_cached_series()

        payload = search_imdb_drama_catalog("The Boys")

        self.assertEqual(payload["selected_source"], "cache")
        self.assertEqual(payload["selected"]["title"], "The Boys")
        self.assertEqual(len(payload["results"]), 1)
        search_mock.assert_not_called()

    @patch("dramaNlearn.services.imdb_lookup._fetch_cinemeta_series_detail")
    @patch("dramaNlearn.services.imdb_lookup._search_cinemeta_series")
    def test_lookup_by_title_fetches_and_persists_series_on_cache_miss(self, search_mock, detail_mock):
        search_mock.return_value = [
            {
                "imdb_id": "tt1190634",
                "title": "The Boys",
                "poster_url": "https://img.example/search.jpg",
                "summary": "Search summary",
                "source": "external",
            }
        ]
        detail_mock.return_value = {
            "imdb_id": "tt1190634",
            "title": "The Boys",
            "poster_url": "https://img.example/detail.jpg",
            "summary": "Detailed summary",
            "episodes": [
                {
                    "season_number": 1,
                    "episode_number": 1,
                    "episode_title": "The Name of the Game",
                    "stream_url": "https://vidfast.pro/tv/tt1190634/1/1?autoPlay=true",
                },
                {
                    "season_number": 1,
                    "episode_number": 2,
                    "episode_title": "Cherry",
                    "stream_url": "https://vidfast.pro/tv/tt1190634/1/2?autoPlay=true",
                },
            ],
        }

        payload = search_imdb_drama_catalog("The Boys")

        self.assertEqual(payload["selected_source"], "fetched")
        self.assertTrue(ImdbDramaSeriesCache.objects.filter(imdb_id="tt1190634").exists())
        self.assertEqual(ImdbDramaEpisodeCache.objects.filter(series__imdb_id="tt1190634").count(), 2)
        self.assertEqual(payload["selected"]["summary"], "Detailed summary")
        search_mock.assert_called_once_with("The Boys")
        detail_mock.assert_called_once_with("tt1190634")


class ImdbDramaBrowserViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="imdb-manager",
            password="pw123456",
        )
        self.series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt1190634",
            title="The Boys",
            poster_url="https://img.example/the-boys.jpg",
            summary="A group of vigilantes take on corrupt superheroes.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=self.series,
            season_number=1,
            episode_number=1,
            episode_title="The Name of the Game",
            stream_url="https://vidfast.pro/tv/tt1190634/1/1?autoPlay=true",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=self.series,
            season_number=1,
            episode_number=2,
            episode_title="Cherry",
            stream_url="https://vidfast.pro/tv/tt1190634/1/2?autoPlay=true",
        )
        self.recent_series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt3581920",
            title="The Last of Us",
            poster_url="https://img.example/the-last-of-us.jpg",
            summary="Post-pandemic drama.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=self.recent_series,
            season_number=1,
            episode_number=1,
            episode_title="When You're Lost in the Darkness",
            stream_url="https://vidfast.pro/tv/tt3581920/1/1?autoPlay=true",
        )
        self.oldest_series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt0436992",
            title="Doctor Who",
            poster_url="https://img.example/doctor-who.jpg",
            summary="Time-travel adventures.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=self.oldest_series,
            season_number=1,
            episode_number=1,
            episode_title="Rose",
            stream_url="https://vidfast.pro/tv/tt0436992/1/1?autoPlay=true",
        )

        now = timezone.now()
        ImdbDramaSeriesCache.objects.filter(pk=self.series.pk).update(
            updated_at=now - timedelta(days=2),
            last_played_at=now - timedelta(hours=1),
            manual_order=2,
        )
        ImdbDramaSeriesCache.objects.filter(pk=self.recent_series.pk).update(
            updated_at=now - timedelta(hours=2),
            manual_order=1,
        )
        ImdbDramaSeriesCache.objects.filter(pk=self.oldest_series.pk).update(
            updated_at=now - timedelta(days=7),
            last_played_at=now - timedelta(days=3),
            manual_order=3,
        )

    def test_imdb_page_is_available(self):
        response = self.client.get(reverse("dramaNlearn:imdb"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "IMDB DRAMA")

    def test_imdb_page_lists_saved_dramas_in_four_column_grid_without_placeholder_text(self):
        hidden_series = ImdbDramaSeriesCache.objects.create(
            imdb_id="tt28793987",
            title="The Fiery Priest",
            poster_url="https://img.example/the-fiery-priest.jpg",
            summary="Action comedy.",
        )
        ImdbDramaEpisodeCache.objects.create(
            series=hidden_series,
            season_number=2,
            episode_number=3,
            episode_title="Someday",
            stream_url="",
        )

        response = self.client.get(reverse("dramaNlearn:imdb"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "저장된 드라마")
        self.assertContains(response, "The Boys")
        self.assertContains(response, "The Last of Us")
        self.assertContains(response, "1개 시즌 · 2개 에피소드")
        self.assertContains(response, "grid-template-columns:repeat(4, minmax(0, 1fr));")
        self.assertNotContains(response, "드라마 제목이나 IMDb ID를 검색하면 저장된 메타데이터와 에피소드 플레이어가 여기에 표시됩니다.")
        self.assertNotContains(response, 'class="imdb-badge is-accent">tt1190634', html=False)
        self.assertNotContains(response, '<span class="imdb-badge">DB</span>', html=True)
        self.assertContains(
            response,
            f'{reverse("player")}?imdb_modal=1&amp;imdb_id=tt1190634',
            html=False,
        )
        self.assertNotContains(response, "The Fiery Priest")
        self.assertEqual(response.context["saved_sort"], "manual")
        self.assertEqual(response.context["saved_series"][0]["imdb_id"], "tt3581920")

    def test_imdb_page_supports_saved_series_sorting_options(self):
        response = self.client.get(reverse("dramaNlearn:imdb"), {"saved_sort": "manual"})

        self.assertEqual(response.status_code, 200)
        saved_series = response.context["saved_series"]
        self.assertEqual(saved_series[0]["imdb_id"], "tt3581920")
        self.assertContains(response, "직접 순서")

        response = self.client.get(reverse("dramaNlearn:imdb"), {"saved_sort": "recent_played"})

        self.assertEqual(response.status_code, 200)
        saved_series = response.context["saved_series"]
        self.assertEqual(response.context["saved_sort"], "recent_played")
        self.assertEqual(saved_series[0]["imdb_id"], "tt1190634")
        self.assertContains(response, "최근")
        self.assertContains(response, "오래된")
        self.assertContains(response, "최근 재생")

        response = self.client.get(reverse("dramaNlearn:imdb"), {"saved_sort": "oldest"})

        self.assertEqual(response.status_code, 200)
        saved_series = response.context["saved_series"]
        self.assertEqual(saved_series[0]["imdb_id"], "tt0436992")

    def test_authenticated_user_can_delete_saved_series(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dramaNlearn:delete_imdb_series", args=[self.recent_series.imdb_id]),
            {"next": f"{reverse('dramaNlearn:imdb')}?saved_sort=oldest"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('dramaNlearn:imdb')}?saved_sort=oldest")
        self.assertFalse(ImdbDramaSeriesCache.objects.filter(imdb_id=self.recent_series.imdb_id).exists())

    def test_authenticated_user_can_reorder_saved_series(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dramaNlearn:reorder_imdb_series"),
            data=json.dumps(
                {
                    "imdb_ids": [
                        self.oldest_series.imdb_id,
                        self.series.imdb_id,
                        self.recent_series.imdb_id,
                    ]
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        ordered_ids = list(
            ImdbDramaSeriesCache.objects.order_by("manual_order").values_list("imdb_id", flat=True)
        )
        self.assertEqual(ordered_ids[:3], ["tt0436992", "tt1190634", "tt3581920"])

    def test_imdb_page_renders_cached_drama_detail_and_player(self):
        response = self.client.get(reverse("dramaNlearn:imdb"), {"query": "The Boys"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The Boys")
        self.assertContains(response, "A group of vigilantes take on corrupt superheroes.")
        self.assertContains(response, 'id="seasonSelect"', html=False)
        self.assertContains(response, 'id="episodeSelect"', html=False)
        self.assertContains(response, "https://vidfast.pro/tv/tt1190634/1/1?autoPlay=true")
        self.assertContains(response, "DB 저장본")
        self.assertContains(response, "삭제")


class DramaStreamAccessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="drama-stream-owner", password="pw123456")
        self.video = Video.objects.create(
            title="Drama Stream Source",
            source_url="https://send2video.com/watch/stream-source",
            owner=self.user,
            status="ready",
            player_url="https://xzxcdn.com/e/demo-player",
            m3u8_url="https://cdn.example.com/original/master.m3u8?old=1",
        )

    @patch("dramaNlearn.services.stream_access.requests.get")
    @patch("dramaNlearn.services.stream_access.extractor.get_m3u8_from_player")
    def test_prepare_drama_extract_source_refreshes_and_writes_absolute_variant_manifest(self, info_mock, get_mock):
        info_mock.return_value = {
            "m3u8_url": "https://cdn.example.com/hls/master.m3u8?sig=new",
            "thumbnail": "https://img.example.com/refresh.jpg",
            "duration": 321.4,
            "subtitles": [{"src": "https://cdn.example.com/subs/en.vtt", "label": "English"}],
        }
        get_mock.side_effect = [
            SimpleNamespace(
                text=(
                    "#EXTM3U\n"
                    "#EXT-X-STREAM-INF:BANDWIDTH=110000\n"
                    "low/index.m3u8?sig=low\n"
                    "#EXT-X-STREAM-INF:BANDWIDTH=220000\n"
                    "high/index.m3u8?sig=high\n"
                ),
                raise_for_status=lambda: None,
            ),
            SimpleNamespace(
                text=(
                    "#EXTM3U\n"
                    '#EXT-X-KEY:METHOD=AES-128,URI="keys/demo.key?token=1"\n'
                    "#EXTINF:10.0,\n"
                    "seg-001.ts?token=2\n"
                    "#EXTINF:10.0,\n"
                    "https://cdn.example.com/hls/high/seg-002.ts?token=3\n"
                    "#EXT-X-ENDLIST\n"
                ),
                raise_for_status=lambda: None,
            ),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            prepared = prepare_drama_extract_source(self.video, Path(temp_dir))
            playlist_text = prepared.source_path.read_text(encoding="utf-8")

        self.video.refresh_from_db()

        self.assertEqual(prepared.resolved_master_url, "https://cdn.example.com/hls/master.m3u8?sig=new")
        self.assertEqual(prepared.selected_variant_url, "https://cdn.example.com/hls/high/index.m3u8?sig=high")
        self.assertIn('URI="https://cdn.example.com/hls/high/keys/demo.key?token=1"', playlist_text)
        self.assertIn("https://cdn.example.com/hls/high/seg-001.ts?token=2", playlist_text)
        self.assertIn("https://cdn.example.com/hls/high/seg-002.ts?token=3", playlist_text)
        self.assertEqual(self.video.m3u8_url, "https://cdn.example.com/hls/master.m3u8?sig=new")
        self.assertEqual(self.video.thumbnail, "https://img.example.com/refresh.jpg")
        self.assertEqual(self.video.duration, 321.4)
        self.assertIn("English", self.video.subtitle_tracks)


class DramaAsyncViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="async-user", password="pw123456")
        self.other_user = get_user_model().objects.create_user(username="async-other", password="pw123456")
        self.client.force_login(self.user)

    @patch("dramaNlearn.views.extract_drama_video.delay")
    def test_retry_video_queues_background_job(self, delay_mock):
        delay_mock.return_value = SimpleNamespace(id="drama-retry-task")
        video = Video.objects.create(
            title="Retry Target",
            source_url="https://send2video.com/watch/retry",
            owner=self.user,
            status="error",
            error_msg="boom",
        )

        response = self.client.post(reverse("dramaNlearn:retry_video", args=[video.id]))

        self.assertEqual(response.status_code, 200)
        video.refresh_from_db()
        self.assertEqual(video.status, "queued")
        job = BackgroundJob.objects.filter(
            related_object_type="drama_video",
            related_object_id=str(video.id),
        ).latest("id")
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.celery_task_id, "drama-retry-task")

    @patch("dramaNlearn.views.current_app.control.revoke")
    def test_cancel_video_marks_queued_job_canceled(self, revoke_mock):
        video = Video.objects.create(
            title="Cancel Target",
            source_url="https://send2video.com/watch/cancel",
            owner=self.user,
            status="queued",
        )
        job = BackgroundJob.objects.create(
            user=self.user,
            job_type=BackgroundJobType.DRAMA_VIDEO_EXTRACT,
            related_object_type="drama_video",
            related_object_id=str(video.id),
            status="queued",
            progress_percent=0,
            celery_task_id="celery-drama-cancel",
        )

        response = self.client.post(reverse("dramaNlearn:cancel_video", args=[video.id]))

        self.assertEqual(response.status_code, 200)
        revoke_mock.assert_called_once_with("celery-drama-cancel")
        video.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(video.status, "canceled")
        self.assertEqual(job.status, "canceled")

    def test_cancel_rejects_non_queued_job(self):
        video = Video.objects.create(
            title="Fetching Target",
            source_url="https://send2video.com/watch/fetching",
            owner=self.user,
            status="fetching",
        )
        BackgroundJob.objects.create(
            user=self.user,
            job_type=BackgroundJobType.DRAMA_VIDEO_EXTRACT,
            related_object_type="drama_video",
            related_object_id=str(video.id),
            status="processing",
            progress_percent=40,
        )

        response = self.client.post(reverse("dramaNlearn:cancel_video", args=[video.id]))

        self.assertEqual(response.status_code, 400)

    def test_status_api_hides_job_payload_for_non_owner(self):
        video = Video.objects.create(
            title="Owner Video",
            source_url="https://send2video.com/watch/owner",
            owner=self.user,
            status="queued",
        )
        BackgroundJob.objects.create(
            user=self.user,
            job_type=BackgroundJobType.DRAMA_VIDEO_EXTRACT,
            related_object_type="drama_video",
            related_object_id=str(video.id),
            status="queued",
            progress_percent=10,
            message="Queued for drama extraction",
        )
        self.client.force_login(self.other_user)

        response = self.client.get(reverse("dramaNlearn:api_video_status", args=[video.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("job", response.json())

    def test_drama_job_history_requires_owner(self):
        video = Video.objects.create(
            title="Owner Video",
            source_url="https://send2video.com/watch/history",
            owner=self.user,
            status="error",
        )
        BackgroundJob.objects.create(
            user=self.user,
            job_type=BackgroundJobType.DRAMA_VIDEO_EXTRACT,
            related_object_type="drama_video",
            related_object_id=str(video.id),
            status="failed",
            progress_percent=100,
            message="Drama extraction failed",
            error_message="boom",
        )
        self.client.force_login(self.other_user)

        response = self.client.get(reverse("workers:drama-video-job-history", args=[video.id]))

        self.assertEqual(response.status_code, 403)


class DramaAsyncTaskTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="task-user", password="pw123456")
        self.video = Video.objects.create(
            title="Queued Drama",
            source_url="https://send2video.com/watch/task",
            owner=self.user,
            status="queued",
        )
        self.job = BackgroundJob.objects.create(
            user=self.user,
            job_type=BackgroundJobType.DRAMA_VIDEO_EXTRACT,
            related_object_type="drama_video",
            related_object_id=str(self.video.id),
            status="queued",
            progress_percent=0,
            message="Queued for drama extraction",
        )

    @patch("dramaNlearn.tasks.extractor.extract")
    def test_extract_drama_video_marks_ready_on_success(self, extract_mock):
        extract_mock.return_value = {
            "player_url": "https://player.example/embed",
            "m3u8_url": "https://player.example/index.m3u8",
            "thumbnail": "https://img.example/thumb.jpg",
            "duration": 123,
            "subtitles": [{"src": "https://example.com/sub.vtt", "label": "English"}],
        }

        extract_drama_video.run(self.video.id)

        self.video.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.video.status, "ready")
        self.assertTrue(self.video.m3u8_url.endswith(".m3u8"))
        self.assertEqual(self.job.status, "success")
        self.assertEqual(self.job.progress_percent, 100)

    @patch("dramaNlearn.tasks.extractor.extract", side_effect=requests.Timeout("timed out"))
    def test_extract_drama_video_maps_timeout_error_message(self, extract_mock):
        extract_drama_video.run(self.video.id)

        self.video.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.video.status, "error")
        self.assertIn("응답 시간이 너무 길어", self.video.error_msg)
        self.assertEqual(self.job.status, "failed")
        self.assertIn("응답 시간이 너무 길어", self.job.error_message)

    def test_extract_drama_video_respects_canceled_job(self):
        self.job.status = "canceled"
        self.job.save(update_fields=["status", "updated_at"])

        extract_drama_video.run(self.video.id)

        self.video.refresh_from_db()
        self.assertEqual(self.video.status, "canceled")
