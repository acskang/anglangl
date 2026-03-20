from django import forms


class ThePeachLoginForm(forms.Form):
    email = forms.EmailField(label="ThePeach 이메일", max_length=254)
    password = forms.CharField(label="비밀번호", strip=False, widget=forms.PasswordInput)


class ThePeachSignupForm(forms.Form):
    email = forms.EmailField(label="이메일", max_length=254)
    full_name = forms.CharField(label="이름", max_length=255)
    smartphone_number = forms.CharField(label="휴대전화", max_length=30)
    password = forms.CharField(label="비밀번호", strip=False, min_length=8, widget=forms.PasswordInput)
    password_confirm = forms.CharField(label="비밀번호 확인", strip=False, widget=forms.PasswordInput)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("password") and cleaned_data.get("password_confirm"):
            if cleaned_data["password"] != cleaned_data["password_confirm"]:
                self.add_error("password_confirm", "비밀번호가 일치하지 않습니다.")
        return cleaned_data
