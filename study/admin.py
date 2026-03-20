from django.contrib import admin

from .models import ClipStudyHistory


@admin.register(ClipStudyHistory)
class ClipStudyHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "clip", "study_count", "last_studied_at", "updated_at")
    search_fields = ("user__username", "clip__title")
    list_filter = ("last_studied_at", "updated_at")
    autocomplete_fields = ("user", "clip")
