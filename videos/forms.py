import mimetypes
from pathlib import Path

from django import forms
from django.conf import settings

from .services.youtube import InvalidYouTubeInput, normalize_youtube_input
from .models import MasterVideoSourceType


class MasterVideoCreateForm(forms.Form):
    source_type = forms.ChoiceField(
        label="Source Type",
        choices=MasterVideoSourceType.choices,
        initial=MasterVideoSourceType.YOUTUBE,
        widget=forms.RadioSelect,
    )
    youtube_input = forms.CharField(
        label="YouTube URL or Video ID",
        max_length=500,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "https://www.youtube.com/watch?v=... or dQw4w9WgXcQ",
            }
        ),
    )
    upload_title = forms.CharField(
        label="Upload title",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Optional. Defaults to the uploaded filename.",
            }
        ),
    )
    video_file = forms.FileField(
        label="Video file",
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": "video/*,.mp4,.mov,.mkv,.webm,.m4v"}),
    )
    subtitle_file = forms.FileField(
        label="Subtitle file",
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".srt,.vtt,.ass,.ssa"}),
    )

    def clean_youtube_input(self):
        value = (self.cleaned_data.get("youtube_input") or "").strip()
        if not value:
            return value
        try:
            normalized = normalize_youtube_input(value)
        except InvalidYouTubeInput as exc:
            raise forms.ValidationError(str(exc)) from exc

        self.cleaned_data["youtube_video_id"] = normalized.youtube_video_id
        self.cleaned_data["youtube_url"] = normalized.youtube_url
        return value

    def clean_video_file(self):
        uploaded = self.cleaned_data.get("video_file")
        if not uploaded:
            return uploaded

        max_size = getattr(settings, "MASTER_VIDEO_UPLOAD_MAX_FILE_SIZE_BYTES", 5 * 1024 * 1024 * 1024)
        allowed_ext = set(
            getattr(settings, "MASTER_VIDEO_UPLOAD_ALLOWED_EXTENSIONS", [".mp4", ".mov", ".mkv", ".webm", ".m4v"])
        )

        if uploaded.size <= 0:
            raise forms.ValidationError("Empty file is not allowed.")
        if uploaded.size > max_size:
            raise forms.ValidationError("File exceeds the upload size limit.")

        ext = Path(uploaded.name).suffix.lower()
        if ext not in allowed_ext:
            raise forms.ValidationError("Unsupported file extension.")

        guessed_mime, _ = mimetypes.guess_type(uploaded.name)
        provided_mime = getattr(uploaded, "content_type", "") or guessed_mime or ""
        if provided_mime and not provided_mime.startswith("video/"):
            raise forms.ValidationError("Only video files can be uploaded.")

        return uploaded

    def clean_subtitle_file(self):
        uploaded = self.cleaned_data.get("subtitle_file")
        if not uploaded:
            return uploaded

        ext = Path(uploaded.name).suffix.lower()
        if ext not in {".srt", ".vtt", ".ass", ".ssa"}:
            raise forms.ValidationError("Unsupported subtitle file extension.")
        if uploaded.size <= 0:
            raise forms.ValidationError("Empty subtitle file is not allowed.")

        max_size = getattr(settings, "MASTER_VIDEO_SUBTITLE_MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024)
        if uploaded.size > max_size:
            raise forms.ValidationError("Subtitle file exceeds the upload size limit.")

        return uploaded

    def clean(self):
        cleaned = super().clean()
        source_type = cleaned.get("source_type")

        if source_type == MasterVideoSourceType.YOUTUBE:
            youtube_input = (cleaned.get("youtube_input") or "").strip()
            if not youtube_input:
                self.add_error("youtube_input", "Please enter a YouTube URL or video ID.")
            if cleaned.get("video_file"):
                self.add_error("video_file", "Remove the uploaded file when registering a YouTube video.")
        elif source_type == MasterVideoSourceType.UPLOAD:
            if not cleaned.get("video_file"):
                self.add_error("video_file", "Please choose a local video file to upload.")
            if (cleaned.get("youtube_input") or "").strip():
                self.add_error("youtube_input", "Clear the YouTube input when using local upload.")
        else:
            self.add_error("source_type", "Unsupported source type.")

        return cleaned
