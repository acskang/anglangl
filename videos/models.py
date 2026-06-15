from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models

from core.models import BaseModel, ProcessingState


class MasterVideoSourceType(models.TextChoices):
    YOUTUBE = "youtube", "YouTube"
    UPLOAD = "upload", "Upload"


class MasterVideoCategory(models.TextChoices):
    GENERAL = "general", "General"
    TECH = "tech", "Tech"
    COOK = "cook", "Cook"
    MOVIE = "movie", "Movie"
    ECONOMIC = "economic", "Economic"
    MUSIC = "music", "Music"
    SPORTS = "sports", "Sports"
    EDUCATION = "education", "Education"
    TRAVEL = "travel", "Travel"
    NEWS = "news", "News"
    GAMING = "gaming", "Gaming"
    HEALTH = "health", "Health"
    OTHER = "other", "Other"


def _video_thumbnail_path(instance: "MasterVideo", filename: str) -> str:
    safe_name = Path(filename).name or "thumbnail.jpg"
    return f"thumbnails/videos/user_{instance.owner_id}/{instance.id or 'new'}-{uuid4().hex}-{safe_name}"


class MasterVideo(BaseModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="master_videos")
    source_type = models.CharField(
        max_length=20,
        choices=MasterVideoSourceType.choices,
        default=MasterVideoSourceType.YOUTUBE,
    )
    youtube_video_id = models.CharField(max_length=32, blank=True, default="")
    youtube_url = models.URLField(max_length=500, blank=True, default="")
    remote_playback_url = models.URLField(max_length=1000, blank=True, default="")
    source_drama_video = models.OneToOneField(
        "dramaNlearn.Video",
        on_delete=models.CASCADE,
        related_name="master_video_bridge",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=30, choices=MasterVideoCategory.choices, default=MasterVideoCategory.GENERAL)
    thumbnail_url = models.URLField(max_length=500, blank=True)
    saved_thumbnail_file = models.ImageField(upload_to=_video_thumbnail_path, blank=True)
    custom_thumbnail_file = models.ImageField(upload_to=_video_thumbnail_path, blank=True)
    custom_thumbnail_description = models.TextField(blank=True, default="")
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    channel_name = models.CharField(max_length=200, blank=True)
    video_file = models.FileField(upload_to="videos/files/", blank=True)
    subtitle_file = models.FileField(upload_to="videos/subtitles/", blank=True)
    hls_manifest_file = models.FileField(upload_to="videos/hls/", blank=True)
    file_size_bytes = models.BigIntegerField(null=True, blank=True)
    download_status = models.CharField(
        max_length=20,
        choices=ProcessingState.choices,
        default=ProcessingState.PENDING,
    )
    download_error_message = models.TextField(blank=True)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "youtube_video_id"],
                condition=~models.Q(youtube_video_id=""),
                name="uniq_mastervideo_owner_videoid",
            ),
        ]
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="mv_owner_created_idx"),
            models.Index(fields=["download_status", "is_active"], name="mv_status_active_idx"),
            models.Index(fields=["youtube_video_id"], name="mv_youtube_id_idx"),
        ]

    def __str__(self) -> str:
        identifier = self.youtube_video_id or self.video_file.name or f"video-{self.id}"
        return f"{self.title} ({identifier})"

    @property
    def source_url(self) -> str:
        return self.youtube_url or self.remote_playback_url or ""

    @property
    def source_reference(self) -> str:
        if self.youtube_video_id:
            return self.youtube_video_id
        if self.source_drama_video_id:
            return f"drama-{self.source_drama_video_id}"
        if self.video_file:
            return Path(self.video_file.name).name
        return f"video-{self.id}"

    @property
    def primary_thumbnail_url(self) -> str:
        return self.thumbnail

    @property
    def thumbnail(self) -> str:
        if self.custom_thumbnail_file:
            return self.custom_thumbnail_file.url
        if self.saved_thumbnail_file:
            return self.saved_thumbnail_file.url
        return self.thumbnail_url or ""

    @property
    def video_id(self) -> str:
        return self.youtube_video_id

    @property
    def url(self) -> str:
        return self.source_url

    @property
    def duration(self) -> int:
        return int(self.duration_seconds or 0)

    @property
    def channel(self) -> str:
        return self.channel_name or ""

    @property
    def full_file_exists(self) -> bool:
        try:
            return bool(self.video_file and self.video_file.name and Path(self.video_file.path).exists())
        except (NotImplementedError, ValueError):
            return False
