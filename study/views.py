from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import StudyMaterialForm
from .models import (
    StudyMaterial,
    StudyMaterialGeneration,
    StudyMaterialPurpose,
    StudyMaterialSourceType,
    StudyMaterialType,
    StudyMaterialVisibility,
)
from .services import (
    append_generation_history,
    build_initial_material_content,
    build_material_title,
    resolve_study_source,
    suggest_difficulty,
    suggest_purpose,
)


class StudyMaterialOwnerMixin(LoginRequiredMixin):
    model = StudyMaterial

    def get_queryset(self):
        return (
            StudyMaterial.objects.filter(owner=self.request.user)
            .select_related(
                "source_clip",
                "source_master_video",
                "source_drama_video",
                "copied_from",
            )
        )


class StudyMaterialListView(StudyMaterialOwnerMixin, ListView):
    template_name = "study/material_list.html"
    context_object_name = "materials"
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset()
        material_type = (self.request.GET.get("material_type") or "").strip()
        purpose = (self.request.GET.get("purpose") or "").strip()
        source_type = (self.request.GET.get("source_type") or "").strip()
        ownership = (self.request.GET.get("ownership") or "").strip()
        sort = (self.request.GET.get("sort") or "recent").strip()

        if material_type:
            queryset = queryset.filter(material_type=material_type)
        if purpose:
            queryset = queryset.filter(purpose=purpose)
        if source_type:
            queryset = queryset.filter(source_type=source_type)
        if ownership == "created":
            queryset = queryset.filter(copied_from__isnull=True)
        elif ownership == "imported":
            queryset = queryset.filter(copied_from__isnull=False)
        if sort == "oldest":
            queryset = queryset.order_by("created_at", "id")
        elif sort == "title":
            queryset = queryset.order_by("title", "-updated_at")
        elif sort == "updated":
            queryset = queryset.order_by("-updated_at", "-created_at")
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_mode"] = "library"
        context["page_title"] = "학습 자료 라이브러리"
        context["page_description"] = "생성한 초안을 저장하고, 다시 열고, 목적별로 정리하는 시작점입니다."
        context["material_type_choices"] = StudyMaterialType.choices
        context["purpose_choices"] = StudyMaterialPurpose.choices
        context["source_type_choices"] = StudyMaterialSourceType.choices
        context["sort_choices"] = [
            ("recent", "최근 생성 순"),
            ("updated", "최근 수정 순"),
            ("oldest", "오래된 순"),
            ("title", "제목 순"),
        ]
        return context


class StudyMaterialCreateView(LoginRequiredMixin, CreateView):
    template_name = "study/material_form.html"
    form_class = StudyMaterialForm

    def get_initial(self):
        initial = super().get_initial()
        source = resolve_study_source(user=self.request.user, params=self.request.GET)
        material_type = (self.request.GET.get("material_type") or "").strip() or initial.get("material_type") or "shadowing_script"
        purpose = suggest_purpose(material_type)

        initial.update(
            {
                "material_type": material_type,
                "purpose": purpose,
                "difficulty": suggest_difficulty(source),
                "title": build_material_title(source, material_type),
                "generated_content": build_initial_material_content(
                    source=source,
                    material_type=material_type,
                    purpose=purpose,
                ),
            }
        )
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["source_payload"] = resolve_study_source(user=self.request.user, params=self.request.GET)
        return context

    def form_valid(self, form):
        source = resolve_study_source(user=self.request.user, params=self.request.GET)
        material = form.save(commit=False)
        material.owner = self.request.user
        material.source_type = source.source_type
        material.source_title = source.title
        material.source_url = source.source_url
        material.imdb_code = source.imdb_code
        material.source_clip = source.source_clip
        material.source_master_video = source.source_master_video
        material.source_drama_video = source.source_drama_video
        material.generation_history = append_generation_history(
            material,
            source=source,
            template_key=material.material_type,
        )
        material.save()
        StudyMaterialGeneration.objects.create(
            material=material,
            created_by=self.request.user,
            template_key=material.material_type,
            prompt_intent="initial_draft",
            input_snapshot={
                "source_type": source.source_type,
                "source_title": source.title,
                "source_url": source.source_url,
                "imdb_code": source.imdb_code,
            },
            output_snapshot={
                "generated_content": material.generated_content,
                "editable_notes": material.editable_notes,
            },
        )
        self.object = material
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("study:detail", kwargs={"pk": self.object.pk})


class StudyMaterialDetailView(StudyMaterialOwnerMixin, DetailView):
    template_name = "study/material_detail.html"
    context_object_name = "material"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_mode"] = "library"
        context["can_edit"] = True
        context["can_clone"] = True
        context["back_url"] = reverse("study:list")
        context["can_toggle_visibility"] = True
        return context


class StudyMaterialUpdateView(StudyMaterialOwnerMixin, UpdateView):
    template_name = "study/material_form.html"
    form_class = StudyMaterialForm
    context_object_name = "material"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["source_payload"] = None
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        StudyMaterialGeneration.objects.create(
            material=self.object,
            created_by=self.request.user,
            template_key=self.object.material_type,
            prompt_intent="manual_edit",
            input_snapshot={
                "material_id": self.object.id,
            },
            output_snapshot={
                "generated_content": self.object.generated_content,
                "editable_notes": self.object.editable_notes,
            },
        )
        return response

    def get_success_url(self):
        return reverse("study:detail", kwargs={"pk": self.object.pk})


class StudyMaterialExploreListView(ListView):
    template_name = "study/material_list.html"
    context_object_name = "materials"
    paginate_by = 20
    model = StudyMaterial

    def get_queryset(self):
        queryset = (
            StudyMaterial.objects.filter(visibility=StudyMaterialVisibility.PUBLIC)
            .select_related(
                "owner",
                "source_clip",
                "source_master_video",
                "source_drama_video",
                "copied_from",
            )
            .order_by("-updated_at", "-created_at")
        )
        material_type = (self.request.GET.get("material_type") or "").strip()
        purpose = (self.request.GET.get("purpose") or "").strip()
        source_type = (self.request.GET.get("source_type") or "").strip()
        sort = (self.request.GET.get("sort") or "recent").strip()

        if self.request.user.is_authenticated:
            queryset = queryset.exclude(owner=self.request.user)
        if material_type:
            queryset = queryset.filter(material_type=material_type)
        if purpose:
            queryset = queryset.filter(purpose=purpose)
        if source_type:
            queryset = queryset.filter(source_type=source_type)
        if sort == "oldest":
            queryset = queryset.order_by("created_at", "id")
        elif sort == "title":
            queryset = queryset.order_by("title", "-updated_at")
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_mode"] = "explore"
        context["page_title"] = "공개 학습 자료 탐색"
        context["page_description"] = "공개된 자료를 보고, 필요한 자료는 복제해서 내 라이브러리로 가져올 수 있습니다."
        context["material_type_choices"] = StudyMaterialType.choices
        context["purpose_choices"] = StudyMaterialPurpose.choices
        context["source_type_choices"] = StudyMaterialSourceType.choices
        context["sort_choices"] = [
            ("recent", "최근 공개 순"),
            ("oldest", "오래된 순"),
            ("title", "제목 순"),
        ]
        return context


class StudyMaterialPublicDetailView(DetailView):
    template_name = "study/material_detail.html"
    context_object_name = "material"
    model = StudyMaterial

    def get_queryset(self):
        queryset = StudyMaterial.objects.filter(visibility=StudyMaterialVisibility.PUBLIC).select_related(
            "owner",
            "source_clip",
            "source_master_video",
            "source_drama_video",
            "copied_from",
        )
        if self.request.user.is_authenticated:
            queryset = queryset.exclude(owner=self.request.user)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_mode"] = "explore"
        context["can_edit"] = False
        context["can_clone"] = self.request.user.is_authenticated
        context["back_url"] = reverse("study:explore")
        context["can_toggle_visibility"] = False
        return context


class StudyMaterialCloneView(LoginRequiredMixin, View):
    def post(self, request, pk):
        source_material = get_object_or_404(
            StudyMaterial.objects.select_related(
                "owner",
                "source_clip",
                "source_master_video",
                "source_drama_video",
                "copied_from",
            ),
            pk=pk,
        )

        if source_material.owner_id != request.user.id and source_material.visibility != StudyMaterialVisibility.PUBLIC:
            raise Http404("복제할 수 없는 자료입니다.")

        cloned_material = StudyMaterial.objects.create(
            owner=request.user,
            title=f"{source_material.title} · 내 사본",
            material_type=source_material.material_type,
            purpose=source_material.purpose,
            difficulty=source_material.difficulty,
            visibility=StudyMaterialVisibility.PRIVATE,
            source_type=source_material.source_type,
            source_title=source_material.source_title,
            source_url=source_material.source_url,
            imdb_code=source_material.imdb_code,
            source_master_video=source_material.source_master_video,
            source_clip=source_material.source_clip,
            source_drama_video=source_material.source_drama_video,
            copied_from=source_material,
            generated_content=source_material.generated_content,
            editable_notes=source_material.editable_notes,
            generation_history=list(source_material.generation_history or []),
        )
        StudyMaterialGeneration.objects.create(
            material=cloned_material,
            created_by=request.user,
            template_key=cloned_material.material_type,
            prompt_intent="clone_import",
            input_snapshot={
                "copied_from_id": source_material.id,
                "copied_from_owner_id": source_material.owner_id,
            },
            output_snapshot={
                "generated_content": cloned_material.generated_content,
                "editable_notes": cloned_material.editable_notes,
            },
        )
        return HttpResponseRedirect(reverse("study:detail", kwargs={"pk": cloned_material.pk}))


class StudyMaterialVisibilityToggleView(LoginRequiredMixin, View):
    def post(self, request, pk):
        material = get_object_or_404(StudyMaterial, pk=pk, owner=request.user)
        material.visibility = (
            StudyMaterialVisibility.PUBLIC
            if material.visibility == StudyMaterialVisibility.PRIVATE
            else StudyMaterialVisibility.PRIVATE
        )
        material.save(update_fields=["visibility", "updated_at"])
        StudyMaterialGeneration.objects.create(
            material=material,
            created_by=request.user,
            template_key=material.material_type,
            prompt_intent="visibility_toggle",
            input_snapshot={"material_id": material.id},
            output_snapshot={"visibility": material.visibility},
        )
        return HttpResponseRedirect(reverse("study:detail", kwargs={"pk": material.pk}))
