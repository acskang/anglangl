from django.conf import settings
from django.db import models

from core.models import BaseModel, ProcessingState


class MasterVideoSourceType(models.TextChoices):
    YOUTUBE = "youtube", "YouTube"
    UPLOAD = "upload", "Upload"


class MasterVideo(BaseModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="master_videos")
    source_type = models.CharField(
        max_length=20,
        choices=MasterVideoSourceType.choices,
        default=MasterVideoSourceType.YOUTUBE,
    )
    youtube_video_id = models.CharField(max_length=32, blank=True, default="")
    youtube_url = models.URLField(max_length=500, blank=True, default="")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    thumbnail_url = models.URLField(max_length=500, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
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
