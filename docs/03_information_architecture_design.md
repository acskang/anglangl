# 03. 정보구조 및 화면 설계

## 목적

현재 기능 나열형 화면을 `생성`, `보관`, `탐색`, `소스`, `작업 상태` 중심으로 정리한다.

## 목표 내비게이션

```text
Dashboard
Create
Library
Explore
Sources
Jobs
```

## 화면별 역할

```text
Dashboard
  현재 이어 할 일, 최근 자료, 실패 작업, 최근 소스, 최근 클립을 보여준다.

Create
  사용자가 입력 소스와 자료 유형을 선택하고 생성 초안을 만드는 화면이다.

Library
  내가 만든 자료와 가져온 자료를 저장/정리/재편집하는 화면이다.

Explore
  다른 사용자의 공개 자료를 탐색하고 복제하는 화면이다.

Sources
  MasterVideo, Clip, dramaNlearn, movies, URL source를 찾고 자료 생성으로 연결한다.

Jobs
  장시간 미디어 처리와 AI 생성 작업 상태를 추적한다.
```

## 현재 URL 매핑

```text
/                      landing
/admin/dashboard/      dashboard:home
/videos/               MasterVideo
/clips/                Clip
/study/                Library
/study/explore/        Explore
/study/create/         Create
/jobs/                 BackgroundJob
/dramaNlearn/          legacy/source provider
/movies/               movie source provider
/player/               content discovery/player
```

## 권장 URL 방향

초기에는 기존 URL을 유지하고 내비게이션 라벨과 진입 흐름을 정리한다. 대규모 URL rename은 후순위다.

```text
/study/                Library
/study/explore/        Explore
/study/create/         Create Material
/videos/               Sources > Videos
/clips/                Sources > Clips
/jobs/                 Jobs
```

## Create 화면 구조

```text
1. Source 선택
   - Clip
   - MasterVideo
   - DramaVideo
   - Movie
   - URL
   - Manual

2. Material type 선택
   - 쉐도잉 스크립트
   - 핵심 표현 정리
   - 단어/문장 학습 노트
   - future: 퀴즈, 문법 설명, 리스닝 세트

3. Purpose / difficulty 선택
4. Generate draft
5. Edit draft
6. Save to library
```

## Library 필터

```text
ownership: 내가 만든 자료 / 가져온 자료
material_type
purpose
difficulty
source_type
visibility
sort: updated / created / title
```

## Explore 필터

```text
material_type
purpose
difficulty
source_type
quality_badge
sort: recent / cloned / title
```

## UI 톤

- 한국어를 기본으로 한다.
- 사용자에게 AI가 대신 공부한다는 인상을 주지 않는다.
- "생성", "편집", "저장", "공유", "다시 활용" 동사를 명확히 사용한다.
- 검정 배경, 보라/녹색 포인트, 흰색/회색 텍스트 방향을 유지한다.
- 생성 결과는 채팅 버블보다 문서형/카드형 구조로 보여준다.

