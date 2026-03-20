from django.db import models

class YouTubeVideo(models.Model):
    url = models.URLField(unique=True)
    title = models.CharField(max_length=200)
    thumbnail_url = models.URLField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class ChapterDownload(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "pending"),
        (STATUS_SUCCESS, "success"),
        (STATUS_FAILED, "failed"),
    ]

    video_url = models.URLField()
    video_title = models.CharField(max_length=255, blank=True)
    chapter_index = models.PositiveIntegerField()
    chapter_title = models.CharField(max_length=255)
    start_time = models.FloatField()
    end_time = models.FloatField()
    output_path = models.CharField(max_length=500, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.video_title or 'YouTube Video'} - {self.chapter_title} ({self.start_time}-{self.end_time})"
