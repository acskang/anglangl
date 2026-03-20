import tempfile
from pathlib import Path
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from core.models import ProcessingState
from videos.models import MasterVideo, MasterVideoSourceType
from workers.models import BackgroundJob, BackgroundJobType

from .models import Clip, ClipSourceType


class ClipVisibilityTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="owner", password="pw123456")
        self.viewer = get_user_model().objects.create_user(username="viewer", password="pw123456")
        self.video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="clipvideo001",
            youtube_url="https://www.youtube.com/watch?v=clipvideo001",
            title="Owner Video",
            download_status=ProcessingState.READY,
            duration_seconds=180,
        )
        self.clip = Clip.objects.create(
            owner=self.owner,
            source_type=ClipSourceType.EXTRACTED,
            master_video=self.video,
            title="Shared Clip",
            start_time_seconds=5,
            end_time_seconds=25,
            duration_seconds=20,
            file_status=ProcessingState.READY,
        )

    def test_list_includes_clips_from_other_users(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("clips:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shared Clip")
        self.assertContains(response, "@owner")

    def test_detail_allows_viewing_other_users_clip_without_manage_actions(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("clips:detail", args=[self.clip.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shared Clip")
        self.assertContains(response, "@owner")
        self.assertNotContains(response, "Processing Job History")
        self.assertNotContains(response, 'href="%s"' % reverse("clips:edit", args=[self.clip.id]), html=False)
        self.assertNotContains(response, 'href="%s"' % reverse("clips:delete", args=[self.clip.id]), html=False)
        self.assertNotContains(response, "Edit Title / Description")

    def test_non_owner_cannot_edit_other_users_clip(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("clips:edit", args=[self.clip.id]))

        self.assertEqual(response.status_code, 404)

    def test_non_owner_cannot_delete_other_users_clip(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("clips:delete", args=[self.clip.id]))

        self.assertEqual(response.status_code, 404)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ClipExtractionWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="planner", password="pw123456")
        self.client.force_login(self.user)
        self.video = MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Movie Night",
            video_file="videos/files/movie.mp4",
            hls_manifest_file="master_videos/hls/user_1/1/index.m3u8",
            duration_seconds=300,
            download_status=ProcessingState.READY,
        )
        self.video.subtitle_file.save(
            "movie.srt",
            ContentFile(
                b"1\n00:00:05,000 --> 00:00:08,000\nHello there.\n\n2\n00:00:10,000 --> 00:00:13,000\nGeneral Kenobi.\n"
            ),
            save=False,
        )
        self.video.save(update_fields=["subtitle_file", "updated_at"])

    def test_plan_generation_from_subtitles(self):
        response = self.client.post(
            reverse("clips:create"),
            {
                "action": "plan",
                "master_video": self.video.id,
                "range_start": "00:00:00",
                "range_end": "00:00:20",
                "is_public": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hello there.")
        self.assertContains(response, "General Kenobi.")
        self.assertContains(response, "plan_total_rows")

    @patch("clips.views.extract_clip.delay")
    def test_extract_creates_multiple_clips_from_plan_rows(self, delay_mock):
        delay_mock.return_value.id = "task-1"

        response = self.client.post(
            reverse("clips:create"),
            {
                "action": "extract",
                "master_video": self.video.id,
                "range_start": "00:00:00",
                "range_end": "00:00:20",
                "is_public": "on",
                "plan_total_rows": "2",
                "plan_selected_0": "on",
                "plan_start_0": "00:00:05",
                "plan_end_0": "00:00:08",
                "plan_subtitle_0": "Hello there.",
                "plan_selected_1": "on",
                "plan_start_1": "00:00:10",
                "plan_end_1": "00:00:13",
                "plan_subtitle_1": "General Kenobi.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Clip.objects.filter(master_video=self.video).count(), 2)
        first_clip = Clip.objects.filter(master_video=self.video).order_by("start_time_seconds").first()
        self.assertEqual(first_clip.subtitle, "Hello there.")
        self.assertTrue(first_clip.original_filename.endswith(".mp4"))
        self.assertEqual(delay_mock.call_count, 2)

    def test_subtitle_track_endpoint_returns_webvtt(self):
        response = self.client.get(reverse("clips:master-video-subtitle-vtt", args=[self.video.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/vtt; charset=utf-8")
        self.assertIn("WEBVTT", response.content.decode("utf-8"))
        self.assertIn("00:00:05.000 --> 00:00:08.000", response.content.decode("utf-8"))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ClipTaskTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="clip-task-user", password="pw123456")
        self.video = MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Source Video",
            download_status=ProcessingState.READY,
        )
        self.video.video_file.save("source.mp4", ContentFile(b"video-bytes"), save=False)
        self.video.save(update_fields=["video_file", "updated_at"])

    def test_extract_clip_marks_failed_and_cleans_partial_outputs_on_soft_timeout(self):
        clip = Clip.objects.create(
            owner=self.user,
            source_type=ClipSourceType.EXTRACTED,
            master_video=self.video,
            title="Timeout Clip",
            start_time_seconds=5,
            end_time_seconds=25,
            duration_seconds=20,
            file_status=ProcessingState.QUEUED,
        )
        job = BackgroundJob.objects.create(
            user=self.user,
            job_type=BackgroundJobType.CLIP_EXTRACTION,
            related_object_type="clip",
            related_object_id=str(clip.id),
            status="queued",
        )

        def raise_soft_timeout(*args, **kwargs):
            output_path = kwargs["output_path"]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"partial")
            raise SoftTimeLimitExceeded()

        from clips.tasks import extract_clip

        with patch("clips.tasks.FfmpegService.extract_clip", side_effect=raise_soft_timeout):
            extract_clip.run(clip.id)

        clip.refresh_from_db()
        job.refresh_from_db()

        self.assertEqual(clip.file_status, ProcessingState.FAILED)
        self.assertIn("soft time limit", clip.file_error_message.lower())
        self.assertEqual(job.status, "failed")
        clip_dir = Path(self.video.video_file.storage.location) / "clips" / f"user_{self.user.id}" / str(clip.id)
        self.assertFalse(clip_dir.exists())
