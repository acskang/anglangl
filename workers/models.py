from django.conf import settings
from django.db import models

from core.models import BackgroundJobState, BaseModel


class BackgroundJobType(models.TextChoices):
    YOUTUBE_DOWNLOAD = "youtube_download", "Source Video Import"
    MASTER_VIDEO_UPLOAD_PROCESS = "master_video_upload_process", "Master Video Upload Process"
    CLIP_EXTRACTION = "clip_extraction", "Clip Extraction"
    CLIP_BATCH_UPLOAD = "clip_batch_upload", "Clip Batch Upload"
    CLIP_FILE_POSTPROCESS = "clip_file_postprocess", "Clip File Postprocess"
    DRAMA_VIDEO_EXTRACT = "drama_video_extract", "Drama Video Extract"


class BackgroundJob(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="background_jobs",
    )
    job_type = models.CharField(max_length=100, choices=BackgroundJobType.choices)
    related_object_type = models.CharField(max_length=100, blank=True)
    related_object_id = models.CharField(max_length=64, blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20,
        choices=BackgroundJobState.choices,
        default=BackgroundJobState.PENDING,
    )
    progress_percent = models.PositiveSmallIntegerField(default=0)
    message = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="job_status_created_idx"),
            models.Index(fields=["celery_task_id"], name="job_celery_task_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.job_type} ({self.status})"
