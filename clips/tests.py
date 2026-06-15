import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import BackgroundJobState, ProcessingState
from dramaNlearn.models import Video as DramaVideo
from videos.models import MasterVideo, MasterVideoSourceType
from workers.models import BackgroundJob, BackgroundJobType

from .models import AlbumImage, AlbumImageSourceType, Clip, ClipImage, ClipSourceType
from .services.ffmpeg import FfmpegService
from .services.whisper import WhisperTranscript
from .timecode import format_hhmmss, format_hhmmss_tenths, parse_hhmmss

TEST_IMAGE_BYTES = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
    b"\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00"
    b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01"
    b"\x00\x3b"
)


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
            title="Owner Clip",
            start_time_seconds=5,
            end_time_seconds=25,
            duration_seconds=20,
            file_status=ProcessingState.READY,
        )
        self.viewer_clip = Clip.objects.create(
            owner=self.viewer,
            source_type=ClipSourceType.UPLOADED,
            title="Viewer Clip",
            start_time_seconds=0,
            end_time_seconds=0,
            duration_seconds=0,
            file_status=ProcessingState.READY,
        )

    def test_list_redirects_to_dashboard(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clips:list"))

        self.assertRedirects(response, reverse("dashboard:home"))

    def test_detail_requires_ownership(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("clips:detail", args=[self.clip.id]))

        self.assertEqual(response.status_code, 404)

    def test_non_owner_cannot_edit_other_users_clip(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("clips:edit", args=[self.clip.id]))

        self.assertEqual(response.status_code, 404)

    def test_non_owner_cannot_delete_other_users_clip(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("clips:delete", args=[self.clip.id]))

        self.assertEqual(response.status_code, 404)


class TimecodeFormatTests(TestCase):
    def test_timecode_uses_single_tenth_digit_format(self):
        self.assertEqual(format_hhmmss(1733.9), "00:28:53:9")
        self.assertEqual(parse_hhmmss("00:28:53:9"), 1733.9)
        self.assertEqual(parse_hhmmss("00:28:53:900"), 1733.9)

    def test_timecode_display_uses_decimal_tenth_suffix(self):
        self.assertEqual(format_hhmmss_tenths(1733.9), "00:28:53.9s")


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

    @patch("clips.views.extract_clip.delay")
    def test_api_create_clip_from_linked_video_without_local_file(self, delay_mock):
        delay_mock.return_value.id = "task-linked-clip-1"
        linked_video = MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="linkedvideo001",
            youtube_url="https://www.youtube.com/watch?v=linkedvideo001",
            title="Linked Source",
            duration_seconds=300,
            download_status=ProcessingState.READY,
        )

        response = self.client.post(
            reverse("clips:api-create"),
            data=json.dumps({"master_video_id": linked_video.id, "start_time": 12.4, "end_time": 26.7}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        clip = Clip.objects.get(pk=payload["clip_id"])
        self.assertEqual(clip.master_video, linked_video)
        self.assertAlmostEqual(clip.start_time_seconds, 12.4)
        self.assertAlmostEqual(clip.end_time_seconds, 26.7)
        self.assertAlmostEqual(clip.duration_seconds, 14.3)
        self.assertEqual(clip.file_status, ProcessingState.QUEUED)
        delay_mock.assert_called_once_with(clip.id)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ClipmasterEditWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="clip-editor", password="pw123456")
        self.client.force_login(self.user)
        self.video = MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="clipmasteredit01",
            youtube_url="https://www.youtube.com/watch?v=clipmasteredit01",
            title="Clipmaster Source",
            duration_seconds=180,
            download_status=ProcessingState.READY,
        )
        self.clip = Clip.objects.create(
            owner=self.user,
            source_type=ClipSourceType.EXTRACTED,
            master_video=self.video,
            title="Editable Clip",
            description="clip description",
            start_time_seconds=5,
            end_time_seconds=20,
            duration_seconds=15,
            file_status=ProcessingState.READY,
        )
        self.clip.clip_file.save("editable.mp4", ContentFile(b"clip-bytes"), save=False)
        self.clip.save(update_fields=["clip_file", "updated_at"])

    def test_edit_view_renders_clipmaster_controls(self):
        response = self.client.get(reverse("clips:edit", args=[self.clip.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "클립 플레이어")
        self.assertContains(response, "클립 추출 시간")
        self.assertContains(response, "00:00:05.0s ~ 00:00:20.0s (00:00:15.0s)")
        self.assertContains(response, reverse("clips:api-update", args=[self.clip.id]))
        self.assertContains(response, reverse("clips:image-capture", args=[self.clip.id]))
        self.assertContains(response, reverse("clips:subtitle-extract", args=[self.clip.id]))

    @patch("clips.views.WhisperService.transcribe")
    def test_subtitle_extract_redirects_back_to_edit(self, transcribe_mock):
        transcribe_mock.return_value = SimpleNamespace(text="hello there", timing_json='[{"start":0,"end":1}]')
        edit_url = reverse("clips:edit", args=[self.clip.id])

        response = self.client.post(
            reverse("clips:subtitle-extract", args=[self.clip.id]),
            {
                "whisper_model": "base",
                "whisper_language": "en",
                "next": edit_url,
            },
        )

        self.assertRedirects(response, edit_url)
        preview = self.client.session.get(f"clip_subtitle_preview_{self.clip.id}")
        self.assertEqual(preview["text"], "hello there")
        self.assertEqual(preview["timing_json"], '[{"start":0,"end":1}]')

    @patch("clips.views.WhisperService.transcribe")
    def test_subtitle_extract_ajax_returns_preview_json(self, transcribe_mock):
        transcribe_mock.return_value = SimpleNamespace(text="ajax subtitle", timing_json='[{"start":0,"end":2}]')

        response = self.client.post(
            reverse("clips:subtitle-extract", args=[self.clip.id]),
            {
                "whisper_model": "base",
                "whisper_language": "en",
                "next": reverse("clips:edit", args=[self.clip.id]),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["text"], "ajax subtitle")
        preview = self.client.session.get(f"clip_subtitle_preview_{self.clip.id}")
        self.assertEqual(preview["text"], "ajax subtitle")
        self.assertEqual(preview["timing_json"], '[{"start":0,"end":2}]')

    @patch("clips.views._fetch_youtube_subtitle_preview")
    @patch("clips.views.WhisperService.transcribe")
    def test_subtitle_extract_falls_back_to_youtube_subtitles_when_whisper_empty(self, transcribe_mock, fallback_mock):
        transcribe_mock.return_value = WhisperTranscript(text="", timing_json="[]")
        fallback_mock.return_value = ("fallback subtitle", '[{"start":0,"end":3}]')

        response = self.client.post(
            reverse("clips:subtitle-extract", args=[self.clip.id]),
            {
                "whisper_model": "base",
                "whisper_language": "en",
                "next": reverse("clips:edit", args=[self.clip.id]),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["text"], "fallback subtitle")
        preview = self.client.session.get(f"clip_subtitle_preview_{self.clip.id}")
        self.assertEqual(preview["text"], "fallback subtitle")
        self.assertEqual(preview["timing_json"], '[{"start":0,"end":3}]')

    def test_subtitle_save_redirects_back_to_edit(self):
        edit_url = reverse("clips:edit", args=[self.clip.id])
        session = self.client.session
        session[f"clip_subtitle_preview_{self.clip.id}"] = {
            "text": "save this subtitle",
            "timing_json": '[{"start":0,"end":2}]',
        }
        session.save()

        response = self.client.post(
            reverse("clips:subtitle-save", args=[self.clip.id]),
            {
                "subtitle_text": "save this subtitle",
                "next": edit_url,
            },
        )

        self.assertRedirects(response, edit_url)
        self.clip.refresh_from_db()
        self.assertEqual(self.clip.subtitle, "save this subtitle")
        self.assertEqual(self.clip.subtitle_timing, '[{"start":0,"end":2}]')
        self.assertIsNone(self.client.session.get(f"clip_subtitle_preview_{self.clip.id}"))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ClipMediaManagementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="media-user", password="pw123456")
        self.viewer = get_user_model().objects.create_user(username="media-viewer", password="pw123456")
        self.client.force_login(self.user)
        self.video = MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Source Video",
            download_status=ProcessingState.READY,
        )
        self.clip = Clip.objects.create(
            owner=self.user,
            source_type=ClipSourceType.UPLOADED,
            title="Media Clip",
            start_time_seconds=0,
            end_time_seconds=10,
            duration_seconds=10,
            file_status=ProcessingState.READY,
        )
        self.clip.clip_file.save("clip.mp4", ContentFile(b"clip-bytes"), save=False)
        self.clip.save(update_fields=["clip_file", "updated_at"])

    def test_capture_image_creates_clip_image_and_album_image(self):
        image_data = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yFmsAAAAASUVORK5CYII="

        response = self.client.post(
            reverse("clips:image-capture", args=[self.clip.id]),
            data=json.dumps({"image_data": image_data, "capture_time": 1.5}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ClipImage.objects.filter(owner=self.user, clip=self.clip).exists())
        self.assertTrue(AlbumImage.objects.filter(owner=self.user, clip=self.clip, source=AlbumImageSourceType.CAPTURE).exists())

    def test_album_upload_creates_manual_album_image(self):
        response = self.client.post(
            reverse("clips:album-upload"),
            {
                "title": "Manual Upload",
                "description": "desc",
                "tags": "one,two",
                "image": SimpleUploadedFile(
                    "album.gif",
                    TEST_IMAGE_BYTES,
                    content_type="image/gif",
                ),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(AlbumImage.objects.filter(owner=self.user, title="Manual Upload").exists())

    def test_album_list_redirects_to_dashboard(self):
        AlbumImage.objects.create(
            owner=self.user,
            title="Mine",
            image=SimpleUploadedFile(
                "mine.gif",
                TEST_IMAGE_BYTES,
                content_type="image/gif",
            ),
            source=AlbumImageSourceType.UPLOAD,
        )

        response = self.client.get(reverse("clips:album-list"))

        self.assertRedirects(response, reverse("dashboard:home"))

    def test_non_owner_cannot_open_album_detail(self):
        image = AlbumImage.objects.create(
            owner=self.user,
            title="Mine",
            image=SimpleUploadedFile(
                "mine.gif",
                TEST_IMAGE_BYTES,
                content_type="image/gif",
            ),
            source=AlbumImageSourceType.UPLOAD,
        )
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("clips:album-detail", args=[image.id]))

        self.assertEqual(response.status_code, 404)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class FfmpegServiceTests(TestCase):
    def test_extract_clip_applies_input_options_before_input(self):
        service = FfmpegService()
        source_path = Path(tempfile.mkdtemp()) / "drama-source.m3u8"
        output_path = Path(tempfile.mkdtemp()) / "clip.mp4"
        thumbnail_path = Path(tempfile.mkdtemp()) / "thumb.jpg"
        source_path.write_text("#EXTM3U\n", encoding="utf-8")

        captured_args: list[str] = []

        def fake_run(args, timeout, progress_callback=None, expected_duration_seconds=None):
            nonlocal captured_args
            captured_args = list(args)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"clip")

        with (
            patch.object(service, "_run_ffmpeg_with_progress", side_effect=fake_run),
            patch.object(service, "generate_thumbnail", return_value=thumbnail_path),
        ):
            service.extract_clip(
                source_path=source_path,
                output_path=output_path,
                thumbnail_path=thumbnail_path,
                start_seconds=12.3,
                end_seconds=28.8,
                input_options=["-protocol_whitelist", "file,crypto,data,http,https,tcp,tls"],
            )

        self.assertIn("-protocol_whitelist", captured_args)
        option_index = captured_args.index("-protocol_whitelist")
        self.assertEqual(captured_args[option_index + 1], "file,crypto,data,http,https,tcp,tls")
        self.assertEqual(captured_args[captured_args.index("-i") + 1], str(source_path))
        self.assertLess(option_index, captured_args.index("-i"))


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

    def test_extract_clip_uses_ytdlp_section_download_for_linked_videos(self):
        linked_video = MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.YOUTUBE,
            title="Linked Source",
            youtube_video_id="linkedclip001",
            youtube_url="https://www.youtube.com/watch?v=linkedclip001",
            download_status=ProcessingState.READY,
        )
        clip = Clip.objects.create(
            owner=self.user,
            source_type=ClipSourceType.EXTRACTED,
            master_video=linked_video,
            title="Linked Clip",
            start_time_seconds=5.2,
            end_time_seconds=25.7,
            duration_seconds=20.5,
            file_status=ProcessingState.QUEUED,
        )
        job = BackgroundJob.objects.create(
            user=self.user,
            job_type=BackgroundJobType.CLIP_EXTRACTION,
            related_object_type="clip",
            related_object_id=str(clip.id),
            status=BackgroundJobState.QUEUED,
        )

        clip_output_path = Path(self.video.video_file.storage.location) / "clips" / f"user_{self.user.id}" / str(clip.id) / "clip.mp4"
        thumbnail_output_path = Path(self.video.video_file.storage.location) / "thumbnails" / f"clip-{clip.id}.jpg"
        manifest_path = (
            Path(self.video.video_file.storage.location)
            / "clips"
            / "hls"
            / f"user_{self.user.id}"
            / str(clip.id)
            / "index.m3u8"
        )

        def fake_download_clip_section(*args, **kwargs):
            clip_output_path.parent.mkdir(parents=True, exist_ok=True)
            clip_output_path.write_bytes(b"clip-bytes")
            return clip_output_path

        def fake_generate_thumbnail(*args, **kwargs):
            thumbnail_output_path.parent.mkdir(parents=True, exist_ok=True)
            thumbnail_output_path.write_bytes(TEST_IMAGE_BYTES)
            return thumbnail_output_path

        def fake_generate_hls(*args, **kwargs):
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text("#EXTM3U\n", encoding="utf-8")
            return SimpleNamespace(manifest_path=manifest_path)

        from clips.tasks import extract_clip

        with (
            patch("clips.tasks.prepare_drama_extract_source") as prepare_mock,
            patch("clips.tasks.YtDlpService.download_clip_section", side_effect=fake_download_clip_section) as download_mock,
            patch("clips.tasks.FfmpegService.generate_thumbnail", side_effect=fake_generate_thumbnail),
            patch("clips.tasks.FfmpegService.generate_hls", side_effect=fake_generate_hls),
        ):
            extract_clip.run(clip.id)

        clip.refresh_from_db()
        job.refresh_from_db()

        self.assertEqual(clip.file_status, ProcessingState.READY)
        self.assertEqual(job.status, BackgroundJobState.SUCCESS)
        prepare_mock.assert_not_called()
        self.assertEqual(download_mock.call_args.args[0], linked_video.youtube_url)
        self.assertEqual(download_mock.call_args.kwargs["start_seconds"], 5.2)
        self.assertEqual(download_mock.call_args.kwargs["end_seconds"], 25.7)
        self.assertTrue(clip.clip_file.name.endswith("clip.mp4"))
        self.assertTrue(clip.thumbnail_file.name.endswith(".jpg"))
        self.assertTrue(clip.hls_manifest_file.name.endswith("index.m3u8"))

    def test_extract_clip_uses_prepared_manifest_for_remote_drama_stream(self):
        drama_video = DramaVideo.objects.create(
            title="Drama Source",
            source_url="https://send2video.com/watch/drama-source",
            owner=self.user,
            status="ready",
            player_url="https://xzxcdn.com/e/drama-player",
            m3u8_url="https://player.example/drama/master-old.m3u8",
        )
        remote_video = MasterVideo.objects.create(
            owner=self.user,
            source_type=MasterVideoSourceType.UPLOAD,
            title="Drama Bridge",
            remote_playback_url="https://player.example/drama/master-old.m3u8",
            download_status=ProcessingState.READY,
            source_drama_video=drama_video,
        )
        clip = Clip.objects.create(
            owner=self.user,
            source_type=ClipSourceType.EXTRACTED,
            master_video=remote_video,
            title="Drama Clip",
            start_time_seconds=12.3,
            end_time_seconds=28.8,
            duration_seconds=16.5,
            file_status=ProcessingState.QUEUED,
        )
        job = BackgroundJob.objects.create(
            user=self.user,
            job_type=BackgroundJobType.CLIP_EXTRACTION,
            related_object_type="clip",
            related_object_id=str(clip.id),
            status=BackgroundJobState.QUEUED,
        )

        clip_output_path = Path(self.video.video_file.storage.location) / "clips" / f"user_{self.user.id}" / str(clip.id) / "drama-clip.mp4"
        thumbnail_output_path = Path(self.video.video_file.storage.location) / "thumbnails" / f"clip-{clip.id}-drama.jpg"
        manifest_path = (
            Path(self.video.video_file.storage.location)
            / "clips"
            / "hls"
            / f"user_{self.user.id}"
            / str(clip.id)
            / "index.m3u8"
        )
        prepared_manifest_path = (
            Path(self.video.video_file.storage.location)
            / "clips"
            / f"user_{self.user.id}"
            / str(clip.id)
            / "_drama_source"
            / "drama-source.m3u8"
        )

        def fake_extract_clip(*args, **kwargs):
            clip_output_path.parent.mkdir(parents=True, exist_ok=True)
            thumbnail_output_path.parent.mkdir(parents=True, exist_ok=True)
            clip_output_path.write_bytes(b"drama-clip")
            thumbnail_output_path.write_bytes(TEST_IMAGE_BYTES)
            return SimpleNamespace(
                clip_output_path=clip_output_path,
                thumbnail_output_path=thumbnail_output_path,
            )

        def fake_generate_hls(*args, **kwargs):
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text("#EXTM3U\n", encoding="utf-8")
            return SimpleNamespace(manifest_path=manifest_path)

        from clips.tasks import extract_clip

        with (
            patch(
                "clips.tasks.prepare_drama_extract_source",
                return_value=SimpleNamespace(
                    source_path=prepared_manifest_path,
                    resolved_master_url="https://player.example/drama/master-fresh.m3u8",
                    selected_variant_url="https://player.example/drama/index-fresh.m3u8",
                ),
            ) as prepare_mock,
            patch("clips.tasks.FfmpegService.extract_clip", side_effect=fake_extract_clip) as extract_mock,
            patch("clips.tasks.FfmpegService.generate_hls", side_effect=fake_generate_hls),
        ):
            extract_clip.run(clip.id)

        clip.refresh_from_db()
        job.refresh_from_db()
        remote_video.refresh_from_db()

        self.assertEqual(clip.file_status, ProcessingState.READY)
        self.assertEqual(job.status, BackgroundJobState.SUCCESS)
        prepare_mock.assert_called_once()
        self.assertEqual(extract_mock.call_args.kwargs["source_path"], prepared_manifest_path)
        self.assertEqual(
            extract_mock.call_args.kwargs["input_options"],
            ["-protocol_whitelist", "file,crypto,data,http,https,tcp,tls"],
        )
        self.assertEqual(extract_mock.call_args.kwargs["start_seconds"], 12.3)
        self.assertEqual(extract_mock.call_args.kwargs["end_seconds"], 28.8)
        self.assertEqual(remote_video.remote_playback_url, "https://player.example/drama/master-fresh.m3u8")
        self.assertTrue(clip.clip_file.name.endswith("drama-clip.mp4"))
        self.assertTrue(clip.thumbnail_file.name.endswith(".jpg"))
        self.assertTrue(clip.hls_manifest_file.name.endswith("index.m3u8"))
