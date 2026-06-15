# Step 09 - Dashboard and Job Status Unification

너는 `anglangl`의 대시보드와 작업 상태 UX를 정리하는 Django 개발자다.

이번 단계만 수행하고 완료 후 멈춘다.

## 목표

Dashboard가 영상/클립/학습 자료/작업 상태를 학습 자료 생성 흐름 중심으로 보여주도록 정리한다.

## 주요 작업

- `docs/03_information_architecture_design.md`와 `docs/04_ai_generation_workflow_design.md`를 읽는다.
- `dashboard/views.py`와 `templates/dashboard/*`를 확인한다.
- 최근 학습 자료, 실패 작업, 처리 중 작업, 최근 source asset의 우선순위를 조정한다.
- AI 생성 작업 상태가 도입된 경우 `BackgroundJob` 또는 `StudyMaterial.generation_status`를 attention item에 반영한다.
- `templates/dashboard/includes/recent_study_materials.html` 표시 정보를 정리한다.
- dashboard tests를 보강한다.

## 금지 사항

```text
Dashboard 전체 리디자인 금지
BackgroundJob 상태 enum 대규모 변경 금지
기존 미디어 작업 상태 표시 제거 금지
```

## 검증

```bash
python manage.py check
python manage.py test dashboard.tests
```

## 완료 보고 형식

```text
[Step 09 - Dashboard and Job Status Unification 완료 보고]

1. 수행한 작업 요약
2. 생성/수정한 파일 목록
3. Dashboard 표시 변경
4. 실행한 명령어
5. 검증 결과
6. 남은 이슈
```

