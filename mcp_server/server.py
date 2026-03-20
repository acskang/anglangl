import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server.config import load_settings
from mcp_server.django_client import DjangoInternalApiClient
from mcp_server.schemas import (
    BatchIdInput,
    ClipIdInput,
    ClipSearchInput,
    RecentStudyInput,
    VideoIdInput,
    VideoSearchInput,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp.listening_clips")

settings = load_settings()
client = DjangoInternalApiClient(settings)
mcp = FastMCP("listening-clips-mcp")


def get_widget_resource_templates() -> dict[str, str]:
    # Placeholder for future ChatGPT widget registrations.
    return {
        "clip_search_results": "widget://listening-clips/clip-search-results",
        "clip_detail_card": "widget://listening-clips/clip-detail-card",
    }


def _resolve_user_id(ctx: Any) -> str:
    # Best-effort extraction across SDK/runtime variants.
    if ctx is not None:
        for attr in ("user_id", "user", "subject"):
            value = getattr(ctx, attr, None)
            if value:
                return str(value)
        request_context = getattr(ctx, "request_context", None)
        if isinstance(request_context, dict):
            for key in ("user_id", "sub", "subject"):
                value = request_context.get(key)
                if value:
                    return str(value)
    return settings.django_default_user_id


@mcp.tool(description="Search clips visible to the current user.")
async def search_clips(query: str = "", visibility: str = "all", limit: int = 20, offset: int = 0, ctx: Any = None) -> dict:
    args = ClipSearchInput(query=query, visibility=visibility, limit=limit, offset=offset)
    user_id = _resolve_user_id(ctx)
    return await client.request_json(
        method="GET",
        path="/internal-api/clips/search/",
        user_id=user_id,
        params=args.model_dump(),
    )


@mcp.tool(description="Get clip detail for a clip visible to the current user.")
async def get_clip_detail(clip_id: int, ctx: Any = None) -> dict:
    args = ClipIdInput(clip_id=clip_id)
    user_id = _resolve_user_id(ctx)
    return await client.request_json(
        method="GET",
        path=f"/internal-api/clips/{args.clip_id}/",
        user_id=user_id,
    )


@mcp.tool(description="Get an authorized temporary playback link for a clip.")
async def get_clip_playback_link(clip_id: int, ctx: Any = None) -> dict:
    args = ClipIdInput(clip_id=clip_id)
    user_id = _resolve_user_id(ctx)
    return await client.request_json(
        method="POST",
        path=f"/internal-api/clips/{args.clip_id}/playback-link/",
        user_id=user_id,
    )


@mcp.tool(description="List recently studied clips for the current user.")
async def list_recent_study_clips(limit: int = 10, ctx: Any = None) -> dict:
    args = RecentStudyInput(limit=limit)
    user_id = _resolve_user_id(ctx)
    return await client.request_json(
        method="GET",
        path="/internal-api/study/recent/",
        user_id=user_id,
        params=args.model_dump(),
    )


@mcp.tool(description="Search master videos owned by the current user.")
async def search_master_videos(query: str = "", mine_only: bool = True, limit: int = 20, offset: int = 0, ctx: Any = None) -> dict:
    args = VideoSearchInput(query=query, mine_only=mine_only, limit=limit, offset=offset)
    user_id = _resolve_user_id(ctx)
    return await client.request_json(
        method="GET",
        path="/internal-api/videos/search/",
        user_id=user_id,
        params=args.model_dump(),
    )


@mcp.tool(description="Get master video detail for a video owned by the current user.")
async def get_master_video_detail(master_video_id: int, ctx: Any = None) -> dict:
    args = VideoIdInput(master_video_id=master_video_id)
    user_id = _resolve_user_id(ctx)
    return await client.request_json(
        method="GET",
        path=f"/internal-api/videos/{args.master_video_id}/",
        user_id=user_id,
    )


@mcp.tool(description="Get upload batch detail for a batch owned by the current user.")
async def get_upload_batch_detail(batch_id: int, ctx: Any = None) -> dict:
    args = BatchIdInput(batch_id=batch_id)
    user_id = _resolve_user_id(ctx)
    return await client.request_json(
        method="GET",
        path=f"/internal-api/upload-batches/{args.batch_id}/",
        user_id=user_id,
    )


if __name__ == "__main__":
    mcp.run()
