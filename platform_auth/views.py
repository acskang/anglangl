from django.conf import settings
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.http import JsonResponse
from django.shortcuts import redirect, render, resolve_url
from django.views.decorators.http import require_http_methods

from .cookies import clear_thepeach_auth_cookies, set_thepeach_auth_cookies
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
        raise ThePeachAuthError("로그인 응답이 올바르지 않습니다.")
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
    return access_token, refresh_token


def _is_ajax_request(request) -> bool:
    requested_with = request.headers.get("X-Requested-With", "")
    accept = request.headers.get("Accept", "")
    return requested_with == "XMLHttpRequest" or "application/json" in accept


def _first_form_error(form, default: str) -> str:
    for field_errors in form.errors.values():
        if field_errors:
            return str(field_errors[0])
    return default


def _sanitize_auth_error_message(message: str, *, mode: str) -> str:
    normalized = (message or "").strip()
    lowered = normalized.lower()

    invalid_credentials = {
        "Invalid email or password.",
        "ThePeach rejected the supplied credentials.",
        "Invalid credentials.",
    }
    if normalized in invalid_credentials or "invalid email or password" in lowered or "invalid credentials" in lowered:
        return "이메일 또는 비밀번호를 확인해주세요."
    if "already" in lowered and any(token in lowered for token in ("exists", "registered", "taken", "use")):
        return "이미 사용 중인 이메일입니다."
    if "password" in lowered and "match" in lowered:
        return "비밀번호가 일치하지 않습니다."
    if any(token in lowered for token in ("connect", "timeout", "timed out", "temporarily unavailable", "refused")):
        return "지금은 인증을 처리할 수 없습니다. 잠시 후 다시 시도해주세요."
    if mode == "signup":
        return "회원가입을 처리하지 못했습니다. 입력값을 확인한 뒤 다시 시도해주세요."
    return "로그인을 처리하지 못했습니다. 입력값을 확인한 뒤 다시 시도해주세요."


def _auth_context(
    *,
    next_url: str,
    mode: str,
    error_message: str = "",
    suggest_signup: bool = False,
    login_initial: dict | None = None,
    signup_initial: dict | None = None,
):
    return {
        "auth_modal_open": True,
        "auth_modal_mode": mode,
        "auth_modal_next": next_url,
        "auth_modal_error": error_message,
        "auth_suggest_signup": suggest_signup,
        "auth_login_initial": login_initial or {},
        "auth_signup_initial": signup_initial or {},
        "auth_modal_route": True,
        "auth_modal_cancel_url": settings.LOGOUT_REDIRECT_URL,
    }


def _json_error(message: str, *, status: int = 400, suggest_signup: bool = False):
    payload = {"ok": False, "error": message}
    if suggest_signup:
        payload["suggest_signup"] = True
    return JsonResponse(payload, status=status)


def _json_success(*, redirect_url: str, message: str = ""):
    return JsonResponse({"ok": True, "redirect_url": redirect_url, "message": message})


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(resolve_url(request.GET.get("next") or settings.LOGIN_REDIRECT_URL))

    form = ThePeachLoginForm(request.POST or None)
    next_url = resolve_url(request.GET.get("next") or request.POST.get("next") or settings.LOGIN_REDIRECT_URL)
    suggest_signup = False
    error_message = ""
    login_initial = {"email": request.POST.get("email", "").strip()}

    if request.method == "POST" and form.is_valid():
        try:
            auth_data = login_with_thepeach(
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
            )
            access_token, refresh_token = _complete_login(request, auth_data=auth_data)
            response = _json_success(redirect_url=next_url, message="로그인되었습니다.") if _is_ajax_request(request) else redirect(next_url)
            set_thepeach_auth_cookies(response, access_token=access_token, refresh_token=refresh_token)
            return response
        except ThePeachAuthError as exc:
            raw_message = str(exc)
            error_message = _sanitize_auth_error_message(raw_message, mode="login")
            if raw_message in {"Invalid email or password.", "ThePeach rejected the supplied credentials."} or "invalid email or password" in raw_message.lower():
                suggest_signup = True
            if _is_ajax_request(request):
                return _json_error(error_message, status=400, suggest_signup=suggest_signup)
    elif request.method == "POST":
        error_message = _first_form_error(form, "입력값을 확인해주세요.")
        if _is_ajax_request(request):
            return _json_error(error_message)

    return render(
        request,
        "registration/login.html",
        _auth_context(
            next_url=next_url,
            mode="login",
            error_message=error_message,
            suggest_signup=suggest_signup,
            login_initial=login_initial,
        ),
    )


@require_http_methods(["GET", "POST"])
def signup_view(request):
    if request.user.is_authenticated:
        return redirect(resolve_url(request.GET.get("next") or settings.LOGIN_REDIRECT_URL))

    form = ThePeachSignupForm(request.POST or None)
    next_url = resolve_url(request.GET.get("next") or request.POST.get("next") or settings.LOGIN_REDIRECT_URL)
    error_message = ""
    signup_initial = {
        "email": request.POST.get("email", "").strip(),
        "full_name": request.POST.get("full_name", "").strip(),
        "smartphone_number": request.POST.get("smartphone_number", "").strip(),
    }

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
            access_token, refresh_token = _complete_login(request, auth_data=auth_data)
            response = _json_success(redirect_url=next_url, message="회원가입이 완료되었습니다.") if _is_ajax_request(request) else redirect(next_url)
            set_thepeach_auth_cookies(response, access_token=access_token, refresh_token=refresh_token)
            return response
        except ThePeachAuthError as exc:
            error_message = _sanitize_auth_error_message(str(exc), mode="signup")
            if _is_ajax_request(request):
                return _json_error(error_message)
    elif request.method == "POST":
        error_message = _first_form_error(form, "입력값을 확인해주세요.")
        if _is_ajax_request(request):
            return _json_error(error_message)

    return render(
        request,
        "registration/signup.html",
        _auth_context(
            next_url=next_url,
            mode="signup",
            error_message=error_message,
            signup_initial=signup_initial,
        ),
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
    redirect_url = resolve_url(request.POST.get("next") or settings.LOGOUT_REDIRECT_URL)
    response = _json_success(redirect_url=redirect_url, message="로그아웃되었습니다.") if _is_ajax_request(request) else redirect(redirect_url)
    clear_thepeach_auth_cookies(response)
    return response
