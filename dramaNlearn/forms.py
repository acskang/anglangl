from django import forms

from .models import ThumbnailAsset


class ThumbnailAssetForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["image"].required = False

    class Meta:
        model = ThumbnailAsset
        fields = ["name", "image"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "썸네일 이름"}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }
