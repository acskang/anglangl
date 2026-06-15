# Step 03 - Generation Template Registry

너는 `anglangl`의 학습 자료 생성 템플릿을 서비스 레이어로 정리하는 Django 개발자다.

이번 단계만 수행하고 완료 후 멈춘다.

## 목표

현재 `study/services.py`에 흩어진 초안 생성 로직을 템플릿 레지스트리 구조로 분리한다.

## 주요 작업

- `docs/04_ai_generation_workflow_design.md`를 읽는다.
- `study/services.py`의 `build_initial_material_content()` 로직을 분석한다.
- `study/templates.py` 또는 `study/services/templates.py` 같은 기존 패턴에 맞는 위치를 정한다.
- `TemplateDefinition` 구조를 만든다.
- 기존 `shadowing_script`, `expressions`, `learning_note` 출력이 유지되도록 한다.
- `suggest_purpose`, `build_material_title`이 템플릿 정의를 활용하게 정리한다.
- 기존 테스트를 보강하거나 새 테스트를 추가한다.

## 금지 사항

```text
LLM 호출 구현 금지
DB 기반 템플릿 관리자 구현 금지
출력 문구 대규모 변경 금지
```

## 검증

```bash
python manage.py check
python manage.py test study.tests
```

## 완료 보고 형식

```text
[Step 03 - Generation Template Registry 완료 보고]

1. 수행한 작업 요약
2. 생성/수정한 파일 목록
3. 템플릿 구조
4. 유지된 기존 동작
5. 실행한 명령어
6. 검증 결과
7. 다음 단계
```

