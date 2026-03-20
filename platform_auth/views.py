from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import ThePeachLoginForm, ThePeachSignupForm
from .services import (
    ThePeachAuthError,
    fetch_thepeach_profile,
    login_with_thepeach,
    logout_from_thepeach,
    signup_with_thepeach,
    sync_local_user,
)
from .session import (
    SESSION_ACCESS_TOKEN_KEY,
    SESSION_REFRESH_TOKEN_KEY,
    clear_thepeach_session,
    store_thepeach_session,
)


def _complete_login(request, *, auth_data: dict):
    access_token = auth_data.get("access", "")
    refresh_token = auth_data.get("refresh", "")
    if not access_token or not refresh_token:
        raise ThePeachAuthError("ThePeach 로그인 응답에 토큰이 없습니다.")
    profile = fetch_thepeach_profile(access_token=access_token)
    local_user = sync_local_user(profile)
    auth_login(request, local_user, backend="django.contrib.auth.backends.ModelBackend")
    store_thepeach_session(
        request=request,
        access_token=access_token,
        refresh_token=refresh_token,
        profile={
            "id": profile.id,
            "email": profile.email,
            "display_name": profile.display_name,
            "full_name": profile.full_name,
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "is_active": profile.is_active,
        },
    )


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(request.GET.get("next") or settings.LOGIN_REDIRECT_URL)

    form = ThePeachLoginForm(request.POST or None)
    next_url = request.GET.get("next") or request.POST.get("next") or settings.LOGIN_REDIRECT_URL
    suggest_signup = False

    if request.method == "POST" and form.is_valid():
        try:
            auth_data = login_with_thepeach(
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
            )
            _complete_login(request, auth_data=auth_data)
            return redirect(next_url)
        except ThePeachAuthError as exc:
            error_message = str(exc)
            messages.error(request, error_message)
            if error_message in {"Invalid email or password.", "ThePeach rejected the supplied credentials."}:
                suggest_signup = True

    return render(
        request,
        "registration/login.html",
        {
            "form": form,
            "next": next_url,
            "suggest_signup": suggest_signup,
            "thepeach_login_base_url": settings.THEPEACH_LOGIN_BASE_URL,
            "thepeach_upstream_host_header": settings.THEPEACH_UPSTREAM_HOST_HEADER,
        },
    )


@require_http_methods(["GET", "POST"])
def signup_view(request):
    if request.user.is_authenticated:
        return redirect(request.GET.get("next") or settings.LOGIN_REDIRECT_URL)

    form = ThePeachSignupForm(request.POST or None)
    next_url = request.GET.get("next") or request.POST.get("next") or settings.LOGIN_REDIRECT_URL

    if request.method == "POST" and form.is_valid():
        try:
            signup_with_thepeach(
                email=form.cleaned_data["email"],
                full_name=form.cleaned_data["full_name"],
                smartphone_number=form.cleaned_data["smartphone_number"],
                password=form.cleaned_data["password"],
            )
            auth_data = login_with_thepeach(
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
            )
            _complete_login(request, auth_data=auth_data)
            messages.success(request, "ThePeach 계정이 생성되었습니다.")
            return redirect(next_url)
        except ThePeachAuthError as exc:
            messages.error(request, str(exc))

    return render(
        request,
        "registration/signup.html",
        {
            "form": form,
            "next": next_url,
            "thepeach_login_base_url": settings.THEPEACH_LOGIN_BASE_URL,
            "thepeach_upstream_host_header": settings.THEPEACH_UPSTREAM_HOST_HEADER,
        },
    )


@require_http_methods(["POST"])
def logout_view(request):
    access_token = request.session.get(SESSION_ACCESS_TOKEN_KEY, "")
    refresh_token = request.session.get(SESSION_REFRESH_TOKEN_KEY, "")
    if access_token and refresh_token:
        try:
            logout_from_thepeach(access_token=access_token, refresh_token=refresh_token)
        except ThePeachAuthError:
            pass
    clear_thepeach_session(request)
    auth_logout(request)
    return redirect(settings.LOGOUT_REDIRECT_URL)
