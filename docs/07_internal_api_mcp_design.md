# 07. Internal API 및 MCP 설계

## 목적

ChatGPT/MCP와 내부 자동화가 `anglangl`의 학습 자료를 검색, 열람, 생성 보조할 수 있게 한다.

## 현재 Internal API

```text
GET  /internal-api/clips/search/
GET  /internal-api/clips/<id>/
POST /internal-api/clips/<id>/playback-link/
GET  /internal-api/study/recent/
GET  /internal-api/videos/search/
GET  /internal-api/videos/<id>/
GET  /internal-api/upload-batches/<id>/
```

## 현재 MCP 도구

```text
search_clips
get_clip_detail
get_clip_playback_link
list_recent_study_clips
search_master_videos
get_master_video_detail
get_upload_batch_detail
```

## 권장 추가 API

```text
GET  /internal-api/study-materials/search/
GET  /internal-api/study-materials/<id>/
POST /internal-api/study-materials/draft/
POST /internal-api/study-materials/<id>/clone/
```

## 권장 MCP 도구

```text
search_study_materials(query, material_type, purpose, visibility, limit, offset)
get_study_material_detail(material_id)
draft_study_material(source_type, source_id, material_type, purpose, difficulty)
clone_public_study_material(material_id)
```

## 인증 원칙

- 기존 `Authorization: Bearer <DJANGO_INTERNAL_API_TOKEN>`과 `X-Internal-User-Id` 방식을 유지한다.
- 내부 API는 raw local filesystem path를 반환하지 않는다.
- playback link는 TTL이 있는 signed link만 반환한다.
- private 자료는 owner user id가 일치할 때만 반환한다.

## 응답 설계

```json
{
  "id": 1,
  "title": "Example · 쉐도잉 스크립트",
  "material_type": "shadowing_script",
  "purpose": "shadowing",
  "difficulty": "intermediate",
  "visibility": "private",
  "ownership_label": "내가 만든 자료",
  "source": {
    "source_type": "clip",
    "source_title": "Scene Clip",
    "source_reference": "Clip #10"
  },
  "generated_content": "...",
  "editable_notes": "...",
  "updated_at": "..."
}
```

## 구현 순서

1. serializer 함수 추가
2. 내부 API view/urls 추가
3. permission/visibility 테스트 추가
4. MCP schema/tool 추가
5. README와 docs 업데이트

