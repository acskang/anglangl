# Step 06 - Share Clone Permissions

너는 `anglangl`의 공개/복제 권한을 강화하는 Django 개발자다.

이번 단계만 수행하고 완료 후 멈춘다.

## 목표

공개 자료 탐색과 복제 흐름에서 private 자료 노출, 원본 변경, 과도한 source 정보 노출을 방지한다.

## 주요 작업

- `docs/06_share_reuse_design.md`를 읽는다.
- `StudyMaterialPublicDetailView`, `StudyMaterialCloneView`, `StudyMaterialVisibilityToggleView`를 확인한다.
- private 자료 direct access, non-owner clone, anonymous clone을 테스트한다.
- clone 결과가 항상 private인지 테스트한다.
- clone 후 원본 `generated_content`, `editable_notes`, `visibility`가 바뀌지 않는지 테스트한다.
- public detail에서 source URL 노출 정책을 확인하고 필요 시 템플릿을 조정한다.
- 필요하다면 `clone_count_cache` 갱신을 구현한다.

## 금지 사항

```text
private 자료 공개 금지
owner 아닌 사용자의 edit/delete 권한 부여 금지
internal playback link 공개 화면 노출 금지
```

## 검증

```bash
python manage.py check
python manage.py test study.tests
```

## 완료 보고 형식

```text
[Step 06 - Share Clone Permissions 완료 보고]

1. 수행한 작업 요약
2. 생성/수정한 파일 목록
3. 권한 정책
4. 추가/수정 테스트
5. 실행한 명령어
6. 검증 결과
7. 남은 리스크
```

