# Step 10 - Integration Manual QA

너는 `anglangl`의 통합 검증과 수동 QA 문서를 정리하는 Django 개발자다.

이번 단계만 수행하고 완료 후 멈춘다.

## 목표

StudyMaterial 중심 기능이 영상/클립/드라마/공개 탐색/복제/internal API와 함께 동작하는지 검증하고 QA 문서를 갱신한다.

## 주요 작업

- `docs/09_risk_and_test_plan.md`를 읽는다.
- `docs/manual-qa-checklist.md`를 현재 구현 상태에 맞게 갱신한다.
- `docs/manual-qa-execution-log.md`에 새 실행 템플릿이 필요한지 확인한다.
- 자동 테스트를 실행한다.
- 수동 QA가 실제로 필요한 항목과 자동화된 항목을 구분한다.
- 발견한 미해결 이슈는 별도 섹션으로 기록한다.

## 금지 사항

```text
검증 중 발견한 큰 버그를 즉석에서 대규모 수정 금지
수동으로 확인하지 않은 항목을 pass로 기록 금지
실패를 숨기거나 성공으로 보고 금지
```

## 검증

```bash
python manage.py check
python manage.py test study.tests dashboard.tests
find docs -maxdepth 2 -type f | sort
rg -n "StudyMaterial|manual QA|복제|공개|Internal API|MCP" docs
```

## 완료 보고 형식

```text
[Step 10 - Integration Manual QA 완료 보고]

1. 수행한 작업 요약
2. 생성/수정한 파일 목록
3. 실행한 자동 테스트
4. 수동 QA 문서 변경
5. 검증 결과
6. 실패/미확인 항목
7. 다음 단계
```

