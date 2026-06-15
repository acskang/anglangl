# Step 01 - Source Inventory and Baseline

너는 `anglangl`의 Django 코드베이스를 분석하고 후속 구현 기준을 정리하는 시니어 개발자다.

이번 단계만 수행하고 완료 후 멈춘다.

## 목표

현재 source asset과 StudyMaterial 생성 흐름을 코드 기준으로 inventory 문서에 정리한다.

## 주요 작업

- `AGENTS.md`, `docs/00_current_state_entrypoint.md`를 읽는다.
- `videos`, `clips`, `study`, `dramaNlearn`, `movies`, `dashboard`, `internal_api`, `mcp_server` 구조를 확인한다.
- source type별로 어떤 모델/뷰/서비스/템플릿이 연결되는지 정리한다.
- 기존 테스트와 수동 QA 문서를 확인한다.
- 결과를 `docs/source_inventory.md`에 작성한다.

## 금지 사항

```text
코드 동작 변경 금지
schema 변경 금지
참조 외부 프로젝트 수정 금지
대규모 리팩터링 금지
```

## 검증

```bash
find docs -maxdepth 2 -type f | sort
rg -n "MasterVideo|Clip|StudyMaterial|DramaVideo|Internal API|MCP" docs/source_inventory.md
```

## 완료 보고 형식

```text
[Step 01 - Source Inventory and Baseline 완료 보고]

1. 수행한 작업 요약
2. 생성/수정한 파일 목록
3. 확인한 핵심 코드 영역
4. 실행한 명령어
5. 검증 결과
6. 다음 단계
```

