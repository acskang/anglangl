SESSION_ACCESS_TOKEN_KEY = "thepeach_access_token"
SESSION_REFRESH_TOKEN_KEY = "thepeach_refresh_token"
SESSION_PROFILE_KEY = "thepeach_profile"
SESSION_AUTH_SOURCE_KEY = "thepeach_auth_source"
SESSION_AUTH_SOURCE_VALUE = "thepeach_sso"


def store_thepeach_session(*, request, access_token: str, refresh_token: str, profile: dict) -> None:
    request.session[SESSION_ACCESS_TOKEN_KEY] = access_token
    request.session[SESSION_REFRESH_TOKEN_KEY] = refresh_token
    request.session[SESSION_PROFILE_KEY] = profile
    request.session[SESSION_AUTH_SOURCE_KEY] = SESSION_AUTH_SOURCE_VALUE


def clear_thepeach_session(request) -> None:
    for key in (SESSION_ACCESS_TOKEN_KEY, SESSION_REFRESH_TOKEN_KEY, SESSION_PROFILE_KEY, SESSION_AUTH_SOURCE_KEY):
        request.session.pop(key, None)


def is_thepeach_session(request) -> bool:
    return request.session.get(SESSION_AUTH_SOURCE_KEY) == SESSION_AUTH_SOURCE_VALUE


def needs_thepeach_session_store(*, request, access_token: str, refresh_token: str, profile: dict) -> bool:
    if request.session.get(SESSION_ACCESS_TOKEN_KEY) != access_token:
        return True
    if request.session.get(SESSION_REFRESH_TOKEN_KEY) != refresh_token:
        return True
    if request.session.get(SESSION_PROFILE_KEY) != profile:
        return True
    return request.session.get(SESSION_AUTH_SOURCE_KEY) != SESSION_AUTH_SOURCE_VALUE
