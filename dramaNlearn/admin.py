from django.contrib import admin

from .models import ThumbnailAsset, Video


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "owner", "view_count", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("title", "source_url", "thumbnail")


@admin.register(ThumbnailAsset)
class ThumbnailAssetAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at", "updated_at")
    search_fields = ("name",)
