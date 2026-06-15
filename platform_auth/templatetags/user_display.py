from django import template


register = template.Library()


@register.filter
def user_display_label(user) -> str:
    if not user:
        return ""

    full_name = ""
    get_full_name = getattr(user, "get_full_name", None)
    if callable(get_full_name):
        full_name = (get_full_name() or "").strip()
    if full_name:
        return full_name

    for attr in ("first_name", "display_name", "full_name"):
        value = (getattr(user, attr, "") or "").strip()
        if value:
            return value

    email = (getattr(user, "email", "") or "").strip()
    if email:
        return email.split("@", 1)[0]

    username = (getattr(user, "username", "") or "").strip()
    if username:
        return username.split("@", 1)[0]

    return ""
