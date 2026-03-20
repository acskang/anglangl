import json
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from PIL import Image

from .models import ThumbnailAsset, Video


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

    @patch("dramaNlearn.views.extractor.extract")
    def test_can_add_multiple_urls_in_single_request(self, extract_mock):
        self.client.force_login(self.user)
        extract_mock.side_effect = [
            {
                "player_url": "https://example.com/player/1",
                "m3u8_url": "https://example.com/stream/1.m3u8",
                "thumbnail": "https://example.com/thumb/1.jpg",
                "duration": 120,
                "subtitles": [],
            },
            RuntimeError("boom"),
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
        self.assertEqual(payload["success_count"], 1)
        self.assertEqual(payload["failed_count"], 1)
        self.assertEqual(payload["requested_count"], 2)
        self.assertEqual(len(payload["results"]), 2)
        self.assertTrue(Video.objects.filter(source_url="https://send2video.com/watch/one", status="ready", title="첫 번째").exists())
        self.assertTrue(Video.objects.filter(source_url="https://send2video.com/watch/two", status="error").exists())

    @patch("dramaNlearn.views.extractor.extract")
    def test_single_url_keeps_legacy_response_shape(self, extract_mock):
        self.client.force_login(self.user)
        extract_mock.return_value = {
            "player_url": "https://example.com/player/legacy",
            "m3u8_url": "https://example.com/stream/legacy.m3u8",
            "thumbnail": "",
            "duration": 30,
            "subtitles": [],
        }

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
