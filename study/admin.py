from django.contrib import admin

from .models import ClipStudyHistory, StudyMaterial, StudyMaterialGeneration


@admin.register(StudyMaterial)
class StudyMaterialAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "owner", "material_type", "purpose", "visibility", "updated_at")
    list_filter = ("material_type", "purpose", "difficulty", "visibility", "source_type")
    search_fields = ("title", "source_title", "owner__username", "imdb_code")
    autocomplete_fields = ("owner", "source_master_video", "source_clip", "source_drama_video", "copied_from")


@admin.register(StudyMaterialGeneration)
class StudyMaterialGenerationAdmin(admin.ModelAdmin):
    list_display = ("id", "material", "template_key", "created_by", "created_at")
    list_filter = ("template_key", "created_at")
    search_fields = ("material__title", "created_by__username", "prompt_intent")
    autocomplete_fields = ("material", "created_by")


@admin.register(ClipStudyHistory)
class ClipStudyHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "clip", "study_count", "last_studied_at", "updated_at")
    search_fields = ("user__username", "clip__title")
    list_filter = ("last_studied_at", "updated_at")
    autocomplete_fields = ("user", "clip")
