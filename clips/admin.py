from django.contrib import admin

from .models import Clip, ClipUploadBatch


@admin.register(ClipUploadBatch)
class ClipUploadBatchAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "owner",
        "status",
        "total_files",
        "success_files",
        "failed_files",
        "created_at",
    )
    search_fields = ("title", "owner__username", "source_directory_label")
    list_filter = ("status", "created_at")
    autocomplete_fields = ("owner",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Clip)
class ClipAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "source_type",
        "owner",
        "master_video",
        "upload_batch",
        "start_time_seconds",
        "end_time_seconds",
        "duration_seconds",
        "hls_manifest_file",
        "is_public",
        "file_status",
        "extracted_at",
        "created_at",
    )
    search_fields = ("title", "original_filename", "owner__username", "master_video__title")
    list_filter = ("source_type", "is_public", "is_active", "file_status", "created_at", "extracted_at")
    autocomplete_fields = ("owner", "master_video", "upload_batch")
    readonly_fields = ("duration_seconds", "hls_manifest_file", "extracted_at", "created_at", "updated_at")
