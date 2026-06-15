import json

from django.db import models


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ProcessingState(models.TextChoices):
    PENDING = "pending", "Pending"
    QUEUED = "queued", "Queued"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class BackgroundJobState(models.TextChoices):
    PENDING = "pending", "Pending"
    QUEUED = "queued", "Queued"
    PROCESSING = "processing", "Processing"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"
    CANCELED = "canceled", "Canceled"


class DramaSeriesCache(BaseModel):
    tmdb = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["title", "tmdb"]

    def __str__(self):
        return self.title or self.tmdb


class DramaEpisodeCache(BaseModel):
    series = models.ForeignKey(DramaSeriesCache, related_name="episodes", on_delete=models.CASCADE)
    season_number = models.PositiveIntegerField()
    episode_number = models.PositiveIntegerField()
    label = models.CharField(max_length=255, blank=True)
    embed_url = models.URLField(max_length=1000)

    class Meta:
        ordering = ["season_number", "episode_number"]
        unique_together = [("series", "season_number", "episode_number")]

    def __str__(self):
        return f"{self.series} S{self.season_number}E{self.episode_number}"


class ImdbDramaSeriesCache(BaseModel):
    imdb_id = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=255, blank=True)
    poster_url = models.URLField(max_length=1000, blank=True)
    summary = models.TextField(blank=True)
    last_played_at = models.DateTimeField(null=True, blank=True)
    manual_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["title", "imdb_id"]

    def __str__(self):
        return self.title or self.imdb_id


class ImdbDramaEpisodeCache(BaseModel):
    series = models.ForeignKey(ImdbDramaSeriesCache, related_name="episodes", on_delete=models.CASCADE)
    season_number = models.PositiveIntegerField()
    episode_number = models.PositiveIntegerField()
    episode_title = models.CharField(max_length=255, blank=True)
    stream_url = models.URLField(max_length=1000)
    resolved_m3u8_url = models.URLField(max_length=2000, blank=True)
    subtitle_tracks = models.TextField(blank=True, default="[]")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["season_number", "episode_number"]
        unique_together = [("series", "season_number", "episode_number")]

    def __str__(self):
        return f"{self.series} S{self.season_number}E{self.episode_number}"

    def subtitle_tracks_list(self):
        if not self.subtitle_tracks:
            return []
        try:
            data = json.loads(self.subtitle_tracks)
        except (TypeError, ValueError):
            return []
        return data if isinstance(data, list) else []
