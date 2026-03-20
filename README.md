# ListenTube Foundation (Step 4)

Step 4 adds bulk local clip upload on top of YouTube download + extracted clip workflows.

## New in this step
- Bulk upload page for multiple local video files
- `ClipUploadBatch` model to track one upload request
- Unified `Clip` source model with `source_type`:
  - `extracted`
  - `uploaded`
- Unified clip file lifecycle status on `Clip.file_status`:
  - `pending`, `queued`, `processing`, `ready`, `failed`
- Per-file async post-processing task for uploaded clips:
  - `process_uploaded_clip(clip_id)`
- Batch aggregate status refresh task:
  - `refresh_upload_batch_status(batch_id)`
- ffprobe duration detection + ffmpeg thumbnail generation
- Upload batch list/detail pages

## Existing features preserved
- YouTube MasterVideo registration and async download
- Extracted clip creation and async ffmpeg extraction
- Clip detail/playback pages

## Playback direction
- This project should favor HLS (`m3u8`) as the long-term playback path.
- HLS fits browser streaming, adaptive delivery, and longer sessions better than serving large source files directly.
- Direct `mp4`/`mov`/`webm` playback remains useful for uploads, clips, and fallback cases, but it should not be treated as the primary playback architecture.

## Tech Stack
- Django
- PostgreSQL
- Celery
- Redis
- yt-dlp
- ffmpeg / ffprobe

## Core domain additions
### Clip
Added/refactored fields:
- `source_type` (`extracted` / `uploaded`)
- `master_video` nullable (required only for extracted)
- `upload_batch` nullable FK
- `original_filename`
- `file_size_bytes`
- `mime_type`
- `file_status`
- `file_error_message`

Rules:
- Uploaded clips:
  - `start_time_seconds = 0`
  - `end_time_seconds = duration_seconds`
  - `clip_file` is uploaded source file
- Extracted clips remain compatible with existing flow.

### ClipUploadBatch
Tracks one bulk upload request:
- owner/title/description/source_directory_label
- total/success/failed counters
- status: `pending`, `uploading`, `processing`, `completed`, `partial_failed`, `failed`
- error_message

## Environment variables
```bash
export SECRET_KEY='replace-me'
export DEBUG='True'
export ALLOWED_HOSTS='127.0.0.1,localhost'

# Database
export DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:5432/listen_practice'

# Redis / Celery
export CELERY_BROKER_URL='redis://127.0.0.1:6379/0'
export CELERY_RESULT_BACKEND='redis://127.0.0.1:6379/1'

# Static / media
export STATIC_URL='/static/'
export STATIC_ROOT='/absolute/path/to/staticfiles'
export MEDIA_URL='/media/'
export MEDIA_ROOT='/absolute/path/to/media'

# Upload limits
export CLIP_UPLOAD_MAX_FILES_PER_BATCH='30'
export CLIP_UPLOAD_MAX_FILE_SIZE_BYTES='314572800'
export CLIP_UPLOAD_ALLOWED_EXTENSIONS='.mp4,.mov,.mkv,.webm,.m4v'
```

## Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Check required binaries:
```bash
yt-dlp --version
ffmpeg -version
ffprobe -version
```

## Run app
```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Celery workers
Start Redis first, then workers:

```bash
celery -A config worker -l info -Q default
celery -A config worker -l info -Q youtube_download
celery -A config worker -l info -Q clip_extract
celery -A config worker -l info -Q clip_upload_process
```

## Routes
- Master videos:
  - `/videos/`, `/videos/create/`, `/videos/<id>/`
- Clips:
  - `/clips/`
  - `/clips/create/` (extracted clip)
  - `/clips/bulk-upload/` (local bulk upload)
  - `/clips/batches/`
  - `/clips/batches/<id>/`
  - `/clips/<id>/`, `/clips/<id>/edit/`, `/clips/<id>/delete/`, `/clips/<id>/retry/`

## File storage
- Downloaded source videos:
  - `media/master_videos/user_<id>/<master_video_id>/source.<ext>`
- Extracted clips:
  - `media/clips/user_<id>/<clip_id>/clip.mp4`
- Uploaded clips:
  - `media/uploaded_clips/user_<id>/batch_<batch_id>/<safe_filename>`
- Thumbnails (both source types):
  - `media/clips/user_<id>/<clip_id>/thumb.jpg`

## Notes
- Private clips are owner-only; public clips are publicly viewable.
- Existing legacy routes stay at `/legacy/`.
- The shared player already prioritizes `m3u8` items before direct file sources when auto-selecting playable media.

## Internal API + MCP integration
This project now includes an internal authenticated API for MCP consumption and a separate Python MCP server under `mcp_server/`.

### Django internal API endpoints
- `GET /internal-api/clips/search/`
- `GET /internal-api/clips/<id>/`
- `POST /internal-api/clips/<id>/playback-link/`
- `GET /internal-api/study/recent/`
- `GET /internal-api/videos/search/`
- `GET /internal-api/videos/<id>/`
- `GET /internal-api/upload-batches/<id>/`

Notes:
- All internal endpoints require `Authorization: Bearer <DJANGO_INTERNAL_API_TOKEN>` and `X-Internal-User-Id`.
- Responses are JSON-only (except signed playback file URL target).
- Raw local filesystem paths are never returned.

### Django env for internal API
```bash
export DJANGO_INTERNAL_API_TOKEN='replace-with-strong-token'
export INTERNAL_PLAYBACK_LINK_TTL_SECONDS='900'
```

### MCP server env
```bash
export DJANGO_API_BASE_URL='http://127.0.0.1:8000'
export DJANGO_INTERNAL_API_TOKEN='replace-with-strong-token'
# Optional instead of internal token:
# export DJANGO_OAUTH_ACCESS_TOKEN='...'
export MCP_PUBLIC_BASE_URL='http://127.0.0.1:3000'
export DJANGO_USER_HEADER_NAME='X-Internal-User-Id'
export DJANGO_DEFAULT_USER_ID='1'
export DJANGO_API_TIMEOUT_SECONDS='10'
```

### Local run commands
1. Start Django:
```bash
python manage.py runserver
```
2. Start MCP server:
```bash
python -m mcp_server.server
```

### Deployment notes
1. Keep `DJANGO_INTERNAL_API_TOKEN` in secret manager, never in VCS.
2. Set strict `ALLOWED_HOSTS` and HTTPS in production.
3. Route `/internal-api/` only through trusted network path if possible.
4. Rotate internal API token periodically.
5. Monitor logs for repeated auth failures and tool abuse.
