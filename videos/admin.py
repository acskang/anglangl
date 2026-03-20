from django.contrib import admin

from .models import MasterVideo


@admin.register(MasterVideo)
class MasterVideoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "owner",
        "source_type",
        "youtube_video_id",
        "title",
        "download_status",
        "hls_manifest_file",
        "duration_seconds",
        "file_size_bytes",
        "downloaded_at",
        "is_active",
        "created_at",
    )
    search_fields = ("youtube_video_id", "youtube_url", "title", "owner__username", "video_file")
    list_filter = ("download_status", "is_active", "created_at", "downloaded_at")
    autocomplete_fields = ("owner",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "downloaded_at",
        "duration_seconds",
        "file_size_bytes",
        "hls_manifest_file",
    )
