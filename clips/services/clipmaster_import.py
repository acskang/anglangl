from __future__ import annotations

import mimetypes
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files import File
from django.db import transaction
from django.utils import timezone

from core.models import ProcessingState
from videos.models import MasterVideo, MasterVideoSourceType

from ..models import AlbumImage, AlbumImageSourceType, Clip, ClipImage, ClipSourceType

REQUIRED_TABLES = {
    "clips_video",
    "clips_clip",
    "clips_clipimage",
    "clips_albumimage",
}

SOURCE_VIDEO_STATUS_MAP = {
    "none": ProcessingState.PENDING,
    "downloading": ProcessingState.PROCESSING,
    "done": ProcessingState.READY,
    "error": ProcessingState.FAILED,
}

SOURCE_CLIP_STATUS_MAP = {
    "pending": ProcessingState.PENDING,
    "processing": ProcessingState.PROCESSING,
    "done": ProcessingState.READY,
    "error": ProcessingState.FAILED,
}

SOURCE_ALBUM_MAP = {
    "capture": AlbumImageSourceType.CAPTURE,
    "thumbnail": AlbumImageSourceType.THUMBNAIL,
    "upload": AlbumImageSourceType.UPLOAD,
}


@dataclass
class ClipmasterImportSummary:
    source_db: Path
    source_media_root: Path
    dry_run: bool = False
    empty_source: bool = False
    source_counts: Counter = field(default_factory=Counter)
    created_counts: Counter = field(default_factory=Counter)
    updated_counts: Counter = field(default_factory=Counter)
    skipped_counts: Counter = field(default_factory=Counter)
    missing_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ClipmasterImportService:
    def __init__(
        self,
        *,
        owner,
        source_db: str | Path,
        source_media_root: str | Path,
        dry_run: bool = False,
    ) -> None:
        self.owner = owner
        self.source_db = Path(source_db).expanduser().resolve()
        self.source_media_root = Path(source_media_root).expanduser().resolve()
        self.dry_run = dry_run
        self.summary = ClipmasterImportSummary(
            source_db=self.source_db,
            source_media_root=self.source_media_root,
            dry_run=dry_run,
        )
        self._video_map: dict[int, MasterVideo] = {}
        self._clip_map: dict[int, Clip] = {}
        self._clip_image_map: dict[int, ClipImage] = {}

    def run(self) -> ClipmasterImportSummary:
        if not self.source_db.exists() or self.source_db.stat().st_size == 0:
            self.summary.empty_source = True
            self.summary.warnings.append("Source database is missing or empty.")
            return self.summary

        if not self.source_media_root.exists():
            self.summary.warnings.append("Source media root does not exist; metadata-only import will run.")

        with sqlite3.connect(self.source_db) as connection:
            connection.row_factory = sqlite3.Row
            tables = self._table_names(connection)
            if not REQUIRED_TABLES.issubset(tables):
                self.summary.empty_source = True
                self.summary.warnings.append("Source database does not contain the clipmaster tables.")
                return self.summary

            source_rows = {
                "videos": self._fetch_rows(connection, "clips_video"),
                "clips": self._fetch_rows(connection, "clips_clip"),
                "clip_images": self._fetch_rows(connection, "clips_clipimage"),
                "album_images": self._fetch_rows(connection, "clips_albumimage"),
            }
            for label, rows in source_rows.items():
                self.summary.source_counts[label] = len(rows)

            if self.dry_run:
                return self.summary

            with transaction.atomic():
                for row in source_rows["videos"]:
                    self._video_map[row["id"]] = self._import_video(row)

                for row in source_rows["videos"]:
                    self._import_video_thumbnail(row, self._video_map[row["id"]])

                for row in source_rows["clips"]:
                    self._clip_map[row["id"]] = self._import_clip(row)

                for row in source_rows["clip_images"]:
                    self._clip_image_map[row["id"]] = self._import_clip_image(row)

                for row in source_rows["album_images"]:
                    self._import_album_image(row)

        return self.summary

    def _table_names(self, connection: sqlite3.Connection) -> set[str]:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        return {row[0] for row in rows}

    def _fetch_rows(self, connection: sqlite3.Connection, table_name: str) -> list[sqlite3.Row]:
        return connection.execute(f"SELECT * FROM {table_name} ORDER BY id ASC").fetchall()

    def _import_video(self, row: sqlite3.Row) -> MasterVideo:
        lookup = {"owner": self.owner, "youtube_video_id": (row["video_id"] or "").strip()}
        defaults = {
            "source_type": MasterVideoSourceType.YOUTUBE,
            "youtube_url": (row["url"] or "").strip(),
            "title": self._truncate(row["title"], 255, fallback=(row["video_id"] or "Imported Video")),
            "description": row["description"] or "",
            "thumbnail_url": row["thumbnail_url"] or "",
            "duration_seconds": row["duration"] or None,
            "download_status": ProcessingState.PENDING,
            "download_error_message": "",
        }
        video, created = MasterVideo.objects.get_or_create(defaults=defaults, **lookup)
        if created:
            self.summary.created_counts["videos"] += 1
        else:
            self.summary.updated_counts["videos"] += 1
            for field_name, value in defaults.items():
                setattr(video, field_name, value)

        file_available = bool(video.video_file)
        if not video.video_file:
            file_available = self._copy_to_field(video, "video_file", row["full_file_path"])
            if file_available and video.video_file:
                source_path = self._resolve_source_path(row["full_file_path"])
                if source_path is not None and source_path.exists():
                    video.file_size_bytes = source_path.stat().st_size

        status, error_message = self._map_video_status(
            row["full_status"],
            row["full_error_msg"],
            row["full_file_path"],
            file_available,
        )
        video.download_status = status
        video.download_error_message = error_message
        video.downloaded_at = self._parse_datetime(row["updated_at"]) if status == ProcessingState.READY else None
        video.save()
        self._restore_timestamps(video, row, extra_updates={"downloaded_at": video.downloaded_at})
        return video

    def _import_video_thumbnail(self, row: sqlite3.Row, video: MasterVideo) -> None:
        raw_thumbnail = row["custom_thumbnail"] or row["saved_thumbnail"]
        if not raw_thumbnail:
            self.summary.skipped_counts["video_thumbnails"] += 1
            return

        title_suffix = "Thumbnail (Custom)" if row["custom_thumbnail"] else "Thumbnail"
        album_image = (
            AlbumImage.objects.filter(
                owner=self.owner,
                master_video=video,
                source=AlbumImageSourceType.THUMBNAIL,
                title=f"{self._truncate(video.title, 260, fallback=video.title or 'Imported Video')} {title_suffix}",
            )
            .order_by("id")
            .first()
        )
        created = album_image is None
        if album_image is None:
            album_image = AlbumImage(
                owner=self.owner,
                master_video=video,
                source=AlbumImageSourceType.THUMBNAIL,
            )

        album_image.title = self._truncate(
            f"{video.title} {title_suffix}",
            300,
            fallback=video.title or "Imported Video",
        )
        album_image.description = "Imported from clipmaster video thumbnail."
        if not album_image.image:
            copied = self._copy_to_field(album_image, "image", raw_thumbnail)
            if not copied:
                self.summary.skipped_counts["video_thumbnails"] += 1
                return
        album_image.save()
        self._restore_timestamps(album_image, row)

        counter = self.summary.created_counts if created else self.summary.updated_counts
        counter["video_thumbnails"] += 1

    def _import_clip(self, row: sqlite3.Row) -> Clip:
        master_video = self._video_map[row["video_id"]]
        title = self._truncate(row["title"], 255, fallback=f"{master_video.title} clip {row['id']}")
        clip = (
            Clip.objects.filter(
                owner=self.owner,
                master_video=master_video,
                source_type=ClipSourceType.EXTRACTED,
                start_time_seconds=max(0, row["start_time"] or 0),
                end_time_seconds=max(0, row["end_time"] or 0),
                title=title,
            )
            .order_by("id")
            .first()
        )
        created = clip is None
        if clip is None:
            clip = Clip(
                owner=self.owner,
                master_video=master_video,
                source_type=ClipSourceType.EXTRACTED,
            )

        clip.title = title
        clip.description = row["description"] or ""
        clip.subtitle = row["transcript"] or ""
        clip.subtitle_timing = "[]"
        clip.start_time_seconds = max(0, row["start_time"] or 0)
        clip.end_time_seconds = max(0, row["end_time"] or 0)
        clip.original_filename = Path(row["file_path"]).name if row["file_path"] else ""
        clip.file_size_bytes = None
        clip.mime_type = mimetypes.guess_type(clip.original_filename or "")[0] or ""
        clip.file_error_message = row["error_msg"] or ""
        clip.file_status = ProcessingState.PENDING
        clip.extracted_at = None
        clip.save()

        file_available = bool(clip.clip_file)
        if not clip.clip_file:
            file_available = self._copy_to_field(clip, "clip_file", row["file_path"])
            if file_available and clip.clip_file:
                source_path = self._resolve_source_path(row["file_path"])
                if source_path is not None and source_path.exists():
                    clip.file_size_bytes = source_path.stat().st_size
                    clip.mime_type = mimetypes.guess_type(source_path.name)[0] or clip.mime_type

        raw_thumbnail = row["custom_thumbnail"] or row["thumbnail"]
        if not clip.thumbnail_file and raw_thumbnail:
            self._copy_to_field(clip, "thumbnail_file", raw_thumbnail)

        status, error_message = self._map_clip_status(
            row["status"],
            row["error_msg"],
            row["file_path"],
            file_available,
        )
        clip.file_status = status
        clip.file_error_message = error_message
        clip.extracted_at = self._parse_datetime(row["updated_at"]) if status == ProcessingState.READY else None
        clip.save()
        self._restore_timestamps(clip, row, extra_updates={"extracted_at": clip.extracted_at})

        counter = self.summary.created_counts if created else self.summary.updated_counts
        counter["clips"] += 1
        return clip

    def _import_clip_image(self, row: sqlite3.Row) -> ClipImage:
        clip = self._clip_map[row["clip_id"]]
        title = self._truncate(row["title"], 300, fallback=f"{clip.title} image {row['id']}")
        clip_image = (
            ClipImage.objects.filter(
                owner=self.owner,
                clip=clip,
                seq_no=max(1, row["seq_no"] or 1),
                title=title,
            )
            .order_by("id")
            .first()
        )
        created = clip_image is None
        if clip_image is None:
            clip_image = ClipImage(owner=self.owner, clip=clip)

        clip_image.title = title
        clip_image.description = row["description"] or ""
        clip_image.seq_no = max(1, row["seq_no"] or 1)
        clip_image.capture_time_seconds = row["capture_time"] or 0
        clip_image.save()

        copied = clip_image.image and bool(clip_image.image.name)
        if not copied:
            copied = self._copy_to_field(clip_image, "image", row["image"])
        if not copied:
            self.summary.skipped_counts["clip_images"] += 1

        clip_image.save()
        self._restore_timestamps(clip_image, row)

        counter = self.summary.created_counts if created else self.summary.updated_counts
        counter["clip_images"] += 1
        return clip_image

    def _import_album_image(self, row: sqlite3.Row) -> AlbumImage:
        source = SOURCE_ALBUM_MAP.get((row["source"] or "").strip(), AlbumImageSourceType.UPLOAD)
        master_video = self._video_map.get(row["video_id"])
        clip = self._clip_map.get(row["clip_id"])
        clip_image = self._clip_image_map.get(row["clip_image_id"])
        title = self._truncate(row["title"], 300, fallback=f"Album image {row['id']}")

        lookup = {
            "owner": self.owner,
            "source": source,
            "title": title,
            "master_video": master_video,
            "clip": clip,
            "clip_image": clip_image,
        }
        album_image, created = AlbumImage.objects.get_or_create(
            defaults={
                "description": row["description"] or "",
                "tags": row["tags"] or "",
            },
            **lookup,
        )
        if created:
            self.summary.created_counts["album_images"] += 1
        else:
            self.summary.updated_counts["album_images"] += 1
            album_image.description = row["description"] or ""
            album_image.tags = row["tags"] or ""

        if not album_image.image:
            copied = self._copy_to_field(album_image, "image", row["image"])
            if not copied:
                self.summary.skipped_counts["album_images"] += 1
        album_image.save()
        self._restore_timestamps(album_image, row)
        return album_image

    def _copy_to_field(self, instance, field_name: str, raw_value: str | None) -> bool:
        source_path = self._resolve_source_path(raw_value)
        if source_path is None:
            return False
        if not source_path.exists():
            self.summary.missing_files.append(str(source_path))
            return False

        with source_path.open("rb") as handle:
            getattr(instance, field_name).save(source_path.name, File(handle), save=False)
        return True

    def _resolve_source_path(self, raw_value: str | None) -> Path | None:
        if not raw_value:
            return None
        candidate = Path(str(raw_value))
        if candidate.is_absolute():
            return candidate
        return self.source_media_root / candidate

    def _restore_timestamps(self, instance, row: sqlite3.Row, *, extra_updates: dict | None = None) -> None:
        created_at = self._parse_datetime(row["created_at"])
        updated_at = self._parse_datetime(row["updated_at"])
        updates = {}
        if created_at is not None:
            updates["created_at"] = created_at
        if updated_at is not None:
            updates["updated_at"] = updated_at
        if extra_updates:
            updates.update(extra_updates)
        if updates:
            instance.__class__.objects.filter(pk=instance.pk).update(**updates)

    def _map_video_status(
        self,
        source_status: str | None,
        source_error: str | None,
        source_file_path: str | None,
        file_copied: bool,
    ) -> tuple[str, str]:
        status = SOURCE_VIDEO_STATUS_MAP.get((source_status or "").strip(), ProcessingState.PENDING)
        error_message = source_error or ""
        if status == ProcessingState.READY and not file_copied:
            error_message = error_message or self._missing_file_message("full video", source_file_path)
            return ProcessingState.FAILED, error_message
        return status, error_message

    def _map_clip_status(
        self,
        source_status: str | None,
        source_error: str | None,
        source_file_path: str | None,
        file_copied: bool,
    ) -> tuple[str, str]:
        status = SOURCE_CLIP_STATUS_MAP.get((source_status or "").strip(), ProcessingState.PENDING)
        error_message = source_error or ""
        if status == ProcessingState.READY and not file_copied:
            error_message = error_message or self._missing_file_message("clip file", source_file_path)
            return ProcessingState.FAILED, error_message
        return status, error_message

    def _missing_file_message(self, label: str, source_file_path: str | None) -> str:
        if source_file_path:
            return f"Source {label} was missing during clipmaster import: {source_file_path}"
        return f"Source {label} was not available during clipmaster import."

    def _parse_datetime(self, value) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value))
        if timezone.is_naive(dt):
            return timezone.make_aware(dt, timezone.get_current_timezone())
        return dt

    def _truncate(self, value: str | None, limit: int, *, fallback: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            cleaned = fallback
        return cleaned[:limit]


def import_clipmaster_data(
    *,
    owner_identifier: str,
    source_db: str | Path,
    source_media_root: str | Path,
    dry_run: bool = False,
) -> ClipmasterImportSummary:
    User = get_user_model()
    owner = User.objects.filter(username=owner_identifier).first()
    if owner is None:
        owner = User.objects.filter(email=owner_identifier).first()
    if owner is None and owner_identifier.isdigit():
        owner = User.objects.filter(pk=int(owner_identifier)).first()
    if owner is None:
        raise User.DoesNotExist(f"Could not find owner '{owner_identifier}'.")

    return ClipmasterImportService(
        owner=owner,
        source_db=source_db,
        source_media_root=source_media_root,
        dry_run=dry_run,
    ).run()
