import shutil
import sqlite3
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.models import ProcessingState
from videos.models import MasterVideo

from .models import AlbumImage, AlbumImageSourceType, Clip, ClipImage

TEST_IMAGE_BYTES = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
    b"\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00"
    b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01"
    b"\x00\x3b"
)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ClipmasterImportCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="import-owner", password="pw123456")
        self.source_root = Path(tempfile.mkdtemp(prefix="clipmaster-source-"))
        self.source_media_root = self.source_root / "media"
        self.source_media_root.mkdir(parents=True, exist_ok=True)
        self.source_db = self.source_root / "db.sqlite3"

    def tearDown(self):
        shutil.rmtree(self.source_root, ignore_errors=True)
        super().tearDown()

    def test_import_command_copies_clipmaster_data_into_owner_models(self):
        self._create_source_schema()
        self._create_source_fixture_data()

        first_stdout = StringIO()
        call_command(
            "import_clipmaster_data",
            owner=self.user.username,
            source_db=str(self.source_db),
            source_media_root=str(self.source_media_root),
            stdout=first_stdout,
        )
        second_stdout = StringIO()
        call_command(
            "import_clipmaster_data",
            owner=self.user.username,
            source_db=str(self.source_db),
            source_media_root=str(self.source_media_root),
            stdout=second_stdout,
        )

        self.assertIn("videos=1/0", first_stdout.getvalue())
        self.assertIn("videos=0/1", second_stdout.getvalue())
        self.assertEqual(MasterVideo.objects.count(), 1)
        self.assertEqual(Clip.objects.count(), 1)
        self.assertEqual(ClipImage.objects.count(), 1)
        self.assertEqual(AlbumImage.objects.count(), 2)

        video = MasterVideo.objects.get()
        self.assertEqual(video.owner, self.user)
        self.assertEqual(video.youtube_video_id, "clipmaster001")
        self.assertEqual(video.download_status, ProcessingState.READY)
        self.assertTrue(video.video_file.name.endswith(".mp4"))
        self.assertTrue(Path(video.video_file.path).exists())

        clip = Clip.objects.get()
        self.assertEqual(clip.owner, self.user)
        self.assertEqual(clip.master_video, video)
        self.assertEqual(clip.file_status, ProcessingState.READY)
        self.assertEqual(clip.subtitle, "Hello from clipmaster")
        self.assertTrue(Path(clip.clip_file.path).exists())
        self.assertTrue(Path(clip.thumbnail_file.path).exists())

        clip_image = ClipImage.objects.get()
        self.assertEqual(clip_image.owner, self.user)
        self.assertEqual(clip_image.clip, clip)
        self.assertTrue(Path(clip_image.image.path).exists())

        capture_album = AlbumImage.objects.get(source=AlbumImageSourceType.CAPTURE)
        self.assertEqual(capture_album.clip, clip)
        self.assertEqual(capture_album.clip_image, clip_image)
        self.assertTrue(Path(capture_album.image.path).exists())

        thumbnail_album = AlbumImage.objects.get(source=AlbumImageSourceType.THUMBNAIL)
        self.assertEqual(thumbnail_album.master_video, video)
        self.assertTrue(Path(thumbnail_album.image.path).exists())

    def test_import_command_handles_empty_source_database(self):
        self.source_db.touch()

        stdout = StringIO()
        call_command(
            "import_clipmaster_data",
            owner=self.user.username,
            source_db=str(self.source_db),
            source_media_root=str(self.source_media_root),
            stdout=stdout,
        )

        self.assertIn("No clipmaster source tables/data were found.", stdout.getvalue())
        self.assertEqual(MasterVideo.objects.count(), 0)
        self.assertEqual(Clip.objects.count(), 0)
        self.assertEqual(ClipImage.objects.count(), 0)
        self.assertEqual(AlbumImage.objects.count(), 0)

    def _create_source_schema(self):
        with sqlite3.connect(self.source_db) as connection:
            connection.executescript(
                """
                CREATE TABLE clips_video (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'general',
                    thumbnail_url TEXT NOT NULL DEFAULT '',
                    saved_thumbnail TEXT NULL,
                    custom_thumbnail TEXT NULL,
                    duration INTEGER NOT NULL DEFAULT 0,
                    channel TEXT NOT NULL DEFAULT '',
                    full_file_path TEXT NOT NULL DEFAULT '',
                    full_status TEXT NOT NULL DEFAULT 'none',
                    full_error_msg TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE clips_clip (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    start_time INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    thumbnail TEXT NULL,
                    custom_thumbnail TEXT NULL,
                    file_path TEXT NOT NULL DEFAULT '',
                    transcript TEXT NOT NULL DEFAULT '',
                    transcript_status TEXT NOT NULL DEFAULT 'none',
                    seq_no INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_msg TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE clips_clipimage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clip_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    image TEXT NOT NULL,
                    seq_no INTEGER NOT NULL DEFAULT 1,
                    capture_time REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE clips_albumimage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    image TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'upload',
                    video_id INTEGER NULL,
                    clip_id INTEGER NULL,
                    clip_image_id INTEGER NULL,
                    tags TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def _create_source_fixture_data(self):
        full_videos_dir = self.source_media_root / "full_videos"
        clip_dir = self.source_media_root / "clips"
        video_thumbs_dir = self.source_media_root / "video_thumbs"
        clip_thumbs_dir = self.source_media_root / "clip_thumbs"
        clip_images_dir = self.source_media_root / "clip_images"
        album_dir = self.source_media_root / "album"
        for directory in [
            full_videos_dir,
            clip_dir,
            video_thumbs_dir,
            clip_thumbs_dir,
            clip_images_dir,
            album_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)

        full_video_path = full_videos_dir / "full_0001.mp4"
        clip_path = clip_dir / "clip_0001.mp4"
        video_thumb_path = video_thumbs_dir / "video_thumb.gif"
        clip_thumb_path = clip_thumbs_dir / "clip_thumb.gif"
        clip_image_path = clip_images_dir / "capture_01.gif"

        full_video_path.write_bytes(b"video-bytes")
        clip_path.write_bytes(b"clip-bytes")
        video_thumb_path.write_bytes(TEST_IMAGE_BYTES)
        clip_thumb_path.write_bytes(TEST_IMAGE_BYTES)
        clip_image_path.write_bytes(TEST_IMAGE_BYTES)

        created_at = "2026-04-20 09:00:00"
        updated_at = "2026-04-20 09:30:00"

        with sqlite3.connect(self.source_db) as connection:
            connection.execute(
                """
                INSERT INTO clips_video (
                    id, url, video_id, title, description, category, thumbnail_url, custom_thumbnail,
                    duration, channel, full_file_path, full_status, full_error_msg, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "https://www.youtube.com/watch?v=clipmaster001",
                    "clipmaster001",
                    "Clipmaster Source Video",
                    "Video imported from clipmaster",
                    "general",
                    "https://img.youtube.com/vi/clipmaster001/maxresdefault.jpg",
                    "video_thumbs/video_thumb.gif",
                    321,
                    "clipmaster channel",
                    str(full_video_path),
                    "done",
                    "",
                    created_at,
                    updated_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO clips_clip (
                    id, video_id, title, description, start_time, end_time, custom_thumbnail, file_path,
                    transcript, transcript_status, seq_no, status, error_msg, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    1,
                    "Clipmaster Clip 01",
                    "First imported clip",
                    10,
                    24,
                    "clip_thumbs/clip_thumb.gif",
                    str(clip_path),
                    "Hello from clipmaster",
                    "done",
                    1,
                    "done",
                    "",
                    created_at,
                    updated_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO clips_clipimage (
                    id, clip_id, title, description, image, seq_no, capture_time, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    1,
                    "Clip Capture 01",
                    "Imported capture",
                    "clip_images/capture_01.gif",
                    1,
                    12.5,
                    created_at,
                    updated_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO clips_albumimage (
                    id, title, description, image, source, video_id, clip_id, clip_image_id, tags, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "Imported Album Capture",
                    "Album image imported from clipmaster",
                    "clip_images/capture_01.gif",
                    "capture",
                    1,
                    1,
                    1,
                    "imported,capture",
                    created_at,
                    updated_at,
                ),
            )
