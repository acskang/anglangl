from datetime import timedelta
import json
import re
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import BackgroundJobState, ProcessingState
from clips.models import Clip, ClipSourceType
from videos.forms import MasterVideoCreateForm
from videos.models import MasterVideo, MasterVideoSourceType
from videos.services.download_state import STALE_PENDING_MASTER_VIDEO_ERROR
from videos.services.ytdlp import YtDlpService, YtDlpTransientError
from workers.models import BackgroundJob, BackgroundJobType

TEST_IMAGE_BYTES = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
    b"\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00"
    b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01"
    b"\x00\x3b"
)
VIDEO_THUMBNAIL_MEDIA_ROOT = tempfile.mkdtemp()


class DummyJsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyBytesResponse:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.headers = {}

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def extract_csrf_token(html: str) -> str:
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    if not match:
        raise AssertionError("csrfmiddlewaretoken input not found in rendered HTML")
    return match.group(1)


class MasterVideoCreateFormTests(TestCase):
    def test_upload_source_requires_video_file(self):
        form = MasterVideoCreateForm(
            data={
                "source_type": MasterVideoSourceType.UPLOAD,
                "upload_title": "Local File",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("video_file", form.errors)

    def test_youtube_source_rejects_uploaded_file(self):
        uploaded = SimpleUploadedFile("sample.mp4", b"video-bytes", content_type="video/mp4")
        form = MasterVideoCreateForm(
            data={
                "source_type": MasterVideoSourceType.YOUTUBE,
                "youtube_input": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            },
            files={"video_file": uploaded},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("video_file", form.errors)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class MasterVideoCreateViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="tester", password="pw123456")
        self.client.force_login(self.user)

    @patch("videos.views.process_uploaded_master_video.delay")
    def test_local_upload_queues_background_processing(self, delay_mock):
        uploaded = SimpleUploadedFile("lesson.mp4", b"fake-video-content", content_type="video/mp4")
        subtitle = SimpleUploadedFile("lesson.srt", b"1\n00:00:00,000 --> 00:00:02,000\nHello\n", content_type="text/plain")
        delay_mock.return_value.id = "celery-upload-task-1"

        response = self.client.post(
            reverse("videos:create"),
            data={
                "source_type": MasterVideoSourceType.UPLOAD,
                "upload_title": "Lesson 1",
                "video_file": uploaded,
                "subtitle_file": subtitle,
            },
        )

        self.assertEqual(response.status_code, 302)
        video = MasterVideo.objects.get()
        self.assertEqual(video.source_type, MasterVideoSourceType.UPLOAD)
        self.assertEqual(video.title, "Lesson 1")
        self.assertEqual(video.download_status, ProcessingState.QUEUED)
        self.assertTrue(video.video_file.name.endswith("lesson.mp4"))
        self.assertTrue(video.subtitle_file.name.endswith("lesson.srt"))
        delay_mock.assert_called_once_with(video.id)

        job = BackgroundJob.objects.get(related_object_type="master_video", related_object_id=str(video.id))
        self.assertEqual(job.job_type, BackgroundJobType.MASTER_VIDEO_UPLOAD_PROCESS)
        self.assertEqual(job.status, BackgroundJobState.QUEUED)
        self.assertEqual(job.celery_task_id, "celery-upload-task-1")

    @patch("videos.views.download_youtube_video.delay")
    def test_linked_video_queues_import_job(self, delay_mock):
        delay_mock.return_value.id = "celery-import-task-1"

        response = self.client.post(
            reverse("videos:create"),
            data={
                "source_type": MasterVideoSourceType.YOUTUBE,
                "youtube_input": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            },
        )

        self.assertEqual(response.status_code, 302)
        video = MasterVideo.objects.get()
        self.assertEqual(video.source_type, MasterVideoSourceType.YOUTUBE)
        self.assertEqual(video.download_status, ProcessingState.QUEUED)
        self.assertEqual(video.youtube_video_id, "dQw4w9WgXcQ")
        delay_mock.assert_called_once_with(video.id)

        job = BackgroundJob.objects.get(related_object_type="master_video", related_object_id=str(video.id))
        self.assertEqual(job.job_type, BackgroundJobType.YOUTUBE_DOWNLOAD)
        self.assertEqual(job.status, BackgroundJobState.QUEUED)
        self.assertEqual(job.celery_task_id, "celery-import-task-1")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class UploadedMasterVideoTaskTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="task-user", password="pw123456")
        self.video = MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Queued Upload",
            download_status=ProcessingState.QUEUED,
        )
        self.video.video_file.save("queued.mp4", ContentFile(b"video-bytes"), save=False)
        self.video.file_size_bytes = len(b"video-bytes")
        self.video.save(update_fields=["video_file", "file_size_bytes", "updated_at"])
        self.job = BackgroundJob.objects.create(
            user=self.user,
            job_type=BackgroundJobType.MASTER_VIDEO_UPLOAD_PROCESS,
            related_object_type="master_video",
            related_object_id=str(self.video.id),
            status=BackgroundJobState.QUEUED,
            message="Queued for uploaded video processing",
        )

    @patch("videos.tasks.FfmpegService.generate_hls")
    @patch("videos.tasks.FfmpegService.probe_duration_seconds", return_value=42)
    def test_process_uploaded_master_video_marks_video_ready(self, probe_duration_mock, generate_hls_mock):
        generate_hls_mock.return_value.manifest_path = (
            Path(settings.MEDIA_ROOT) / "master_videos" / "hls" / f"user_{self.user.id}" / str(self.video.id) / "index.m3u8"
        )

        from videos.tasks import process_uploaded_master_video

        process_uploaded_master_video.run(self.video.id)

        self.video.refresh_from_db()
        self.job.refresh_from_db()

        self.assertEqual(self.video.download_status, ProcessingState.READY)
        self.assertEqual(self.video.duration_seconds, 42)
        self.assertTrue(self.video.hls_manifest_file.name.endswith("index.m3u8"))
        self.assertEqual(self.job.status, BackgroundJobState.SUCCESS)
        probe_duration_mock.assert_called_once()
        generate_hls_mock.assert_called_once()
        self.assertIsNotNone(generate_hls_mock.call_args.kwargs["progress_callback"])
        self.assertEqual(generate_hls_mock.call_args.kwargs["timeout"], settings.FFMPEG_HLS_TIMEOUT)

    @patch("videos.tasks.FfmpegService.generate_hls", side_effect=SoftTimeLimitExceeded())
    @patch("videos.tasks.FfmpegService.probe_duration_seconds", return_value=42)
    def test_process_uploaded_master_video_marks_failed_on_soft_timeout(self, probe_duration_mock, generate_hls_mock):
        from videos.tasks import process_uploaded_master_video

        process_uploaded_master_video.run(self.video.id)

        self.video.refresh_from_db()
        self.job.refresh_from_db()

        self.assertEqual(self.video.download_status, ProcessingState.FAILED)
        self.assertIn("soft time limit", self.video.download_error_message.lower())
        self.assertEqual(self.job.status, BackgroundJobState.FAILED)
        probe_duration_mock.assert_called_once()
        generate_hls_mock.assert_called_once()


class VideoLibraryTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="owner", password="pw123456")
        self.viewer = get_user_model().objects.create_user(username="viewer", password="pw123456")
        self.linked_video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="abc123xyz99",
            youtube_url="https://www.youtube.com/watch?v=abc123xyz99",
            title="Owner Linked Asset",
            download_status=ProcessingState.READY,
            duration_seconds=120,
        )
        self.upload_video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Upload Video",
            download_status=ProcessingState.READY,
        )
        self.viewer_video = MasterVideo.objects.create(
            owner=self.viewer,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Viewer Upload",
            download_status=ProcessingState.READY,
        )
        self.clip = Clip.objects.create(
            owner=self.owner,
            source_type=ClipSourceType.EXTRACTED,
            master_video=self.linked_video,
            title="Owner Clip",
            start_time_seconds=0,
            end_time_seconds=10,
            duration_seconds=10,
            file_status=ProcessingState.READY,
        )

    def test_list_redirects_to_dashboard(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("videos:list"))

        self.assertRedirects(response, reverse("dashboard:home"))

    def test_upload_route_filters_to_uploaded_videos(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("videos:upload-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload Video")
        self.assertNotContains(response, "Owner Linked Asset")
        self.assertNotContains(response, "Viewer Upload")
        self.assertContains(response, reverse("videos:create-video"))

    def test_linked_route_filters_to_youtube_videos(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("videos:linked-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "저장된 영상")
        self.assertContains(response, "Owner Linked Asset")
        self.assertNotContains(response, "Upload Video")
        self.assertContains(response, reverse("videos:create-youtube"))
        self.assertContains(response, "library-card-grid", html=False)
        self.assertContains(response, 'class="library-toolbar linked-toolbar"', html=False)
        self.assertContains(response, reverse("videos:thumbnail-proxy", args=[self.linked_video.id]), html=False)
        self.assertContains(response, "1개 클립")
        self.assertNotContains(response, "Failed</span>", html=False)
        self.assertNotContains(response, "Open</a>", html=False)
        self.assertNotContains(response, "Reload</button>", html=False)
        self.assertNotContains(response, 'id="videoSource"', html=False)
        self.assertContains(response, "Apply</button>", html=False)

    def test_thumbnail_album_shows_only_request_users_videos_with_thumbnails(self):
        self.client.force_login(self.owner)
        self.linked_video.thumbnail_url = "https://img.example/owner.jpg"
        self.linked_video.custom_thumbnail_description = "대표 썸네일 설명"
        self.linked_video.save(update_fields=["thumbnail_url", "custom_thumbnail_description", "updated_at"])
        self.upload_video.thumbnail_url = "https://img.example/upload.jpg"
        self.upload_video.save(update_fields=["thumbnail_url", "updated_at"])
        self.viewer_video.thumbnail_url = "https://img.example/viewer.jpg"
        self.viewer_video.save(update_fields=["thumbnail_url", "updated_at"])

        response = self.client.get(reverse("videos:thumbnail-album"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "썸네일 이미지 앨범")
        self.assertContains(response, "Owner Linked Asset")
        self.assertContains(response, "Upload Video")
        self.assertNotContains(response, "Viewer Upload")
        self.assertContains(response, reverse("videos:edit", args=[self.linked_video.id]), html=False)
        self.assertContains(response, reverse("videos:detail", args=[self.linked_video.id]), html=False)
        self.assertContains(response, reverse("videos:thumbnail-proxy", args=[self.linked_video.id]), html=False)
        self.assertContains(response, "대표 썸네일 설명")

    def test_thumbnail_album_empty_message_when_no_thumbnails_exist(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("videos:thumbnail-album"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "등록된 썸네일 이미지가 없습니다.")

    def test_owner_detail_shows_manage_actions(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("videos:detail", args=[self.linked_video.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Owner Clip")
        self.assertContains(response, reverse("videos:edit", args=[self.linked_video.id]), html=False)
        self.assertContains(response, reverse("videos:delete", args=[self.linked_video.id]), html=False)

    def test_owner_detail_includes_embed_failure_fallback_markup(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("videos:detail", args=[self.linked_video.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="playerFallback"', html=False)
        self.assertContains(response, "외부 사이트 재생이 차단된 영상입니다")
        self.assertContains(response, reverse("videos:thumbnail-proxy", args=[self.linked_video.id]), html=False)
        self.assertContains(response, reverse("videos:edit", args=[self.linked_video.id]), html=False)

    def test_owner_detail_includes_context_capture_player_controls(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("videos:detail", args=[self.linked_video.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="playerContextMenu"', html=False)
        self.assertContains(response, 'data-context-action="start"', html=False)
        self.assertContains(response, 'data-context-action="end"', html=False)
        self.assertContains(response, 'data-context-action="fullscreen"', html=False)
        self.assertContains(response, 'data-context-action="pip"', html=False)
        self.assertContains(response, 'id="currentTimeBar"', html=False)
        self.assertContains(response, 'id="ytTopChromeMask"', html=False)
        self.assertContains(response, 'id="captureStartBtn"', html=False)
        self.assertContains(response, 'id="captureEndBtn"', html=False)
        self.assertContains(response, 'id="seekStartBtn"', html=False)
        self.assertContains(response, 'id="seekEndBtn"', html=False)
        self.assertContains(response, 'class="time-transfer-btn left start"', html=False)
        self.assertContains(response, 'class="time-transfer-btn right start"', html=False)
        self.assertContains(response, 'class="time-transfer-btn left end"', html=False)
        self.assertContains(response, 'class="time-transfer-btn right end"', html=False)
        self.assertContains(response, 'placeholder="00:00:00:0"', html=False)
        self.assertContains(response, 'placeholder="00:00:10:0"', html=False)
        self.assertContains(response, 'maxlength="10"', html=False)
        self.assertContains(response, 'syncBar(false, true)', html=False)
        self.assertContains(response, 'startSec + 0.1', html=False)
        self.assertContains(response, 'startSec - 0.1', html=False)
        self.assertContains(response, 'endSec + 0.1', html=False)
        self.assertContains(response, 'endSec - 0.1', html=False)
        self.assertContains(response, "seekStartBtn.addEventListener('click', () => applyStartInput(true));")
        self.assertContains(response, "seekEndBtn.addEventListener('click', () => applyEndInput(true));")
        self.assertContains(response, "event.code !== 'Space'")
        self.assertNotContains(response, 'id="playerFullscreenBtn"', html=False)
        self.assertNotContains(response, 'id="playerPiPBtn"', html=False)
        self.assertNotContains(response, 'id="ytInteractionLayer"', html=False)
        self.assertNotContains(response, 'id="durationChip"', html=False)
        self.assertNotContains(response, "선택 구간:")
        self.assertNotContains(response, 'placeholder="00:00:00:000"', html=False)
        self.assertNotContains(response, 'placeholder="00:00:10:000"', html=False)
        self.assertNotContains(response, "우클릭으로 현재 시간을 시작/종료에 저장")
        self.assertNotContains(response, "우클릭 메뉴 또는 버튼으로 현재 시간을 바로 저장할 수 있습니다.")
        self.assertNotContains(response, "클립 구간 설정")
        self.assertNotContains(response, "1초씩 이동")

    def test_non_owner_cannot_view_detail(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("videos:detail", args=[self.linked_video.id]))

        self.assertEqual(response.status_code, 404)

    def test_owner_can_fetch_job_status_json(self):
        self.client.force_login(self.owner)
        job = BackgroundJob.objects.create(
            user=self.owner,
            job_type=BackgroundJobType.YOUTUBE_DOWNLOAD,
            related_object_type="master_video",
            related_object_id=str(self.linked_video.id),
            status=BackgroundJobState.PROCESSING,
            progress_percent=42,
            message="Packaging source video for playback",
        )

        response = self.client.get(reverse("videos:job-status", args=[self.linked_video.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["job"]["id"], job.id)
        self.assertEqual(payload["job"]["progress_percent"], 42)

    def test_non_owner_cannot_fetch_job_status_json(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("videos:job-status", args=[self.linked_video.id]))

        self.assertEqual(response.status_code, 404)


class StalePendingMasterVideoNormalizationTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="stale-owner", password="pw123456")
        self.client.force_login(self.owner)

    def test_list_marks_stale_pending_video_without_active_job_failed(self):
        video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="stalepending1",
            youtube_url="https://www.youtube.com/watch?v=stalepending1",
            title="Stale Pending Video",
            download_status=ProcessingState.PENDING,
        )
        stale_time = timezone.now() - timedelta(minutes=20)
        MasterVideo.objects.filter(id=video.id).update(created_at=stale_time, updated_at=stale_time)

        response = self.client.get(reverse("videos:linked-list"))

        self.assertEqual(response.status_code, 200)
        video.refresh_from_db()
        self.assertEqual(video.download_status, ProcessingState.FAILED)
        self.assertEqual(video.download_error_message, STALE_PENDING_MASTER_VIDEO_ERROR)

    def test_list_keeps_pending_video_when_active_job_exists(self):
        video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Active Pending Video",
            download_status=ProcessingState.PENDING,
        )
        stale_time = timezone.now() - timedelta(minutes=20)
        MasterVideo.objects.filter(id=video.id).update(created_at=stale_time, updated_at=stale_time)
        BackgroundJob.objects.create(
            user=self.owner,
            job_type=BackgroundJobType.MASTER_VIDEO_UPLOAD_PROCESS,
            related_object_type="master_video",
            related_object_id=str(video.id),
            status=BackgroundJobState.QUEUED,
            progress_percent=0,
            message="Queued for processing",
        )

        response = self.client.get(reverse("videos:upload-list"))

        self.assertEqual(response.status_code, 200)
        video.refresh_from_db()
        self.assertEqual(video.download_status, ProcessingState.PENDING)
        self.assertEqual(video.download_error_message, "")


class RegisterVideoViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="split-user", password="pw123456")
        self.client.force_login(self.user)

    def test_generic_add_video_page_loads(self):
        response = self.client.get(reverse("videos:create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add Video")
        self.assertContains(response, "Linked Video")
        self.assertContains(response, "Upload")
        self.assertContains(response, "Save Video")
        self.assertNotContains(response, "YouTube URL 입력")

    def test_legacy_youtube_route_uses_clipmaster_add_page(self):
        response = self.client.get(reverse("videos:create-youtube"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "영상 추가")
        self.assertContains(response, "YouTube URL 입력")
        self.assertContains(response, "저장된 영상")
        self.assertContains(response, "썸네일 복사")
        self.assertContains(response, "copyThumbToClipboard")
        self.assertContains(response, "ClipboardItem({'image/png': pngBlob})")
        self.assertNotContains(response, "writeText(")

    def test_legacy_upload_route_uses_generic_page(self):
        response = self.client.get(reverse("videos:create-video"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add Video")
        self.assertContains(response, "Upload")

    def test_add_video_page_lists_recent_items(self):
        MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="abc123",
            youtube_url="https://www.youtube.com/watch?v=abc123",
            title="Recent Linked Video",
            download_status=ProcessingState.READY,
        )

        response = self.client.get(reverse("videos:create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recent Videos")
        self.assertContains(response, "Recent Linked Video")


@override_settings(CSRF_COOKIE_HTTPONLY=True)
class RegisterVideoAjaxCsrfTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.user = get_user_model().objects.create_user(username="csrf-user", password="pw123456")
        self.client.force_login(self.user)

    @patch("videos.views.YtDlpService.fetch_metadata")
    def test_fetch_info_ajax_accepts_dom_csrf_token_when_cookie_is_httponly(self, fetch_metadata_mock):
        fetch_metadata_mock.return_value = {
            "title": "Fetched Title",
            "description": "Fetched Description",
            "thumbnail": "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
            "duration": 212,
            "uploader": "Fetched Channel",
        }

        page_response = self.client.get(reverse("videos:create"))
        self.assertEqual(page_response.status_code, 200)
        csrf_token = extract_csrf_token(page_response.content.decode("utf-8"))

        response = self.client.post(
            reverse("videos:api-fetch-info"),
            data=json.dumps({"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["title"], "Fetched Title")

    @patch("videos.views.urlopen")
    @patch("videos.views.YtDlpService.fetch_metadata")
    def test_fetch_info_ajax_falls_back_to_oembed_when_ytdlp_metadata_fails(self, fetch_metadata_mock, urlopen_mock):
        fetch_metadata_mock.side_effect = YtDlpTransientError("yt-dlp metadata failed")
        urlopen_mock.return_value = DummyJsonResponse(
            {
                "title": "Fallback Title",
                "author_name": "Fallback Channel",
            }
        )

        page_response = self.client.get(reverse("videos:create"))
        self.assertEqual(page_response.status_code, 200)
        csrf_token = extract_csrf_token(page_response.content.decode("utf-8"))

        response = self.client.post(
            reverse("videos:api-fetch-info"),
            data=json.dumps({"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["exists"])
        self.assertEqual(payload["title"], "Fallback Title")
        self.assertEqual(payload["channel"], "Fallback Channel")
        self.assertEqual(payload["duration"], 0)
        self.assertIn("img.youtube.com/vi/dQw4w9WgXcQ/maxresdefault.jpg", payload["thumbnail_url"])

    @patch("videos.views.urlopen")
    @patch("videos.views.YtDlpService.fetch_metadata")
    def test_fetch_info_ajax_uses_page_description_when_oembed_has_none(self, fetch_metadata_mock, urlopen_mock):
        fetch_metadata_mock.side_effect = YtDlpTransientError("yt-dlp metadata failed")

        def urlopen_side_effect(request, timeout=5):
            if "oembed" in request.full_url:
                return DummyJsonResponse(
                    {
                        "title": "Fallback Title",
                        "author_name": "Fallback Channel",
                    }
                )
            return DummyBytesResponse(
                b'<meta property="og:description" content="Page description from youtube">'
                b'<meta property="og:image" content="https://img.example/fallback.jpg">'
            )

        urlopen_mock.side_effect = urlopen_side_effect

        page_response = self.client.get(reverse("videos:create"))
        self.assertEqual(page_response.status_code, 200)
        csrf_token = extract_csrf_token(page_response.content.decode("utf-8"))

        response = self.client.post(
            reverse("videos:api-fetch-info"),
            data=json.dumps({"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["description"], "Page description from youtube")
        self.assertEqual(payload["thumbnail_url"], "https://img.example/fallback.jpg")


class MasterVideoSaveAjaxTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="save-ajax-user", password="pw123456")
        self.client.force_login(self.user)

    def test_save_video_persists_youtube_description(self):
        response = self.client.post(
            reverse("videos:api-save"),
            data=json.dumps(
                {
                    "url": "https://www.youtube.com/watch?v=desctest001",
                    "title": "Saved Video",
                    "description": "Fetched Description From Youtube",
                    "thumbnail_url": "https://img.youtube.com/vi/desctest001/hqdefault.jpg",
                    "duration": 135,
                    "channel": "Bird Channel",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])

        video = MasterVideo.objects.get(owner=self.user, youtube_video_id="desctest001")
        self.assertEqual(video.description, "Fetched Description From Youtube")
        self.assertEqual(video.youtube_url, "https://www.youtube.com/watch?v=desctest001")

    @patch("videos.views.urlopen")
    @patch("videos.views.YtDlpService.fetch_metadata")
    def test_save_video_fills_blank_description_from_fallback_page_metadata(self, fetch_metadata_mock, urlopen_mock):
        fetch_metadata_mock.side_effect = YtDlpTransientError("yt-dlp metadata failed")

        def urlopen_side_effect(request, timeout=5):
            if "oembed" in request.full_url:
                return DummyJsonResponse(
                    {
                        "title": "Fallback Title",
                        "author_name": "Fallback Channel",
                    }
                )
            return DummyBytesResponse(
                b'<meta property="og:description" content="Recovered description from page">'
                b'<meta property="og:image" content="https://img.example/recovered.jpg">'
            )

        urlopen_mock.side_effect = urlopen_side_effect

        response = self.client.post(
            reverse("videos:api-save"),
            data=json.dumps(
                {
                    "url": "https://www.youtube.com/watch?v=blankdesc01",
                    "title": "Saved Video",
                    "description": "",
                    "thumbnail_url": "",
                    "duration": 0,
                    "channel": "",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])

        video = MasterVideo.objects.get(owner=self.user, youtube_video_id="blankdesc01")
        self.assertEqual(video.description, "Recovered description from page")
        self.assertEqual(video.thumbnail_url, "https://img.example/recovered.jpg")
        self.assertEqual(video.channel_name, "Fallback Channel")


class YtDlpServiceTests(TestCase):
    @patch("videos.services.ytdlp.subprocess.run")
    @patch("videos.services.ytdlp.shutil.which")
    def test_fetch_metadata_uses_node_runtime_when_available(self, which_mock, run_mock):
        which_mock.side_effect = lambda value: {
            "yt-dlp": "/usr/bin/yt-dlp",
            "node": "/usr/bin/node",
        }.get(value)
        run_mock.return_value.stdout = "{}"

        service = YtDlpService()
        service.fetch_metadata("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        command = run_mock.call_args.args[0]
        self.assertEqual(command[:3], ["yt-dlp", "--js-runtimes", "node:/usr/bin/node"])
        self.assertIn("--dump-single-json", command)

    def test_download_clip_section_uses_python_ytdlp_download_ranges(self):
        output_dir = Path(tempfile.mkdtemp())
        recorded: dict[str, object] = {}

        def fake_download_range_func(_ctx, ranges):
            recorded["ranges"] = ranges
            return "range-func"

        class FakeYoutubeDL:
            def __init__(self, options):
                recorded["options"] = options

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def download(self, urls):
                recorded["urls"] = urls
                (output_dir / "clip.mp4").write_bytes(b"clip")

        fake_module = SimpleNamespace(
            YoutubeDL=FakeYoutubeDL,
            utils=SimpleNamespace(
                download_range_func=fake_download_range_func,
                DownloadError=RuntimeError,
            ),
        )

        service = YtDlpService()
        with patch.object(service, "_yt_dlp_module", return_value=fake_module):
            result = service.download_clip_section(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                output_dir,
                start_seconds=12.3,
                end_seconds=45.6,
            )

        self.assertEqual(result, output_dir / "clip.mp4")
        self.assertEqual(recorded["ranges"], [(12.3, 45.6)])
        self.assertEqual(recorded["urls"], ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
        options = recorded["options"]
        self.assertEqual(options["download_ranges"], "range-func")
        self.assertTrue(options["force_keyframes_at_cuts"])
        self.assertEqual(options["merge_output_format"], "mp4")
        self.assertTrue(options["noplaylist"])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class MasterVideoEditDeleteDownloadTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="edit-owner", password="pw123456")
        self.viewer = get_user_model().objects.create_user(username="edit-viewer", password="pw123456")
        self.video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Editable Video",
            download_status=ProcessingState.READY,
        )
        self.video.video_file.save("editable.mp4", ContentFile(b"video-bytes"), save=False)
        self.video.hls_manifest_file.save("index.m3u8", ContentFile(b"#EXTM3U\n"), save=False)
        self.video.subtitle_file.save("editable.vtt", ContentFile(b"WEBVTT\n"), save=False)
        self.video.save(update_fields=["video_file", "hls_manifest_file", "subtitle_file", "updated_at"])
        self.linked_video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="blogedit001",
            youtube_url="https://www.youtube.com/watch?v=blogedit001",
            title="Bloggable Video",
            description="Stored youtube description",
            download_status=ProcessingState.READY,
        )
        self.linked_video.hls_manifest_file.save("linked-index.m3u8", ContentFile(b"#EXTM3U\n"), save=False)
        self.linked_video.save(update_fields=["hls_manifest_file", "updated_at"])

    def test_owner_can_update_video_metadata(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("videos:edit", args=[self.video.id]),
            {
                "title": "Edited Title",
                "description": "Updated description",
                "remove_thumbnail": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.video.refresh_from_db()
        self.assertEqual(self.video.title, "Edited Title")
        self.assertEqual(self.video.description, "Updated description")

    def test_linked_video_edit_page_uses_blog_edit_copy_and_shows_url(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("videos:edit", args=[self.linked_video.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "블로그편집")
        self.assertContains(response, "URL")
        self.assertContains(response, self.linked_video.youtube_url)
        self.assertContains(response, "Stored youtube description")
        self.assertContains(response, "썸네일 이미지 추출")
        self.assertContains(response, 'class="thumb-panel-actions"', html=False)
        self.assertContains(response, 'class="section-card thumb-extract-section"', html=False)
        self.assertContains(response, 'id="thumbExtractPlayer"', html=False)
        self.assertContains(response, 'id="thumbExtractYoutubePlayer"', html=False)
        self.assertContains(response, 'id="thumbCaptureSaveBtn"', html=False)
        self.assertContains(response, 'id="thumbCaptureModal"', html=False)
        self.assertContains(response, 'id="thumbCaptureFilename"', html=False)
        self.assertContains(response, 'id="thumbCaptureDescription"', html=False)
        self.assertContains(response, 'id="thumbCaptureConfirmBtn"', html=False)
        self.assertContains(response, "function ensureThumbExtractPlayerReady()", html=False)
        self.assertContains(response, "async function primeThumbExtractFrame(targetSeconds)", html=False)
        self.assertContains(response, "openThumbCaptureModal({", html=False)
        self.assertNotContains(response, "thumbSeekNowBtn.addEventListener", html=False)
        self.assertNotContains(response, "thumbSeekApplyBtn.addEventListener", html=False)
        self.assertNotContains(response, 'id="thumbSeekInput"', html=False)
        self.assertNotContains(response, 'id="thumbSeekApplyBtn"', html=False)
        self.assertNotContains(response, 'id="thumbSeekNowBtn"', html=False)
        self.assertNotContains(response, 'id="thumbExtractCurrentTime"', html=False)
        self.assertContains(response, reverse("videos:thumbnail-update", args=[self.linked_video.id]), html=False)
        self.assertContains(response, 'const VIDEO_YOUTUBE_ID = "blogedit001";', html=False)
        self.assertContains(response, "const VIDEO_PLAYBACK_URL =", html=False)
        self.assertContains(response, 'const VIDEO_PLAYBACK_TYPE = "hls";', html=False)

    def test_linked_video_edit_page_shows_youtube_player_without_local_playback_url(self):
        self.client.force_login(self.owner)
        video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="ytplayeronly1",
            youtube_url="https://www.youtube.com/watch?v=ytplayeronly1",
            title="YouTube Player Only",
            description="No local playback prepared",
            download_status=ProcessingState.PENDING,
        )

        response = self.client.get(reverse("videos:edit", args=[video.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="thumbExtractYoutubePlayer"', html=False)
        self.assertContains(response, 'const VIDEO_YOUTUBE_ID = "ytplayeronly1";', html=False)
        self.assertNotContains(response, "재생 가능한 원본이 준비되면 여기서 특정 장면을 썸네일로 추출하고 저장할 수 있습니다.")

    @patch("videos.views.YtDlpService.fetch_metadata")
    def test_linked_video_edit_page_recovers_blank_description_from_metadata(self, fetch_metadata_mock):
        self.client.force_login(self.owner)
        self.linked_video.description = ""
        self.linked_video.save(update_fields=["description", "updated_at"])
        fetch_metadata_mock.return_value = {
            "title": self.linked_video.title,
            "description": "Recovered description from metadata",
            "thumbnail": self.linked_video.thumbnail_url,
            "duration": 180,
            "uploader": "Recovered Channel",
            "channel": "Recovered Channel",
        }

        response = self.client.get(reverse("videos:edit", args=[self.linked_video.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recovered description from metadata")
        self.linked_video.refresh_from_db()
        self.assertEqual(self.linked_video.description, "Recovered description from metadata")

    def test_owner_can_download_video_file(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("videos:download", args=[self.video.id]))

        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename="editable', response["Content-Disposition"])
        self.assertTrue(response["Content-Disposition"].endswith('.mp4"'))

    def test_non_owner_cannot_download_video_file(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("videos:download", args=[self.video.id]))

        self.assertEqual(response.status_code, 404)

    def test_owner_can_delete_uploaded_video(self):
        self.client.force_login(self.owner)

        response = self.client.post(reverse("videos:delete", args=[self.video.id]))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("videos:upload-list"))
        self.assertFalse(MasterVideo.objects.filter(id=self.video.id).exists())

    def test_non_owner_cannot_delete_uploaded_video(self):
        self.client.force_login(self.viewer)

        response = self.client.post(reverse("videos:delete", args=[self.video.id]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(MasterVideo.objects.filter(id=self.video.id).exists())


@override_settings(
    ALLOWED_HOSTS=["testserver", "anglangl.thesysm.com", "127.0.0.1", "localhost"],
    CSRF_TRUSTED_ORIGINS=["https://anglangl.thesysm.com"],
)
class MasterVideoDeleteCsrfRegressionTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.owner = get_user_model().objects.create_user(
            username="shared@example.com",
            email="shared@example.com",
            password="pw123456",
        )
        self.video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="sharedvideo1",
            youtube_url="https://www.youtube.com/watch?v=sharedvideo1",
            title="Shared Linked Video",
            download_status=ProcessingState.FAILED,
        )
        self.client.cookies[settings.THEPEACH_SSO_ACCESS_COOKIE_NAME] = "shared-access"
        self.client.cookies[settings.THEPEACH_SSO_REFRESH_COOKIE_NAME] = "shared-refresh"

    @patch("platform_auth.services.urlopen")
    def test_linked_video_delete_survives_authenticated_followup_get(self, urlopen_mock):
        profile_payload = {
            "success": True,
            "data": {
                "id": "tp-shared",
                "email": "shared@example.com",
                "display_name": "Shared User",
                "full_name": "Shared User",
                "first_name": "Shared",
                "last_name": "User",
                "is_active": True,
            },
        }
        urlopen_mock.side_effect = [
            DummyJsonResponse(profile_payload),
            DummyJsonResponse(profile_payload),
            DummyJsonResponse(profile_payload),
        ]

        list_url = reverse("videos:linked-list")
        host = "anglangl.thesysm.com"
        referer = f"https://{host}{list_url}"

        first_response = self.client.get(list_url, secure=True, HTTP_HOST=host)
        self.assertEqual(first_response.status_code, 200)
        first_cookie = self.client.cookies["csrftoken"].value
        first_token = extract_csrf_token(first_response.content.decode("utf-8"))

        second_response = self.client.get(list_url, secure=True, HTTP_HOST=host)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(self.client.cookies["csrftoken"].value, first_cookie)

        delete_response = self.client.post(
            reverse("videos:delete", args=[self.video.id]),
            {
                "csrfmiddlewaretoken": first_token,
                "next": list_url,
            },
            secure=True,
            HTTP_HOST=host,
            HTTP_REFERER=referer,
        )

        self.assertRedirects(delete_response, list_url, fetch_redirect_response=False)
        self.assertFalse(MasterVideo.objects.filter(id=self.video.id).exists())


class MasterVideoRetryViewTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="retry-owner", password="pw123456")
        self.viewer = get_user_model().objects.create_user(username="retry-viewer", password="pw123456")
        self.failed_video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="retryfailed1",
            youtube_url="https://www.youtube.com/watch?v=retryfailed1",
            title="Retry Failed",
            download_status=ProcessingState.FAILED,
            download_error_message="boom",
        )
        self.pending_video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="retrypending1",
            youtube_url="https://www.youtube.com/watch?v=retrypending1",
            title="Retry Pending",
            download_status=ProcessingState.PENDING,
        )
        self.ready_video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="retryready1",
            youtube_url="https://www.youtube.com/watch?v=retryready1",
            title="Retry Ready",
            download_status=ProcessingState.READY,
        )
        self.upload_video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Upload Video",
            download_status=ProcessingState.FAILED,
        )

    @patch("videos.views.download_youtube_video.delay")
    def test_owner_can_reload_failed_linked_video(self, delay_mock):
        delay_mock.return_value.id = "celery-reload-failed-1"
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("videos:retry", args=[self.failed_video.id]),
            {"next": reverse("videos:linked-list")},
        )

        self.assertRedirects(response, reverse("videos:linked-list"))
        self.failed_video.refresh_from_db()
        self.assertEqual(self.failed_video.download_status, ProcessingState.QUEUED)
        self.assertEqual(self.failed_video.download_error_message, "")
        delay_mock.assert_called_once_with(self.failed_video.id)

        job = BackgroundJob.objects.get(related_object_type="master_video", related_object_id=str(self.failed_video.id))
        self.assertEqual(job.job_type, BackgroundJobType.YOUTUBE_DOWNLOAD)
        self.assertEqual(job.status, BackgroundJobState.QUEUED)
        self.assertEqual(job.message, "Reload queued")
        self.assertEqual(job.celery_task_id, "celery-reload-failed-1")

    @patch("videos.views.download_youtube_video.delay")
    def test_owner_can_reload_pending_linked_video(self, delay_mock):
        delay_mock.return_value.id = "celery-reload-pending-1"
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("videos:retry", args=[self.pending_video.id]),
            {"next": reverse("videos:linked-list")},
        )

        self.assertRedirects(response, reverse("videos:linked-list"))
        self.pending_video.refresh_from_db()
        self.assertEqual(self.pending_video.download_status, ProcessingState.QUEUED)
        delay_mock.assert_called_once_with(self.pending_video.id)

    def test_owner_cannot_reload_ready_linked_video(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("videos:retry", args=[self.ready_video.id]),
            {"next": reverse("videos:linked-list")},
        )

        self.assertRedirects(response, reverse("videos:linked-list"))
        self.ready_video.refresh_from_db()
        self.assertEqual(self.ready_video.download_status, ProcessingState.READY)

    def test_non_owner_cannot_reload_linked_video(self):
        self.client.force_login(self.viewer)

        response = self.client.post(
            reverse("videos:retry", args=[self.failed_video.id]),
            {"next": reverse("videos:linked-list")},
        )

        self.assertEqual(response.status_code, 404)

    def test_owner_cannot_reload_uploaded_video(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("videos:retry", args=[self.upload_video.id]),
            {"next": reverse("videos:upload-list")},
        )

        self.assertRedirects(response, reverse("videos:upload-list"))
        self.upload_video.refresh_from_db()
        self.assertEqual(self.upload_video.download_status, ProcessingState.FAILED)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class MasterVideoSubtitleUpdateViewTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="subtitle-owner", password="pw123456")
        self.viewer = get_user_model().objects.create_user(username="subtitle-viewer", password="pw123456")
        self.video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Subtitle Video",
            download_status=ProcessingState.READY,
        )

    def test_owner_can_upload_subtitle_later(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("videos:subtitle-update", args=[self.video.id]),
            {"subtitle_file": SimpleUploadedFile("later.vtt", b"WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n", content_type="text/vtt")},
        )

        self.assertEqual(response.status_code, 302)
        self.video.refresh_from_db()
        self.assertTrue(self.video.subtitle_file.name.endswith("later.vtt"))

    def test_non_owner_cannot_upload_subtitle_later(self):
        self.client.force_login(self.viewer)

        response = self.client.post(
            reverse("videos:subtitle-update", args=[self.video.id]),
            {"subtitle_file": SimpleUploadedFile("later.vtt", b"WEBVTT\n", content_type="text/vtt")},
        )

        self.assertEqual(response.status_code, 404)


@override_settings(MEDIA_ROOT=VIDEO_THUMBNAIL_MEDIA_ROOT)
class VideoThumbnailUpdateTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(VIDEO_THUMBNAIL_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="owner2", password="pw123456")
        self.viewer = get_user_model().objects.create_user(username="viewer2", password="pw123456")
        self.video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Local Upload",
            video_file="videos/files/local.mp4",
            download_status=ProcessingState.READY,
        )

    def test_owner_can_upload_thumbnail_for_video(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("videos:thumbnail-update", args=[self.video.id]),
            {"thumbnail_file": SimpleUploadedFile("thumb.gif", TEST_IMAGE_BYTES, content_type="image/gif")},
        )

        self.assertEqual(response.status_code, 200)
        self.video.refresh_from_db()
        self.assertTrue(self.video.custom_thumbnail_file.name)
        self.assertTrue(self.video.thumbnail)
        self.assertIn("/media/", self.video.thumbnail)
        self.assertTrue(self.video.custom_thumbnail_file.name.startswith("thumbnails/"))

    def test_owner_can_upload_thumbnail_with_custom_name_and_description(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("videos:thumbnail-update", args=[self.video.id]),
            {
                "thumbnail_file": SimpleUploadedFile("thumb.gif", TEST_IMAGE_BYTES, content_type="image/gif"),
                "thumbnail_filename": "scene-capture.png",
                "thumbnail_description": "우산처럼 새들이 모여 있는 장면",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.video.refresh_from_db()
        self.assertEqual(self.video.custom_thumbnail_description, "우산처럼 새들이 모여 있는 장면")
        self.assertIn("scene-capture", self.video.custom_thumbnail_file.name)
        self.assertEqual(payload["thumbnail_description"], "우산처럼 새들이 모여 있는 장면")
        self.assertIn("scene-capture", payload["thumbnail_file_name"])

    def test_owner_can_replace_existing_thumbnail(self):
        self.client.force_login(self.owner)

        first_response = self.client.post(
            reverse("videos:thumbnail-update", args=[self.video.id]),
            {"thumbnail_file": SimpleUploadedFile("thumb1.gif", TEST_IMAGE_BYTES, content_type="image/gif")},
        )
        self.assertEqual(first_response.status_code, 200)
        self.video.refresh_from_db()
        first_url = self.video.custom_thumbnail_file.name

        second_response = self.client.post(
            reverse("videos:thumbnail-update", args=[self.video.id]),
            {"thumbnail_file": SimpleUploadedFile("thumb2.gif", TEST_IMAGE_BYTES, content_type="image/gif")},
        )

        self.assertEqual(second_response.status_code, 200)
        self.video.refresh_from_db()
        self.assertTrue(self.video.custom_thumbnail_file.name)
        self.assertNotEqual(first_url, self.video.custom_thumbnail_file.name)
        self.assertTrue(self.video.custom_thumbnail_file.name.startswith("thumbnails/"))

    def test_non_owner_cannot_upload_thumbnail(self):
        self.client.force_login(self.viewer)

        response = self.client.post(
            reverse("videos:thumbnail-update", args=[self.video.id]),
            {"thumbnail_file": SimpleUploadedFile("thumb.gif", TEST_IMAGE_BYTES, content_type="image/gif")},
        )

        self.assertEqual(response.status_code, 404)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ThumbnailRelocationCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="thumb-move-user", password="pw123456")
        self.video = MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="move-thumb-1",
            youtube_url="https://www.youtube.com/watch?v=move-thumb-1",
            title="Move Thumb Video",
            download_status=ProcessingState.READY,
        )
        self.clip = Clip.objects.create(
            owner=self.user,
            source_type=ClipSourceType.EXTRACTED,
            master_video=self.video,
            title="Move Thumb Clip",
            start_time_seconds=0.0,
            end_time_seconds=5.0,
            duration_seconds=5.0,
            file_status=ProcessingState.READY,
        )

        self.legacy_video_thumb = default_storage.save(
            "video_thumbs/user_1/legacy-video-thumb.jpg",
            ContentFile(TEST_IMAGE_BYTES),
        )
        self.legacy_clip_custom_thumb = default_storage.save(
            "clip_thumbs/user_1/legacy-clip-custom.jpg",
            ContentFile(TEST_IMAGE_BYTES),
        )
        self.legacy_clip_generated_thumb = default_storage.save(
            "clips/thumbnails/legacy-clip-generated.jpg",
            ContentFile(TEST_IMAGE_BYTES),
        )

        self.video.saved_thumbnail_file.name = self.legacy_video_thumb
        self.video.save(update_fields=["saved_thumbnail_file", "updated_at"])
        self.clip.custom_thumbnail_file.name = self.legacy_clip_custom_thumb
        self.clip.thumbnail_file.name = self.legacy_clip_generated_thumb
        self.clip.save(update_fields=["custom_thumbnail_file", "thumbnail_file", "updated_at"])

    def test_relocate_thumbnail_files_moves_legacy_thumbnail_paths_under_thumbnails(self):
        call_command("relocate_thumbnail_files")

        self.video.refresh_from_db()
        self.clip.refresh_from_db()

        self.assertTrue(self.video.saved_thumbnail_file.name.startswith("thumbnails/"))
        self.assertTrue(self.clip.custom_thumbnail_file.name.startswith("thumbnails/"))
        self.assertTrue(self.clip.thumbnail_file.name.startswith("thumbnails/"))
        self.assertFalse(default_storage.exists(self.legacy_video_thumb))
        self.assertFalse(default_storage.exists(self.legacy_clip_custom_thumb))
        self.assertFalse(default_storage.exists(self.legacy_clip_generated_thumb))
