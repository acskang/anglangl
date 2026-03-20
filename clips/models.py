from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import BaseModel, ProcessingState


def _uploaded_clip_path(instance: "Clip", filename: str) -> str:
    safe_name = Path(filename).name
    unique_name = f"{uuid4().hex}_{safe_name}"
    return f"uploaded_clips/user_{instance.owner_id}/batch_{instance.upload_batch_id or 'none'}/{unique_name}"


def _clip_thumbnail_path(instance: "Clip", filename: str) -> str:
    safe_name = Path(filename).name or "thumb.jpg"
    return f"thumbnails/clip-{instance.id or 'new'}-{uuid4().hex}-{safe_name}"


def _clip_hls_manifest_path(instance: "Clip", filename: str) -> str:
    safe_name = Path(filename).name or "index.m3u8"
    return f"clips/hls/user_{instance.owner_id}/clip_{instance.id or 'new'}/{safe_name}"


class ClipSourceType(models.TextChoices):
    EXTRACTED = "extracted", "Extracted"
    UPLOADED = "uploaded", "Uploaded"


class ClipUploadBatchStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    UPLOADING = "uploading", "Uploading"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    PARTIAL_FAILED = "partial_failed", "Partial Failed"
    FAILED = "failed", "Failed"


class ClipUploadBatch(BaseModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="clip_upload_batches")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    source_directory_label = models.CharField(max_length=255, blank=True)
    total_files = models.PositiveIntegerField(default=0)
    success_files = models.PositiveIntegerField(default=0)
    failed_files = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=ClipUploadBatchStatus.choices, default=ClipUploadBatchStatus.PENDING)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="clipbatch_owner_created_idx"),
            models.Index(fields=["status", "-created_at"], name="clipbatch_status_created_idx"),
        ]

    def __str__(self) -> str:
        return f"Batch {self.id}: {self.title}"


class Clip(BaseModel):
    source_type = models.CharField(max_length=20, choices=ClipSourceType.choices, default=ClipSourceType.EXTRACTED)
    master_video = models.ForeignKey(
        "videos.MasterVideo",
        on_delete=models.CASCADE,
        related_name="clips",
        null=True,
        blank=True,
    )
    upload_batch = models.ForeignKey(
        "clips.ClipUploadBatch",
        on_delete=models.SET_NULL,
        related_name="clips",
        null=True,
        blank=True,
    )
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="clips")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    subtitle = models.TextField(blank=True, null=True)
    subtitle_timing = models.TextField(blank=True, default="[]")
    original_filename = models.CharField(max_length=255, blank=True)
    file_size_bytes = models.BigIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    start_time_seconds = models.PositiveIntegerField(default=0)
    end_time_seconds = models.PositiveIntegerField(default=0)
    duration_seconds = models.PositiveIntegerField(default=0)
    clip_file = models.FileField(upload_to=_uploaded_clip_path, blank=True)
    hls_manifest_file = models.FileField(upload_to=_clip_hls_manifest_path, blank=True)
    thumbnail_file = models.ImageField(upload_to=_clip_thumbnail_path, blank=True)
    is_public = models.BooleanField(default=False)

    file_status = models.CharField(max_length=20, choices=ProcessingState.choices, default=ProcessingState.PENDING)
    file_error_message = models.TextField(blank=True)

    # Backward-compatible fields kept in sync with file_status/file_error_message.
    extraction_status = models.CharField(max_length=20, choices=ProcessingState.choices, default=ProcessingState.PENDING)
    extraction_error_message = models.TextField(blank=True)

    extracted_at = models.DateTimeField(null=True, blank=True)
    last_studied_at_cache = models.DateTimeField(null=True, blank=True)
    study_count_cache = models.PositiveIntegerField(default=0)
    like_count_cache = models.PositiveIntegerField(default=0)
    comment_count_cache = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="clip_owner_created_idx"),
            models.Index(fields=["is_public", "is_active"], name="clip_public_active_idx"),
            models.Index(fields=["file_status"], name="clip_file_status_idx"),
            models.Index(fields=["source_type", "-created_at"], name="clip_source_created_idx"),
        ]

    def clean(self):
        super().clean()

        if self.source_type == ClipSourceType.EXTRACTED and self.master_video is None:
            raise ValidationError({"master_video": "Master video is required for extracted clips."})

        if self.source_type == ClipSourceType.UPLOADED and self.master_video is not None:
            raise ValidationError({"master_video": "Uploaded clips cannot reference a master video."})

        if self.start_time_seconds < 0:
            raise ValidationError({"start_time_seconds": "Start time must be greater than or equal to 0."})

        if self.source_type == ClipSourceType.EXTRACTED:
            if self.end_time_seconds <= self.start_time_seconds:
                raise ValidationError({"end_time_seconds": "End time must be greater than start time."})

            expected_duration = self.end_time_seconds - self.start_time_seconds
            if self.duration_seconds != expected_duration:
                self.duration_seconds = expected_duration

            max_duration = self.master_video.duration_seconds if self.master_video else None
            if max_duration is not None and self.end_time_seconds > max_duration:
                raise ValidationError({"end_time_seconds": "End time cannot exceed master video duration."})

        if self.source_type == ClipSourceType.UPLOADED:
            if self.start_time_seconds not in (0,):
                raise ValidationError({"start_time_seconds": "Uploaded clips must start at 0."})
            if self.end_time_seconds < self.start_time_seconds:
                raise ValidationError({"end_time_seconds": "End time must be greater than or equal to start time."})

    def save(self, *args, **kwargs):
        if self.source_type == ClipSourceType.EXTRACTED:
            self.duration_seconds = max(0, self.end_time_seconds - self.start_time_seconds)

        # Keep legacy extraction fields mirrored for compatibility.
        self.extraction_status = self.file_status
        self.extraction_error_message = self.file_error_message

        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title
