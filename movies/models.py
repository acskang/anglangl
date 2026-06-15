from django.db import models


class SearchQuery(models.Model):
    query = models.CharField(max_length=200, unique=True, db_index=True)
    search_count = models.IntegerField(default=1)
    last_searched = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_searched"]
        verbose_name = "영화 검색어"
        verbose_name_plural = "영화 검색어 목록"

    def __str__(self):
        return f"{self.query} ({self.search_count})"


class Movie(models.Model):
    SOURCE_CHOICES = [
        ("official", "YTS-Official"),
        ("api", "YTS-API"),
        ("tmdb", "TMDB"),
    ]

    title = models.CharField(max_length=500)
    year = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    url = models.URLField(max_length=1000)
    thumbnail = models.URLField(max_length=1000, null=True, blank=True)
    large_cover = models.URLField(max_length=1000, null=True, blank=True)
    imdb_code = models.CharField(max_length=20, null=True, blank=True, db_index=True)
    imdb_rating = models.FloatField(null=True, blank=True)
    tmdb_id = models.CharField(max_length=20, null=True, blank=True, db_index=True)
    rating = models.FloatField(null=True, blank=True)
    genres = models.JSONField(default=list, blank=True)
    summary = models.TextField(null=True, blank=True)
    torrents = models.JSONField(default=list, blank=True)
    search_query = models.ForeignKey(SearchQuery, on_delete=models.CASCADE, related_name="movies")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year", "title"]
        indexes = [
            models.Index(fields=["title", "year"]),
            models.Index(fields=["imdb_code"]),
            models.Index(fields=["tmdb_id"]),
        ]
        unique_together = [["title", "year", "source", "search_query"]]

    def __str__(self):
        return f"{self.title} ({self.year}) - {self.source}"

    @property
    def imdb_url(self):
        if self.imdb_code:
            return f"https://www.imdb.com/title/{self.imdb_code}"
        return None

    @property
    def tmdb_url(self):
        if self.tmdb_id:
            return f"https://www.themoviedb.org/movie/{self.tmdb_id}"
        return None

    @property
    def player_url(self):
        if self.tmdb_id:
            return f"https://www.vidsrc.win/watch/{self.tmdb_id}"
        return None
