from django import template

from clips.timecode import format_hhmmss

register = template.Library()


@register.filter
def hhmmss(value):
    try:
        return format_hhmmss(float(value))
    except (TypeError, ValueError):
        return "-"
