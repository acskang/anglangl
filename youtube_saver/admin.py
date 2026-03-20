from django.contrib import admin

from .models import ChapterDownload, YouTubeVideo


@admin.register(YouTubeVideo)
class YouTubeVideoAdmin(admin.ModelAdmin):
    list_display = ("title", "url", "created_at")
    search_fields = ("title", "url")
    ordering = ("-created_at",)


@admin.register(ChapterDownload)
class ChapterDownloadAdmin(admin.ModelAdmin):
    list_display = (
        "video_title",
        "chapter_title",
        "chapter_index",
        "status",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("video_title", "chapter_title", "video_url")
    ordering = ("-created_at",)
