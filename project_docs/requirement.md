# requirements.md — Google Drive 기반 맛집 블로그 HTML 자동화 (Stage 1~4)

## 0. 목표

Google Drive에 있는 사진 폴더를 읽어서, 식당 정보를 최소한으로 조회하고(최근 2개월 이내 정보만 사용), 사진을 Vision 분석한 뒤, “30대 남자 맛집 블로그” 스타일의 **HTML 한 문서**를 생성한다.

이번 범위는 **1~4만 구현/검증**한다.  
(메일 전송, 배치 전송, 클라우드 스케줄링은 제외)

---

## 1. 입력(반드시 Google Drive)

### 1.1 입력 폴더 규칙

Google Drive 내 `RestaurantReviews/` 폴더 아래에 다음 규칙의 하위 폴더들이 존재한다.

- 폴더명: `YYYYMMDD_식당명`
  - 예: `20260214_스시로쿠`

해당 폴더 안에는 사진 파일이 들어있다.

- 지원 확장자: `.jpg .jpeg .png .webp`
- 하위 폴더가 있어도 재귀적으로 찾아서 처리한다.

### 1.2 출력 폴더 규칙(Drive에 저장)

출력은 입력과 분리된 폴더에 저장한다.

- 출력 루트: `RestaurantReviewsOutputs/`
- 출력 폴더: `RestaurantReviewsOutputs/YYYYMMDD_식당명/`

---

## 2. 파이프라인(Stage 1~4)

각 Stage는 “눈으로 확인 가능한 중간 산출물”을 Drive에 저장한다.  
중간 산출물이 있으면, 단계별로 잘 됐는지 바로 검증 가능하다.

### Stage 1 — 폴더 검색/이미지 목록 수집

#### 기능

- Drive에서 `RestaurantReviews/` 아래의 `YYYYMMDD_식당명` 폴더들을 조회한다.
- 처리 대상 폴더 1개를 선택한다.
  - 기본은 가장 최신 날짜 폴더 1개(`--latest 1`)
- 폴더 내부 이미지 파일들을 수집한다(재귀).

#### 산출물(Drive 저장)

`RestaurantReviewsOutputs/YYYYMMDD_식당명/manifest.json`

`manifest.json` 최소 스키마:

```json
{
  "source_folder_id": "string",
  "source_folder_name": "YYYYMMDD_식당명",
  "visit_date": "YYYYMMDD",
  "restaurant_name": "string",
  "images": [{ "file_id": "string", "name": "string", "mime_type": "string" }]
}
```
