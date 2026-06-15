# 09. Risk 및 Test Plan

## 주요 리스크

```text
권한 리스크
  private StudyMaterial, Clip, MasterVideo가 다른 사용자에게 노출될 수 있다.

저작권/원본 노출 리스크
  공개 자료가 source_url, playback link, 내부 파일 경로를 과하게 노출할 수 있다.

생성 품질 리스크
  자막이 없는 source에서 빈약한 자료가 생성될 수 있다.

비동기 상태 리스크
  미디어 처리와 AI 생성 작업이 실패했는데 사용자에게 상태가 남지 않을 수 있다.

회귀 리스크
  기존 clips/videos/dramaNlearn 흐름이 StudyMaterial 진입점 변경으로 깨질 수 있다.
```

## 자동 테스트 우선순위

```text
study.tests
  - owner만 private detail 접근 가능
  - public explore 노출
  - clone 결과 private
  - generation history 생성
  - source resolver별 초안 생성

internal_api.tests
  - token 없으면 401/403
  - user header 권한 적용
  - private 자료 owner만 검색
  - public 자료 visibility 정책

clips.tests / videos.tests
  - source detail에서 study create link 유지
  - subtitle 기반 source text 유지

dashboard.tests
  - recent StudyMaterial 표시
  - failed job attention items 유지
```

## 수동 QA

기존 문서를 확장한다.

- `docs/manual-qa-checklist.md`
- `docs/manual-qa-execution-log.md`

추가해야 할 수동 QA 항목:

```text
1. Clip detail에서 쉐도잉 자료 생성
2. MasterVideo subtitle file 기반 자료 생성
3. DramaVideo subtitle track 기반 자료 생성
4. 공개 자료 explore 검색/필터
5. 다른 사용자 clone 후 원본 불변 확인
6. 내부 API study material 검색 확인
7. MCP study material 도구 smoke 확인
```

## 문서 변경 검증

문서만 변경한 경우:

```bash
find docs -maxdepth 2 -type f | sort
rg -n "StudyMaterial|codex_prompts|internal-api|MCP|검증" docs
```

## 코드 변경 검증

코드 변경 시 기본:

```bash
python manage.py check
python manage.py test study.tests
```

schema 변경 시 추가:

```bash
python manage.py makemigrations --check
python manage.py migrate
```

internal API/MCP 변경 시 추가:

```bash
python manage.py test internal_api.tests
python -m compileall internal_api mcp_server
```

