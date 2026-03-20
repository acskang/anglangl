import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MCPSettings:
    django_api_base_url: str
    django_internal_api_token: str
    django_oauth_access_token: str
    mcp_public_base_url: str
    django_user_header_name: str
    django_default_user_id: str
    request_timeout_seconds: float

    @property
    def bearer_token(self) -> str:
        if self.django_internal_api_token:
            return self.django_internal_api_token
        return self.django_oauth_access_token



def load_settings() -> MCPSettings:
    return MCPSettings(
        django_api_base_url=os.environ.get("DJANGO_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        django_internal_api_token=os.environ.get("DJANGO_INTERNAL_API_TOKEN", ""),
        django_oauth_access_token=os.environ.get("DJANGO_OAUTH_ACCESS_TOKEN", ""),
        mcp_public_base_url=os.environ.get("MCP_PUBLIC_BASE_URL", "").rstrip("/"),
        django_user_header_name=os.environ.get("DJANGO_USER_HEADER_NAME", "X-Internal-User-Id"),
        django_default_user_id=os.environ.get("DJANGO_DEFAULT_USER_ID", ""),
        request_timeout_seconds=float(os.environ.get("DJANGO_API_TIMEOUT_SECONDS", "10")),
    )
