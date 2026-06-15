# Step 08 - Internal API and MCP Materials

너는 `anglangl`의 내부 API와 MCP 서버를 확장하는 Django/Python 개발자다.

이번 단계만 수행하고 완료 후 멈춘다.

## 목표

StudyMaterial 검색/상세/초안 생성을 내부 API와 MCP 도구로 제공한다.

## 주요 작업

- `docs/07_internal_api_mcp_design.md`를 읽는다.
- `internal_api/views.py`, `internal_api/serializers.py`, `internal_api/urls.py`를 확인한다.
- `mcp_server/server.py`, `mcp_server/schemas.py`, `mcp_server/django_client.py`를 확인한다.
- 내부 API 추가:
  - `GET /internal-api/study-materials/search/`
  - `GET /internal-api/study-materials/<id>/`
  - 필요 시 `POST /internal-api/study-materials/draft/`
- MCP 도구 추가:
  - `search_study_materials`
  - `get_study_material_detail`
  - 필요 시 `draft_study_material`
- private/public 권한 정책을 테스트한다.
- raw filesystem path를 반환하지 않는다.

## 금지 사항

```text
내부 인증 우회 금지
public/private 정책 약화 금지
playback 파일 직접 경로 반환 금지
MCP 도구에서 DB 직접 접근 금지
```

## 검증

```bash
python manage.py check
python manage.py test internal_api.tests
python -m compileall internal_api mcp_server
```

## 완료 보고 형식

```text
[Step 08 - Internal API and MCP Materials 완료 보고]

1. 수행한 작업 요약
2. 생성/수정한 파일 목록
3. 추가 endpoint/tool
4. 권한 검증 내용
5. 실행한 명령어
6. 검증 결과
7. 남은 이슈
```

