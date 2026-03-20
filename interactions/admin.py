from django.contrib import admin

from .models import ClipComment, ClipLike


@admin.register(ClipLike)
class ClipLikeAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "clip", "created_at")
    search_fields = ("user__username", "clip__title")
    list_filter = ("created_at",)
    autocomplete_fields = ("user", "clip")


@admin.register(ClipComment)
class ClipCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "clip", "is_deleted", "created_at")
    search_fields = ("user__username", "clip__title", "content")
    list_filter = ("is_deleted", "created_at")
    autocomplete_fields = ("user", "clip")
