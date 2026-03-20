# Listening Clips MCP Server

This server exposes safe MCP tools for clip/video/study data by calling Django internal APIs.

## Environment
Use `mcp_server/.env.example` as baseline:

- `DJANGO_API_BASE_URL`
- `DJANGO_INTERNAL_API_TOKEN` or `DJANGO_OAUTH_ACCESS_TOKEN`
- `MCP_PUBLIC_BASE_URL`
- `DJANGO_USER_HEADER_NAME`
- `DJANGO_DEFAULT_USER_ID`

## Run
```bash
python -m mcp_server.server
```

## Tool surface
- `search_clips(query, visibility, limit, offset)`
- `get_clip_detail(clip_id)`
- `get_clip_playback_link(clip_id)`
- `list_recent_study_clips(limit)`
- `search_master_videos(query, mine_only, limit, offset)`
- `get_master_video_detail(master_video_id)`
- `get_upload_batch_detail(batch_id)`

## Security notes
- The MCP server never reads Django DB directly.
- It forwards user identity via header and relies on Django permission checks.
- It returns structured JSON with sanitized errors.
