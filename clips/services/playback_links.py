from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from clips.models import Clip

PLAYBACK_LINK_SALT = "internal-api-clip-playback"


def _can_view_clip(user, clip: Clip) -> bool:
    return user.is_authenticated and (clip.owner_id == user.id or clip.is_public)


def generate_clip_playback_link(request, *, clip: Clip, user) -> dict[str, Any]:
    if not _can_view_clip(user, clip):
        raise PermissionDenied("You do not have access to this clip.")

    if clip.file_status != "ready" or not clip.clip_file:
        raise PermissionDenied("Clip is not ready for playback.")

    ttl_seconds = max(60, int(getattr(settings, "INTERNAL_PLAYBACK_LINK_TTL_SECONDS", 900)))
    expires_at = timezone.now() + timedelta(seconds=ttl_seconds)

    payload = {
        "clip_id": clip.id,
        "owner_id": clip.owner_id,
        "exp": int(expires_at.timestamp()),
    }
    token = signing.dumps(payload, salt=PLAYBACK_LINK_SALT)
    path = reverse("internal_api:clip-playback-file", kwargs={"clip_id": clip.id})
    playback_url = request.build_absolute_uri(f"{path}?token={token}")

    return {
        "clip_id": clip.id,
        "title": clip.title,
        "playback_url": playback_url,
        "expires_at": expires_at.isoformat(),
        "requires_auth": False,
    }


def validate_clip_playback_token(*, clip_id: int, token: str) -> Clip:
    ttl_seconds = max(60, int(getattr(settings, "INTERNAL_PLAYBACK_LINK_TTL_SECONDS", 900)))
    data = signing.loads(token, salt=PLAYBACK_LINK_SALT, max_age=ttl_seconds)

    expected_clip_id = int(data.get("clip_id", 0))
    expected_owner_id = int(data.get("owner_id", 0))
    expires_at_epoch = int(data.get("exp", 0))

    if expected_clip_id != clip_id:
        raise PermissionDenied("Token does not match clip.")

    if expires_at_epoch <= int(timezone.now().timestamp()):
        raise PermissionDenied("Token expired.")

    clip = Clip.objects.select_related("owner").filter(id=clip_id, is_active=True).first()
    if not clip or clip.owner_id != expected_owner_id:
        raise PermissionDenied("Clip not available.")

    if clip.file_status != "ready" or not clip.clip_file:
        raise PermissionDenied("Clip is not ready for playback.")

    return clip
