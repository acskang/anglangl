# Manual QA Execution Log

## 목적
- [`docs/manual-qa-checklist.md`](./manual-qa-checklist.md)를 실제로 실행한 결과를 날짜별로 기록한다.
- 수동 검증에서 발견한 문제를 추적 가능한 형태로 남긴다.

## 실행 기록 템플릿

### 날짜
- YYYY-MM-DD

### 환경
- SQLite / PostgreSQL
- Django URL:
- 브라우저:
- 계정:

### 1. Study Material 재사용 흐름
- 생성 진입: pass / fail
- 저장: pass / fail
- 라이브러리 확인: pass / fail
- 공개 전환: pass / fail
- 다른 사용자 탐색: pass / fail
- 복제: pass / fail
- 재편집: pass / fail

### 2. DramaNlearn 비동기 상태 UX
- URL 추가: pass / fail
- 상태 폴링: pass / fail
- 실패 처리: pass / fail
- 취소 처리: pass / fail
- 작업 이력: pass / fail

### 3. 인증/권한 확인
- 비로그인 접근 제한: pass / fail
- private 자료 상세 차단: pass / fail
- private 자료 복제 차단: pass / fail
- owner 전용 작업 이력 노출: pass / fail

### 발견 이슈
- 이슈:
- 재현 경로:
- 기대 결과:
- 실제 결과:
- 스크린샷/메모:

### 후속 조치
- 자동 테스트 추가 여부:
- 즉시 수정 필요 여부:
- 다음 작업:
