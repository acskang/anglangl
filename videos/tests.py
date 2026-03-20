import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import ProcessingState
from clips.models import Clip, ClipSourceType
from videos.forms import MasterVideoCreateForm
from videos.models import MasterVideo, MasterVideoSourceType
from workers.models import BackgroundJob, BackgroundJobType

TEST_IMAGE_BYTES = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
    b"\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00"
    b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01"
    b"\x00\x3b"
)
VIDEO_THUMBNAIL_MEDIA_ROOT = tempfile.mkdtemp()


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
        self.assertEqual(video.duration_seconds, None)
        self.assertTrue(video.video_file.name.endswith("lesson.mp4"))
        self.assertTrue(video.subtitle_file.name.endswith("lesson.srt"))
        self.assertFalse(video.hls_manifest_file)
        delay_mock.assert_called_once_with(video.id)

        job = BackgroundJob.objects.get(related_object_type="master_video", related_object_id=str(video.id))
        self.assertEqual(job.job_type, BackgroundJobType.MASTER_VIDEO_UPLOAD_PROCESS)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.celery_task_id, "celery-upload-task-1")


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
            status="queued",
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
        self.assertEqual(self.job.status, "success")
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
        self.assertEqual(self.job.status, "failed")
        probe_duration_mock.assert_called_once()
        generate_hls_mock.assert_called_once()


class MasterVideoVisibilityTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="owner", password="pw123456")
        self.viewer = get_user_model().objects.create_user(username="viewer", password="pw123456")
        self.video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="abc123xyz99",
            youtube_url="https://www.youtube.com/watch?v=abc123xyz99",
            title="Owner Video",
            download_status=ProcessingState.READY,
            duration_seconds=120,
        )
        self.clip = Clip.objects.create(
            owner=self.owner,
            source_type=ClipSourceType.EXTRACTED,
            master_video=self.video,
            title="Owner Clip",
            start_time_seconds=0,
            end_time_seconds=10,
            duration_seconds=10,
            file_status=ProcessingState.READY,
        )

    def test_youtube_list_includes_youtube_videos_from_other_users(self):
        self.client.force_login(self.viewer)
        MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Owner Upload",
            download_status=ProcessingState.READY,
        )

        response = self.client.get(reverse("videos:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Owner Video")
        self.assertContains(response, "@owner")
        self.assertNotContains(response, "Owner Upload")

    def test_upload_list_includes_uploaded_videos_from_other_users(self):
        self.client.force_login(self.viewer)
        uploaded = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Owner Upload",
            video_file="videos/files/owner.mp4",
            download_status=ProcessingState.READY,
        )

        response = self.client.get(reverse("videos:upload-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, uploaded.title)
        self.assertContains(response, "@owner")
        self.assertNotContains(response, "Owner Video")

    def test_detail_allows_viewing_other_users_video_without_manage_actions(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("videos:detail", args=[self.video.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Owner Video")
        self.assertContains(response, "Owner Clip")
        self.assertContains(response, "@owner")
        self.assertNotContains(response, 'href="%s?master_video=%s"' % (reverse("clips:create"), self.video.id), html=False)
        self.assertNotContains(response, reverse("workers:master-video-job-history", args=[self.video.id]), html=False)
        self.assertNotContains(response, reverse("videos:retry", args=[self.video.id]), html=False)

    def test_owner_can_fetch_job_status_json(self):
        self.client.force_login(self.owner)
        job = BackgroundJob.objects.create(
            user=self.owner,
            job_type=BackgroundJobType.YOUTUBE_DOWNLOAD,
            related_object_type="master_video",
            related_object_id=str(self.video.id),
            status="processing",
            progress_percent=42,
            message="Packaging downloaded video for playback",
        )

        response = self.client.get(reverse("videos:job-status", args=[self.video.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["job"]["id"], job.id)
        self.assertEqual(payload["job"]["progress_percent"], 42)

    def test_non_owner_cannot_fetch_job_status_json(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("videos:job-status", args=[self.video.id]))

        self.assertEqual(response.status_code, 403)


class RegisterVideoSplitViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="split-user", password="pw123456")
        self.client.force_login(self.user)

    def test_register_youtube_page_loads(self):
        response = self.client.get(reverse("videos:create-youtube"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Register Youtube")
        self.assertContains(response, 'value="youtube"', html=False)

    def test_register_video_page_loads(self):
        response = self.client.get(reverse("videos:create-video"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Register Video")
        self.assertContains(response, 'value="upload"', html=False)

    def test_register_youtube_page_lists_recent_youtube_items(self):
        MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="abc123",
            youtube_url="https://www.youtube.com/watch?v=abc123",
            title="Recent Youtube Video",
            download_status=ProcessingState.READY,
        )
        MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Local Upload",
            download_status=ProcessingState.READY,
        )

        response = self.client.get(reverse("videos:create-youtube"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recent Youtube")
        self.assertContains(response, "Recent Youtube Video")
        self.assertNotContains(response, "Local Upload")

    def test_register_video_page_lists_recent_upload_items(self):
        MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Recent Upload Video",
            video_file="videos/files/recent.mp4",
            download_status=ProcessingState.READY,
        )
        MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="onlyyoutube",
            youtube_url="https://www.youtube.com/watch?v=onlyyoutube",
            title="Youtube Only",
            download_status=ProcessingState.READY,
        )

        response = self.client.get(reverse("videos:create-video"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recent Video")
        self.assertContains(response, "Recent Upload Video")
        self.assertNotContains(response, "Youtube Only")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class MasterVideoDeleteViewTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="delete-owner", password="pw123456")
        self.viewer = get_user_model().objects.create_user(username="delete-viewer", password="pw123456")
        self.video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Delete Me",
            download_status=ProcessingState.READY,
        )
        self.video.video_file.save("delete-me.mp4", ContentFile(b"video-bytes"), save=False)
        self.video.hls_manifest_file.save("index.m3u8", ContentFile(b"#EXTM3U\n"), save=False)
        self.video.subtitle_file.save("delete-me.srt", ContentFile(b"1\n00:00:00,000 --> 00:00:01,000\nHi\n"), save=False)
        self.video.save(update_fields=["video_file", "hls_manifest_file", "subtitle_file", "updated_at"])

    def test_owner_can_delete_uploaded_video(self):
        self.client.force_login(self.owner)

        response = self.client.post(reverse("videos:delete", args=[self.video.id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(MasterVideo.objects.filter(id=self.video.id).exists())

    def test_non_owner_cannot_delete_uploaded_video(self):
        self.client.force_login(self.viewer)

        response = self.client.post(reverse("videos:delete", args=[self.video.id]))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(MasterVideo.objects.filter(id=self.video.id).exists())


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

        self.assertEqual(response.status_code, 403)


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

    def test_owner_can_upload_thumbnail_for_local_video(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("videos:thumbnail-update", args=[self.video.id]),
            {"thumbnail_file": SimpleUploadedFile("thumb.gif", TEST_IMAGE_BYTES, content_type="image/gif")},
        )

        self.assertEqual(response.status_code, 200)
        self.video.refresh_from_db()
        self.assertTrue(self.video.thumbnail_url)
        self.assertIn("/media/thumbnails/", self.video.thumbnail_url)

    def test_owner_can_replace_existing_thumbnail(self):
        self.client.force_login(self.owner)

        first_response = self.client.post(
            reverse("videos:thumbnail-update", args=[self.video.id]),
            {"thumbnail_file": SimpleUploadedFile("thumb1.gif", TEST_IMAGE_BYTES, content_type="image/gif")},
        )
        self.assertEqual(first_response.status_code, 200)
        self.video.refresh_from_db()
        first_url = self.video.thumbnail_url

        second_response = self.client.post(
            reverse("videos:thumbnail-update", args=[self.video.id]),
            {"thumbnail_file": SimpleUploadedFile("thumb2.gif", TEST_IMAGE_BYTES, content_type="image/gif")},
        )

        self.assertEqual(second_response.status_code, 200)
        self.video.refresh_from_db()
        self.assertTrue(self.video.thumbnail_url)
        self.assertNotEqual(first_url, self.video.thumbnail_url)

    def test_non_owner_cannot_upload_thumbnail(self):
        self.client.force_login(self.viewer)

        response = self.client.post(
            reverse("videos:thumbnail-update", args=[self.video.id]),
            {"thumbnail_file": SimpleUploadedFile("thumb.gif", TEST_IMAGE_BYTES, content_type="image/gif")},
        )

        self.assertEqual(response.status_code, 403)
