from django import forms

class YouTubeURLForm(forms.Form):
    url = forms.URLField(
        label='YouTube URL',
        help_text='Paste a full YouTube URL to save it in your library.',
        widget=forms.URLInput(
            attrs={
                'class': 'glass-input',
                'placeholder': 'https://www.youtube.com/watch?v=...',
            }
        ),
    )


class ChapterURLForm(forms.Form):
    url = forms.URLField(
        label='YouTube URL',
        help_text='챕터가 있는 영상의 URL을 입력하세요.',
        widget=forms.URLInput(
            attrs={
                'class': 'glass-input',
                'placeholder': 'https://www.youtube.com/watch?v=...',
            }
        ),
    )
