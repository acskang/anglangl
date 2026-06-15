from django import forms

from .models import StudyMaterial


class StudyMaterialForm(forms.ModelForm):
    class Meta:
        model = StudyMaterial
        fields = [
            "title",
            "material_type",
            "purpose",
            "difficulty",
            "visibility",
            "generated_content",
            "editable_notes",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "학습 자료 제목"}),
            "generated_content": forms.Textarea(
                attrs={
                    "rows": 18,
                    "placeholder": "생성된 학습 자료 초안이 여기에 들어갑니다.",
                }
            ),
            "editable_notes": forms.Textarea(
                attrs={
                    "rows": 8,
                    "placeholder": "학습 메모, 수정 포인트, 다음 액션을 정리하세요.",
                }
            ),
        }
