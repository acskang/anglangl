from django.conf import settings
from django.db import models

from core.models import BaseModel


class ClipLike(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="clip_likes")
    clip = models.ForeignKey("clips.Clip", on_delete=models.CASCADE, related_name="likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "clip"], name="uniq_clip_like_user_clip"),
        ]

    def __str__(self) -> str:
        return f"{self.user} likes {self.clip}"


class ClipComment(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="clip_comments")
    clip = models.ForeignKey("clips.Clip", on_delete=models.CASCADE, related_name="comments")
    content = models.TextField()
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Comment by {self.user} on {self.clip}"
