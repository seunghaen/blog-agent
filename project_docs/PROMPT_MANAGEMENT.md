# 프롬프트 관리 가이드 (비개발자용)

이 문서는 블로그 말투/문장 스타일을 코드 수정 없이 바꾸는 방법만 설명합니다.

## 1) 수정할 파일

- 기본 예시 파일: `config/prompts.example.json`
- 실제 사용 파일(권장): `config/prompts.local.json`

권장 절차:

1. `config/prompts.example.json`을 복사해서 `config/prompts.local.json` 생성
2. `config/prompts.local.json`의 문구만 수정
3. 실행 시 `--prompt-file config/prompts.local.json` 사용

## 2) 필드 설명

- `vision_prompt`
  - 사진 분석용 AI 지시문입니다.
  - JSON 형식 요구를 유지해야 파이프라인이 안정적으로 동작합니다.
- `title_template`
  - HTML `<title>`에 들어갈 제목 형식입니다.
- `intro_template`
  - 본문 첫 문장 템플릿입니다.
- `scene_summary_template`
  - 사진 장면 요약 문장 템플릿입니다.
- `observations_prefix`
  - 관찰 포인트 문장 앞부분입니다.
- `food_guess_prefix`
  - 음식 추정 문장 앞부분입니다.
- `recent_review_template`
  - 최근 60일 리뷰가 있을 때만 들어가는 문장 템플릿입니다.
- `fallback_paragraph`
  - 정보가 적을 때 들어가는 기본 문장입니다.
- `missing_info_line`
  - 식당 정보 조회 실패 시 정보 박스에 표시되는 문장입니다.

## 3) 템플릿 변수

아래 변수는 그대로 사용해야 값이 자동으로 치환됩니다.

- `{restaurant_name}`
- `{visit_date}`
- `{image_count}`
- `{scene_text}`
- `{review_count}`
- `{summary}`

예:

- `"{restaurant_name} 방문 기록"`
- `"{visit_date} 사진 {image_count}장을 기준으로 정리했습니다."`

## 4) 작성 시 주의사항

아래 요소는 규칙 검사에서 실패할 수 있으므로 사용하지 마세요.

- `**`
- 이모지
- `<hr>`
- `.gif`, `image/gif`
- 문장 전체 큰따옴표 강조

## 5) 실행 예시

```bash
python3 -m src.pipeline \
  --config-file config/runtime.local.json \
  --prompt-file config/prompts.local.json
```

