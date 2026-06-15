# 01. anglangl 개요

## 목적

`anglangl`은 사용자가 영어 학습 자료를 직접 만들고, 저장하고, 공유하고, 다시 활용할 수 있게 하는 Django 기반 웹 서비스다.

```text
기존 누적 기능: 영상 등록, 클립 생성, 드라마/영화 플레이어, 학습 이력, 내부 API
목표 제품: AI · LLM 기반 영어 학습 자료 생성 및 공유 플랫폼
```

## 제품 방향

`anglangl`의 중심은 `미디어 재생`이 아니라 `학습 자료 자산화`다. 영상과 클립은 최종 목적이 아니라 자료 생성의 입력이다.

```text
Source Asset
→ Generation Input
→ Editable StudyMaterial
→ Personal Library
→ Public Explore
→ Clone / Reuse
```

## 핵심 사용자 과업

- YouTube, 업로드 영상, 드라마, 영화, URL, 수동 입력에서 학습 자료를 만든다.
- 쉐도잉 스크립트, 핵심 표현, 단어/문장 노트 같은 자료 유형을 선택한다.
- 생성된 초안을 수정하고 저장한다.
- 내 라이브러리에서 목적, 난이도, 소스, 소유 상태로 정리한다.
- 공개 자료를 탐색하고 내 라이브러리로 복제한다.
- 같은 소스를 다른 목적이나 난이도로 다시 생성한다.

## 현재 앱별 역할

```text
videos
  MasterVideo를 관리한다. YouTube/업로드/드라마 bridge를 source asset으로 제공한다.

clips
  MasterVideo 또는 업로드 파일에서 Clip을 만든다. 자막, 시간 구간, 이미지, 앨범을 source context로 제공한다.

study
  StudyMaterial을 관리한다. 현재 제품 정체성의 중심 앱이다.

dashboard
  최근 영상, 클립, 작업, 학습 자료를 모아 사용자의 현재 작업 상태를 보여준다.

workers
  BackgroundJob으로 장시간 작업 상태를 추적한다.

internal_api / mcp_server
  ChatGPT/MCP 연동을 위한 내부 검색, 상세, playback 도구를 제공한다.

dramaNlearn / movies
  외부 콘텐츠 탐색과 플레이어 흐름을 제공한다. 장기적으로는 source provider로 정리한다.
```

## 목표 아키텍처

```text
Source Provider Layer
├── MasterVideo
├── Clip
├── DramaVideo
├── Movie
├── URL
└── Manual Input

Generation Layer
├── Template Registry
├── Source Resolver
├── Prompt Builder
├── LLM Client
├── Draft Parser
└── Generation Snapshot

Study Asset Layer
├── StudyMaterial
├── StudyMaterialGeneration
├── Visibility
├── Clone lineage
└── Library filters

Discovery Layer
├── Public Explore
├── Search / filter
├── Clone
└── Collections (future)
```

## 우선 구현 범위

1. 현재 `StudyMaterial` 모델과 화면을 보강한다.
2. 생성 템플릿을 코드 상수/서비스로 분리한다.
3. LLM 호출은 서비스 레이어 뒤에 두고, 실패 시 기존 deterministic draft를 fallback으로 유지한다.
4. 공개/복제 권한과 원본 노출 정책을 명확히 한다.
5. 내부 API/MCP에 학습 자료 검색/상세/생성 초안 도구를 추가한다.

