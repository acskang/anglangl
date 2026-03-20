from django.conf import settings
from django.db import models

from core.models import BaseModel


class ClipStudyHistory(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="clip_study_history")
    clip = models.ForeignKey("clips.Clip", on_delete=models.CASCADE, related_name="study_histories")
    last_studied_at = models.DateTimeField(null=True, blank=True)
    study_count = models.PositiveIntegerField(default=0)
    total_repeat_count = models.PositiveIntegerField(default=0)
    total_watch_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "clip"], name="uniq_studyhistory_user_clip"),
        ]

    def __str__(self) -> str:
        return f"{self.user} - {self.clip}"
