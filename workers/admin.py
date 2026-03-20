from django.contrib import admin

from .models import BackgroundJob


@admin.register(BackgroundJob)
class BackgroundJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "job_type",
        "user",
        "related_object_type",
        "related_object_id",
        "status",
        "progress_percent",
        "celery_task_id",
        "started_at",
        "finished_at",
        "created_at",
    )
    search_fields = (
        "job_type",
        "celery_task_id",
        "related_object_type",
        "related_object_id",
        "user__username",
        "message",
        "error_message",
    )
    list_filter = ("status", "job_type", "related_object_type", "created_at", "started_at", "finished_at")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
