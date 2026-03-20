import logging
from typing import Any

import httpx

from mcp_server.config import MCPSettings

logger = logging.getLogger(__name__)


class DjangoInternalApiClient:
    def __init__(self, settings: MCPSettings):
        self.settings = settings

    def _base_headers(self, user_id: str) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        token = self.settings.bearer_token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if user_id:
            headers[self.settings.django_user_header_name] = user_id
        return headers

    async def request_json(
        self,
        *,
        method: str,
        path: str,
        user_id: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.settings.django_api_base_url}{path}"
        headers = self._base_headers(user_id)
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                response = await client.request(method=method, url=url, headers=headers, params=params, json=json_body)
        except httpx.HTTPError:
            logger.exception("django_api_network_error", extra={"path": path})
            return {"ok": False, "error": "django_api_unreachable"}

        if response.status_code >= 400:
            logger.warning("django_api_error", extra={"path": path, "status_code": response.status_code})
            error = "request_failed"
            try:
                data = response.json()
                error = data.get("error", error)
            except Exception:  # noqa: BLE001
                pass
            return {
                "ok": False,
                "status": response.status_code,
                "error": error,
            }

        try:
            payload = response.json()
        except ValueError:
            return {"ok": False, "error": "invalid_json_response"}

        return {"ok": True, "data": payload}
