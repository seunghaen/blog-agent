# API 키/Drive 연동 가이드 (비개발자용)

이 문서는 실주행에 필요한 값(API 키, Drive 폴더 ID, 인증 파일) 관리 방법을 설명합니다.

## 1) 준비물

- Google Drive 입력 폴더 ID
- Google Drive 출력 폴더 ID
- Google 인증 파일(JSON)
- Google Places API 키
- Gemini API 키

## 2) 설정 파일 만들기

1. `config/runtime.example.json` 복사
2. 새 파일명 `config/runtime.local.json`로 저장
3. 아래 항목만 본인 값으로 교체

- `input_root_id`
- `output_root_id`
- `google_credentials_file`
- `storage_mode` (`drive`)
- `google_auth_mode` (`service_account` 권장)

권장:

- API 키는 `runtime.local.json`에 직접 넣지 말고 환경변수로 넣기

## 3) Drive 폴더 ID 찾는 법

Google Drive 폴더를 브라우저로 열었을 때 URL이 아래 형태입니다.

`https://drive.google.com/drive/folders/<폴더ID>`

`<폴더ID>` 부분이 `input_root_id`, `output_root_id` 값입니다.

## 4) 서비스계정 사용 시 필수 작업

서비스계정 JSON 안 `client_email` 값을 확인해서,
입력/출력 Drive 폴더를 그 이메일에 공유해야 합니다.

공유 권한이 없으면 폴더/파일 조회나 생성이 실패합니다.

## 5) API 키 넣기 (권장: 환경변수)

현재 터미널 세션에서만 유효:

```bash
export GOOGLE_PLACES_API_KEY="여기에_키"
export GEMINI_API_KEY="여기에_키"
```

영구 적용(zsh):

```bash
echo 'export GOOGLE_PLACES_API_KEY="여기에_키"' >> ~/.zshrc
echo 'export GEMINI_API_KEY="여기에_키"' >> ~/.zshrc
source ~/.zshrc
```

## 6) 실행 예시

```bash
python3 -m src.pipeline --config-file config/runtime.local.json
```

필요하면 개별 옵션으로 덮어쓸 수 있습니다.

```bash
python3 -m src.pipeline \
  --config-file config/runtime.local.json \
  --latest 1 \
  --stage 4
```

## 7) 보안 주의사항

- `runtime.local.json` 같은 개인 설정 파일은 저장소에 커밋하지 마세요.
- API 키, 인증 JSON 파일을 메신저/이메일로 전달하지 마세요.

