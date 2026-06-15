import mimetypes
from pathlib import Path

from django import forms
from django.conf import settings

from core.models import ProcessingState
from videos.models import MasterVideo

from .models import AlbumImage, Clip, ClipImage, ClipSourceType, ClipUploadBatch
from .timecode import format_hhmmss, parse_hhmmss


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            if not data:
                raise forms.ValidationError("Please select at least one file.")
            return [single_clean(item, initial) for item in data]
        return [single_clean(data, initial)]


class ClipExtractBaseForm(forms.ModelForm):
    start_time_seconds = forms.CharField(
        label="Start time",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "00:00:00:0",
                "inputmode": "numeric",
            }
        ),
        help_text="Format: hh:mm:ss:s (0.1-second steps)",
    )
    end_time_seconds = forms.CharField(
        label="End time",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "00:00:30:0",
                "inputmode": "numeric",
            }
        ),
        help_text="Format: hh:mm:ss:s (0.1-second steps)",
    )

    class Meta:
        model = Clip
        fields = [
            "master_video",
            "title",
            "description",
            "start_time_seconds",
            "end_time_seconds",
            "is_public",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "is_public": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        if self.instance and self.instance.pk:
            self.initial.setdefault("start_time_seconds", format_hhmmss(self.instance.start_time_seconds))
            self.initial.setdefault("end_time_seconds", format_hhmmss(self.instance.end_time_seconds))

        if "master_video" in self.fields:
            ready_videos = MasterVideo.objects.filter(
                owner=user,
                download_status=ProcessingState.READY,
                is_active=True,
            )
            self.fields["master_video"].queryset = ready_videos
            self.fields["master_video"].widget.attrs.update({"class": "form-select"})

    def clean_start_time_seconds(self):
        value = self.cleaned_data.get("start_time_seconds")
        try:
            return parse_hhmmss(value)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean_end_time_seconds(self):
        value = self.cleaned_data.get("end_time_seconds")
        try:
            return parse_hhmmss(value)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean(self):
        cleaned = super().clean()
        master_video = cleaned.get("master_video") or getattr(self.instance, "master_video", None)
        start = cleaned.get("start_time_seconds")
        end = cleaned.get("end_time_seconds")

        if not master_video:
            return cleaned

        if master_video.owner_id != self.user.id:
            self.add_error("master_video", "You can only create clips from your own videos.")

        if master_video.download_status != ProcessingState.READY:
            self.add_error("master_video", "Master video must be downloaded and ready.")

        if master_video.duration_seconds is None:
            self.add_error("master_video", "Master video duration is unknown and cannot be clipped yet.")

        if start is not None and end is not None:
            if end <= start:
                self.add_error("end_time_seconds", "End time must be greater than start time.")
            if master_video.duration_seconds is not None and end > master_video.duration_seconds:
                self.add_error(
                    "end_time_seconds",
                    f"End time cannot exceed source duration ({format_hhmmss(master_video.duration_seconds)}).",
                )

        return cleaned


class ClipCreateForm(ClipExtractBaseForm):
    pass


class ClipPlanForm(forms.Form):
    master_video = forms.ModelChoiceField(
        queryset=MasterVideo.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Master video",
    )
    range_start = forms.CharField(
        label="Extraction range start",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "00:00:00:0",
                "inputmode": "numeric",
            }
        ),
    )
    range_end = forms.CharField(
        label="Extraction range end",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "00:05:00:0",
                "inputmode": "numeric",
            }
        ),
    )
    is_public = forms.BooleanField(required=False, widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["master_video"].queryset = MasterVideo.objects.filter(
            owner=user,
            download_status=ProcessingState.READY,
            is_active=True,
        )

    def clean_range_start(self):
        try:
            return parse_hhmmss(self.cleaned_data.get("range_start"))
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean_range_end(self):
        try:
            return parse_hhmmss(self.cleaned_data.get("range_end"))
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean(self):
        cleaned = super().clean()
        master_video = cleaned.get("master_video")
        range_start = cleaned.get("range_start")
        range_end = cleaned.get("range_end")

        if not master_video:
            return cleaned

        if master_video.owner_id != self.user.id:
            self.add_error("master_video", "You can only create clips from your own videos.")
        if not master_video.video_file:
            self.add_error("master_video", "Selected video does not have a playable source file.")
        if not master_video.subtitle_file:
            self.add_error("master_video", "Upload a subtitle file on the video first.")
        if master_video.duration_seconds is None:
            self.add_error("master_video", "Source video duration is unknown.")

        if range_start is not None and range_end is not None:
            if range_end <= range_start:
                self.add_error("range_end", "End time must be greater than start time.")
            if master_video.duration_seconds is not None and range_end > master_video.duration_seconds:
                self.add_error("range_end", f"End time cannot exceed source duration ({format_hhmmss(master_video.duration_seconds)}).")

        return cleaned


class ClipExtractUpdateForm(ClipExtractBaseForm):
    class Meta(ClipExtractBaseForm.Meta):
        fields = [
            "title",
            "description",
            "start_time_seconds",
            "end_time_seconds",
            "is_public",
        ]


class UploadedClipUpdateForm(forms.ModelForm):
    class Meta:
        model = Clip
        fields = ["title", "description", "is_public"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "is_public": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class ClipMetadataForm(forms.ModelForm):
    class Meta:
        model = Clip
        fields = ["title", "description"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class ClipImageMetadataForm(forms.ModelForm):
    class Meta:
        model = ClipImage
        fields = ["title", "description"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class AlbumImageUploadForm(forms.ModelForm):
    class Meta:
        model = AlbumImage
        fields = ["title", "description", "tags", "image"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "tags": forms.TextInput(attrs={"class": "form-control", "placeholder": "comma,separated,tags"}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
        }


class AlbumImageMetadataForm(forms.ModelForm):
    class Meta:
        model = AlbumImage
        fields = ["title", "description", "tags"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "tags": forms.TextInput(attrs={"class": "form-control"}),
        }


class ClipBulkUploadForm(forms.Form):
    default_is_public = forms.BooleanField(required=False, widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))
    files = MultipleFileField(
        widget=MultipleFileInput(attrs={"class": "form-control"}),
        required=True,
    )

    def clean_files(self):
        uploaded_files = self.cleaned_data.get("files") or self.files.getlist("files")
        if not uploaded_files:
            raise forms.ValidationError("Please select at least one file.")

        max_files = getattr(settings, "CLIP_UPLOAD_MAX_FILES_PER_BATCH", 30)
        max_size = getattr(settings, "CLIP_UPLOAD_MAX_FILE_SIZE_BYTES", 300 * 1024 * 1024)
        allowed_ext = set(getattr(settings, "CLIP_UPLOAD_ALLOWED_EXTENSIONS", [".mp4", ".mov", ".mkv", ".webm", ".m4v"]))

        if len(uploaded_files) > max_files:
            raise forms.ValidationError(f"You can upload up to {max_files} files per batch.")

        for f in uploaded_files:
            if f.size <= 0:
                raise forms.ValidationError(f"{f.name}: empty file is not allowed.")
            if f.size > max_size:
                raise forms.ValidationError(f"{f.name}: file exceeds size limit.")

            ext = Path(f.name).suffix.lower()
            if ext not in allowed_ext:
                raise forms.ValidationError(f"{f.name}: unsupported file extension.")

            guessed_mime, _ = mimetypes.guess_type(f.name)
            provided_mime = getattr(f, "content_type", "") or guessed_mime or ""
            if provided_mime and not provided_mime.startswith("video/"):
                raise forms.ValidationError(f"{f.name}: non-video file is not allowed.")

        return uploaded_files


class ClipUploadBatchUpdateForm(forms.ModelForm):
    class Meta:
        model = ClipUploadBatch
        fields = ["title", "description", "source_directory_label"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "source_directory_label": forms.TextInput(attrs={"class": "form-control"}),
        }
