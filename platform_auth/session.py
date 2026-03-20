SESSION_ACCESS_TOKEN_KEY = "thepeach_access_token"
SESSION_REFRESH_TOKEN_KEY = "thepeach_refresh_token"
SESSION_PROFILE_KEY = "thepeach_profile"


def store_thepeach_session(*, request, access_token: str, refresh_token: str, profile: dict) -> None:
    request.session[SESSION_ACCESS_TOKEN_KEY] = access_token
    request.session[SESSION_REFRESH_TOKEN_KEY] = refresh_token
    request.session[SESSION_PROFILE_KEY] = profile


def clear_thepeach_session(request) -> None:
    for key in (SESSION_ACCESS_TOKEN_KEY, SESSION_REFRESH_TOKEN_KEY, SESSION_PROFILE_KEY):
        request.session.pop(key, None)
