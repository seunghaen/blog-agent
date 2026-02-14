# requirements.md — Google Drive 기반 맛집 블로그 HTML 자동화 (Stage 1~4)

## 0. 목표

Google Drive에 있는 사진 폴더를 읽어서, 식당 정보를 최소한으로 조회하고(최근 2개월 이내 정보만 사용), 사진을 Vision 분석한 뒤, "30대 남자 맛집 블로그" 스타일의 HTML 한 문서를 생성한다.

이번 범위는 Stage 1~4만 구현/검증한다.
- 메일 전송, 배치 전송, 클라우드 스케줄링은 제외

## 1. 입력 (반드시 Google Drive)

### 1.1 입력 폴더 규칙

Google Drive 내 `RestaurantReviews/` 폴더 아래에 다음 규칙의 하위 폴더들이 존재한다.
- 폴더명: `YYYYMMDD_식당명`
- 예: `20260214_스시로쿠`

해당 폴더 안에는 사진 파일이 들어있다.
- 지원 확장자: `.jpg`, `.jpeg`, `.png`, `.webp`
- 하위 폴더가 있어도 재귀적으로 찾아서 처리한다.

### 1.2 출력 폴더 규칙 (Drive 저장)

출력은 입력과 분리된 폴더에 저장한다.
- 출력 루트: `RestaurantReviewsOutputs/`
- 출력 폴더: `RestaurantReviewsOutputs/YYYYMMDD_식당명/`

## 2. 파이프라인 (Stage 1~4)

기본 목표는 Stage 4 최종 결과물(`review.html`, `rules_report.json`)을 안정적으로 생성하는 것이다.
Stage 1~3 산출물은 디버그/문제 추적을 위한 선택 사항으로 저장한다.

### Stage 1 — 폴더 검색/이미지 목록 수집

#### 기능

- Drive에서 `RestaurantReviews/` 아래의 `YYYYMMDD_식당명` 폴더들을 조회한다.
- 처리 대상 폴더 1개를 선택한다.
- 기본값은 가장 최신 날짜 폴더 1개(`--latest 1`)
- 폴더 내부 이미지 파일들을 재귀 수집한다.

#### 산출물 (선택, Drive 저장)

`RestaurantReviewsOutputs/YYYYMMDD_식당명/manifest.json`

`manifest.json` 최소 스키마:

```json
{
  "source_folder_id": "string",
  "source_folder_name": "YYYYMMDD_식당명",
  "visit_date": "YYYYMMDD",
  "restaurant_name": "string",
  "images": [
    { "file_id": "string", "name": "string", "mime_type": "string" }
  ]
}
```

#### 검증 (선택)

- `images` 길이가 0이면 실패(권장) 또는 경고 처리

### Stage 2 — 식당 정보 조회 (최근 60일 이내만 사용)

#### 원칙 (단순화)

- 선택 A (권장): Google Places API 사용
- 선택 B (최소): 식당 정보 조회 생략, 사진 기반으로만 글 생성
- 기본은 A를 목표로 하되, 키가 없거나 실패하면 B로 graceful fallback

#### 기능 (선택 A)

- `restaurant_name`으로 Places 검색 후 1개를 선택해 상세 정보 조회
- 리뷰가 있으면 최근 60일 내 리뷰만 필터링해서 사용
- 최근 리뷰가 0개면 리뷰 관련 문장은 작성하지 않음

#### 산출물 (선택, Drive 저장)

`RestaurantReviewsOutputs/YYYYMMDD_식당명/restaurant.json`

`restaurant.json` 최소 스키마:

```json
{
  "found": true,
  "place_id": "string",
  "name": "string",
  "address": "string",
  "opening_hours": ["string"],
  "rating": 4.2,
  "user_ratings_total": 123,
  "maps_url": "string",
  "website": "string",
  "recent_reviews": [
    { "time": 1700000000, "rating": 5, "text": "string", "relative_time": "string" }
  ],
  "recent_reviews_cutoff_days": 60
}
```

#### 검증 (선택)

- `recent_reviews`가 존재하면 각 `review.time`이 현재 시각 기준 60일 이내여야 함
- 하나라도 위반하면 실패
- `found=false`면 Stage 4에서 식당 정보 박스는 최소 항목만 출력

### Stage 3 — 사진 Vision 분석

#### 원칙 (단순화)

- 사진별로 문장이 아니라 `관찰/추정/주의점` 형태의 JSON 생성
- 메뉴/가격을 단정하지 않음

#### 기능

- 각 이미지에 대해 Vision 분석 수행
- 파싱 실패 시 `_raw`로 저장 가능

#### 산출물 (선택, Drive 저장)

`RestaurantReviewsOutputs/YYYYMMDD_식당명/vision.json`

`vision.json` 최소 스키마:

```json
{
  "images": [
    {
      "file_id": "string",
      "name": "string",
      "analysis": {
        "scene_type": "food|menu|interior|exterior|receipt|other",
        "observations": ["string"],
        "food_guess": ["string (추정)"],
        "ambience_hints": ["string"],
        "bloggable_details": ["string"],
        "warnings": ["string"]
      }
    }
  ]
}
```

#### 검증 (선택)

- 가능하면 `images` 길이가 Stage 1과 동일해야 함
- `analysis` 없이 `_raw`만 있으면 경고(실패 아님)

### Stage 4 — 블로그 HTML 생성

#### 결과물 요구 (중요)

- 출력은 완전한 HTML 문서 1개 (`<head>`, `<body>` 포함)
- "30대 남자 맛집 블로그" 스타일
- 과하게 정리된 보고서 톤 금지(목차, 과한 소제목, 템플릿 티)

#### 금지 요소 (필수)

- `**` (마크다운 강조)
- 이모지
- `<hr>` 또는 구분선 표현
- GIF 사용 (`.gif` 또는 `image/gif`)
- 문장 전체를 큰따옴표로 감싸는 과장형 강조 표현

#### 최근 60일 제약

- 리뷰 기반 문장은 `restaurant.json`의 `recent_reviews`만 근거로 사용
- `recent_reviews`가 비어 있으면 "최근 리뷰에서..." 같은 문구 금지
- 주소/영업시간은 변동 가능하므로 단정형 문장 금지, 정보 박스에 짧게 표기(값이 있을 때만)

#### 산출물 (Drive 저장)

- `RestaurantReviewsOutputs/YYYYMMDD_식당명/review.html`
- `RestaurantReviewsOutputs/YYYYMMDD_식당명/rules_report.json`

`rules_report.json` 최소 스키마:

```json
{
  "passed": true,
  "violations": []
}
```

#### 검증 (자동)

- HTML 생성 후 아래 규칙 검사 통과 필요
- `<html>`, `<head>`, `<body>` 태그 존재
- 금지 요소 문자열/태그/패턴 미포함
- `recent_reviews`가 0개인데 리뷰 언급 키워드가 있으면 실패

## 3. 실행 방식 (간단 CLI)

파이프라인은 로컬에서 실행하되, 입출력은 모두 Drive로 한다.

### 필수 옵션

- `--input-root-id`: Drive의 `RestaurantReviews` 폴더 ID
- `--output-root-id`: Drive의 `RestaurantReviewsOutputs` 폴더 ID

### 실행 예시

최신 폴더 1개 처리:

```bash
python -m src.pipeline --input-root-id XXX --output-root-id YYY --latest 1
```

기본 실행은 `--stage`를 지정하지 않으면 Stage 4까지 일괄 실행하여 최종 output 생성까지 완료한다.

특정 Stage까지만 실행:

```bash
python -m src.pipeline --input-root-id XXX --output-root-id YYY --latest 1 --stage 2
```

### Stage 옵션 정의

- `--stage 1`: `manifest.json` 생성
- `--stage 2`: `restaurant.json` 생성
- `--stage 3`: `vision.json` 생성
- `--stage 4`: `review.html` + `rules_report.json` 생성

## 4. 구현 선택 (최소한)

### Drive 접근 방식

- Google Drive API 사용 (폴더 조회, 파일 목록, 다운로드, 업로드)
- 인증은 OAuth(개발자 로컬) 또는 서비스 계정(가능하면) 중 택1
- 초기 개발은 OAuth로 시작 가능

### 식당 정보 조회

- 기본: Google Places API
- 실패/키 없음: `found=false`로 저장하고 진행(사진 기반 작성)

### Vision 분석

- Gemini Vision 등 외부 API 사용
- 실패 시 `_raw` 저장 후 진행

## 5. 품질 기준 (최소)

- 필수 성공 기준은 최종 output 2개(`review.html`, `rules_report.json`) 생성
- 중간 산출물(`manifest.json`, `restaurant.json`, `vision.json`)은 디버그용으로 선택 생성
- 규칙 위반 시 `rules_report.json`에 위반 사유를 남기고 실패 처리
- "없는 사실 생성 금지"는 최우선 규칙

## 6. 테스트 (최소 2개)

- `test_folder_name_parse`: `YYYYMMDD_식당명` 파싱 테스트
- `test_html_rules`: 금지 요소 탐지 테스트(`**`, 이모지, `<hr>`, gif 등)

## 7. 범위 밖 (이번에 하지 않음)

- 메일 전송
- 여러 폴더 일괄 배치 전송
- 스케줄러/클라우드 배포
