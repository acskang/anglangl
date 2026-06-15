from django.conf import settings
from django.db import models

from core.models import BaseModel


class StudyMaterialSourceType(models.TextChoices):
    CLIP = "clip", "Clip"
    MASTER_VIDEO = "master_video", "Master Video"
    DRAMA_VIDEO = "drama_video", "Drama Video"
    MOVIE = "movie", "Movie"
    URL = "url", "URL"
    MANUAL = "manual", "Manual"


class StudyMaterialType(models.TextChoices):
    SHADOWING_SCRIPT = "shadowing_script", "쉐도잉 스크립트"
    EXPRESSIONS = "expressions", "핵심 표현 정리"
    LEARNING_NOTE = "learning_note", "단어/문장 학습 노트"


class StudyMaterialPurpose(models.TextChoices):
    LISTENING = "listening", "리스닝"
    SHADOWING = "shadowing", "쉐도잉"
    SPEAKING = "speaking", "회화"
    VOCABULARY = "vocabulary", "어휘"
    EXAM = "exam", "시험 대비"
    GENERAL = "general", "일반 학습"


class StudyMaterialDifficulty(models.TextChoices):
    BEGINNER = "beginner", "입문"
    INTERMEDIATE = "intermediate", "중급"
    ADVANCED = "advanced", "고급"
    MIXED = "mixed", "혼합"


class StudyMaterialVisibility(models.TextChoices):
    PRIVATE = "private", "비공개"
    PUBLIC = "public", "공개"


class StudyMaterial(BaseModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="study_materials")
    title = models.CharField(max_length=255)
    material_type = models.CharField(
        max_length=40,
        choices=StudyMaterialType.choices,
        default=StudyMaterialType.SHADOWING_SCRIPT,
    )
    purpose = models.CharField(
        max_length=30,
        choices=StudyMaterialPurpose.choices,
        default=StudyMaterialPurpose.GENERAL,
    )
    difficulty = models.CharField(
        max_length=20,
        choices=StudyMaterialDifficulty.choices,
        default=StudyMaterialDifficulty.INTERMEDIATE,
    )
    visibility = models.CharField(
        max_length=20,
        choices=StudyMaterialVisibility.choices,
        default=StudyMaterialVisibility.PRIVATE,
    )
    source_type = models.CharField(
        max_length=30,
        choices=StudyMaterialSourceType.choices,
        default=StudyMaterialSourceType.MANUAL,
    )
    source_title = models.CharField(max_length=255, blank=True)
    source_url = models.URLField(max_length=1000, blank=True)
    imdb_code = models.CharField(max_length=32, blank=True)
    source_master_video = models.ForeignKey(
        "videos.MasterVideo",
        on_delete=models.SET_NULL,
        related_name="study_materials",
        null=True,
        blank=True,
    )
    source_clip = models.ForeignKey(
        "clips.Clip",
        on_delete=models.SET_NULL,
        related_name="study_materials",
        null=True,
        blank=True,
    )
    source_drama_video = models.ForeignKey(
        "dramaNlearn.Video",
        on_delete=models.SET_NULL,
        related_name="study_materials",
        null=True,
        blank=True,
    )
    copied_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="copies",
        null=True,
        blank=True,
    )
    generated_content = models.TextField(blank=True)
    editable_notes = models.TextField(blank=True)
    generation_history = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["owner", "-updated_at"], name="studymat_owner_updated_idx"),
            models.Index(fields=["material_type", "visibility"], name="studymat_type_visibility_idx"),
            models.Index(fields=["source_type", "-created_at"], name="studymat_source_created_idx"),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def source_reference_label(self) -> str:
        if self.source_clip_id:
            return f"Clip #{self.source_clip_id}"
        if self.source_master_video_id:
            return f"MasterVideo #{self.source_master_video_id}"
        if self.source_drama_video_id:
            return f"DramaVideo #{self.source_drama_video_id}"
        if self.imdb_code:
            return f"IMDb {self.imdb_code}"
        return self.source_url or "-"

    @property
    def is_imported(self) -> bool:
        return bool(self.copied_from_id)

    @property
    def ownership_label(self) -> str:
        return "가져온 자료" if self.is_imported else "내가 만든 자료"

    @property
    def visibility_description(self) -> str:
        if self.visibility == StudyMaterialVisibility.PUBLIC:
            return "탐색 화면에 노출됨"
        return "내 라이브러리에서만 보임"

    @property
    def quality_badge(self) -> str:
        history = list(self.generation_history or [])
        source_text_kind = str(history[-1].get("source_text_kind") or "") if history else ""
        if source_text_kind in {"clip_subtitle", "master_video_subtitle", "drama_subtitle_body"}:
            return "자막/대사 기반"
        if source_text_kind == "subtitle_tracks":
            return "자막 트랙 기반"
        if history:
            return "저장된 초안"
        return "메타데이터 기반"

    @property
    def quality_tone(self) -> str:
        history = list(self.generation_history or [])
        source_text_kind = str(history[-1].get("source_text_kind") or "") if history else ""
        if source_text_kind in {"clip_subtitle", "master_video_subtitle", "drama_subtitle_body"}:
            return "rich"
        if source_text_kind == "subtitle_tracks":
            return "medium"
        return "light"


class StudyMaterialGeneration(BaseModel):
    material = models.ForeignKey(
        StudyMaterial,
        on_delete=models.CASCADE,
        related_name="generations",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="study_material_generations",
    )
    template_key = models.CharField(max_length=40)
    prompt_intent = models.CharField(max_length=255, blank=True)
    input_snapshot = models.JSONField(default=dict, blank=True)
    output_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["material", "-created_at"], name="smgen_mat_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.material_id}:{self.template_key}:{self.created_at:%Y-%m-%d %H:%M}"


class ClipStudyHistory(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="clip_study_history")
    clip = models.ForeignKey("clips.Clip", on_delete=models.CASCADE, related_name="study_histories")
    last_studied_at = models.DateTimeField(null=True, blank=True)
    study_count = models.PositiveIntegerField(default=0)
    total_repeat_count = models.PositiveIntegerField(default=0)
    total_watch_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "clip"], name="uniq_studyhistory_user_clip"),
        ]

    def __str__(self) -> str:
        return f"{self.user} - {self.clip}"
