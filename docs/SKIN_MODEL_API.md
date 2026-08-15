# Skin Type AI API 명세서

## 1. 개요

사진 한 장을 입력받아 다음 네 가지 피부 타입의 확률을 반환하는 FastAPI
추론 서비스입니다.

- `normal`
- `dry`
- `oily`
- `combination`

이 API의 결과는 **사진 기반 피부 타입 추정**이며 의료 진단이나 피부 수분량,
피지량, 피부 질환, 건강 점수 또는 피부 나이 측정 결과가 아닙니다.

| 항목 | 값 |
|---|---|
| API 버전 | `0.1.0` |
| 운영 모델 | `outputs/additional_run/checkpoints/best_model.pt` |
| 권장 모델 식별자 | `skin-type-efficientnet-b0-additional-v1` |
| 내부 주소 | `http://127.0.0.1:8000` |
| 운영 예시 주소 | `https://ai.example.com` |
| Content-Type | 요청별 설명 참조 |
| 인증 | 애플리케이션 내장 인증 없음 |

인증, 접근 제어, HTTPS 및 요청 빈도 제한은 Nginx, API Gateway 또는 상위
백엔드에서 적용해야 합니다.

## 2. 배포 환경변수

| 이름 | 필수 | 기본값 | 설명 |
|---|---:|---|---|
| `MODEL_CHECKPOINT` | 권장 | `outputs/checkpoints/best_model.pt` | 체크포인트 절대 또는 상대 경로 |
| `MODEL_VERSION` | 선택 | `skin-type-efficientnet-b0-v1` | 모델 식별 문자열 |
| `CONFIDENCE_THRESHOLD` | 선택 | `0.55` | 판단 보류 기준 |
| `MAX_UPLOAD_BYTES` | 선택 | `10485760` | 최대 이미지 크기, 기본 10 MiB |

운영 환경 권장값:

```ini
MODEL_CHECKPOINT=/home/hnvlab/apps/Hack2026/outputs/additional_run/checkpoints/best_model.pt
MODEL_VERSION=skin-type-efficientnet-b0-additional-v1
CONFIDENCE_THRESHOLD=0.55
MAX_UPLOAD_BYTES=10485760
```

## 3. 공통 규칙

- 모든 응답 본문은 JSON입니다.
- 예측 요청은 `multipart/form-data`를 사용합니다.
- 이미지 필드 이름은 반드시 `file`입니다.
- 허용 MIME 타입은 `image/jpeg`, `image/png`, `image/webp`,
  `image/bmp`입니다.
- 선언한 MIME 타입과 실제 이미지 포맷이 다르면 요청을 거부합니다.
- 모델은 첫 예측 요청에서 지연 로딩되므로 첫 요청이 이후 요청보다 느릴 수 있습니다.
- 확률은 Softmax 결과이며 네 클래스 확률의 합은 부동소수점 오차 범위에서 1입니다.
- `processing_time_ms`는 API 프로세스 내부 처리 시간이며 Nginx 및 네트워크
  지연은 포함하지 않습니다.

## 4. Health Check

### `GET /health`

프로세스와 체크포인트 준비 상태를 반환합니다.

요청 본문은 없습니다.

```bash
curl https://ai.example.com/health
```

### 성공 응답

HTTP `200 OK`

```json
{
  "status": "ok",
  "ready": true,
  "model_version": "skin-type-efficientnet-b0-additional-v1"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `status` | string | 프로세스 상태. 현재 `ok` |
| `ready` | boolean | 체크포인트 파일이 존재하거나 모델이 로딩됐는지 여부 |
| `model_version` | string | 현재 모델 식별자 |

`ready: true`는 체크포인트 파일의 존재를 의미합니다. 실제 모델 역직렬화와 GPU
추론까지 확인하려면 배포 직후 테스트 이미지로 `POST /predict`를 한 번 호출해야
합니다.

## 5. 피부 타입 추정

### `POST /predict`

#### 요청

Content-Type:

```text
multipart/form-data
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `file` | binary | 예 | JPEG, PNG, WebP 또는 BMP 이미지 |

기본 최대 파일 크기는 10 MiB입니다.

```bash
curl -X POST https://ai.example.com/predict \
  -F "file=@sample.jpg;type=image/jpeg"
```

### 예측 확정 응답

HTTP `200 OK`

```json
{
  "predicted_class": "oily",
  "probabilities": {
    "normal": 0.08,
    "dry": 0.04,
    "oily": 0.78,
    "combination": 0.10
  },
  "confidence": 0.78,
  "needs_review": false,
  "message": "사진 기반 피부 타입 추정 결과입니다.",
  "model_version": "skin-type-efficientnet-b0-additional-v1",
  "processing_time_ms": 42.1
}
```

### 판단 보류 응답

최대 확률이 `CONFIDENCE_THRESHOLD`보다 낮으면 특정 타입을 확정하지 않습니다.

HTTP `200 OK`

```json
{
  "predicted_class": null,
  "probabilities": {
    "normal": 0.3341,
    "dry": 0.1713,
    "oily": 0.1813,
    "combination": 0.3133
  },
  "confidence": 0.3341,
  "needs_review": true,
  "message": "사진만으로 피부 타입을 명확하게 판단하기 어렵습니다.",
  "model_version": "skin-type-efficientnet-b0-additional-v1",
  "processing_time_ms": 47.8
}
```

| 필드 | 타입 | Nullable | 설명 |
|---|---|---:|---|
| `predicted_class` | string | 예 | 확정 클래스. 판단 보류 시 `null` |
| `probabilities` | object | 아니요 | 네 클래스별 확률 |
| `confidence` | number | 아니요 | 가장 높은 클래스 확률 |
| `needs_review` | boolean | 아니요 | 임계값 미만 판단 보류 여부 |
| `message` | string | 아니요 | 사용자 표시용 비진단 안내문 |
| `model_version` | string | 아니요 | 응답을 생성한 모델 식별자 |
| `processing_time_ms` | number | 아니요 | 서버 내부 처리 시간(ms) |

클라이언트는 `needs_review`를 우선 확인해야 합니다. `true`일 때
`probabilities`에서 가장 큰 클래스를 임의로 확정 결과로 저장해서는 안 됩니다.

## 6. 오류 응답

FastAPI 오류 형식:

```json
{
  "detail": "오류 설명"
}
```

| HTTP 상태 | 발생 조건 | detail 예시 |
|---:|---|---|
| `400` | 손상된 파일, 실제 포맷과 MIME 불일치 | `Corrupted or invalid image` |
| `413` | `MAX_UPLOAD_BYTES` 초과 | `Uploaded file is too large` |
| `415` | 허용하지 않는 MIME 타입 | `Unsupported image MIME type` |
| `422` | `file` 필드 누락 등 요청 검증 실패 | FastAPI 검증 오류 배열 |
| `503` | 체크포인트 파일 없음 | `Model checkpoint is not available` |

클라이언트 권장 처리:

- `400/415/422`: 사용자에게 지원되는 이미지로 다시 업로드하도록 안내
- `413`: 파일 크기를 줄인 후 재요청
- `503`: 사용자 오류로 표시하지 말고 서버 장애로 처리
- 연결 실패 및 `5xx`: 제한된 횟수의 지수 백오프 재시도 적용

## 7. Nginx 연결

### 별도 서브도메인

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_connect_timeout 10s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
    client_max_body_size 10M;
}
```

### 기존 도메인의 하위 경로

외부 주소가 `https://example.com/skin-ai/`인 경우:

```nginx
location /skin-ai/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_read_timeout 60s;
    client_max_body_size 10M;
}
```

하위 경로 구성에서는 `proxy_pass` URL 끝의 슬래시가 필요합니다.

## 8. Spring Boot 호출 예시

응답 DTO:

```java
public record SkinTypeResponse(
    @JsonProperty("predicted_class")
    String predictedClass,

    Map<String, Double> probabilities,
    double confidence,

    @JsonProperty("needs_review")
    boolean needsReview,

    String message,

    @JsonProperty("model_version")
    String modelVersion,

    @JsonProperty("processing_time_ms")
    double processingTimeMs
) {}
```

`RestClient` 요청:

```java
RestClient client = RestClient.builder()
    .baseUrl("https://ai.example.com")
    .build();

MultipartBodyBuilder body = new MultipartBodyBuilder();
body.part("file", new ByteArrayResource(imageBytes) {
    @Override
    public String getFilename() {
        return "skin.jpg";
    }
}).contentType(MediaType.IMAGE_JPEG);

SkinTypeResponse response = client.post()
    .uri("/predict")
    .contentType(MediaType.MULTIPART_FORM_DATA)
    .body(body.build())
    .retrieve()
    .body(SkinTypeResponse.class);

if (response != null && response.needsReview()) {
    // 확정 타입으로 저장하지 않고 사용자에게 판단 보류 안내
}
```

권장 timeout:

- 연결 timeout: 5~10초
- 응답 timeout: 60초
- 첫 요청은 모델 지연 로딩으로 더 오래 걸릴 수 있으므로 배포 직후 warm-up 권장

## 9. OpenAPI

루트 경로로 배포할 경우:

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI JSON: `/openapi.json`

운영 환경에서 문서 엔드포인트를 외부에 공개하지 않으려면 Nginx에서 접근을
제한하거나 FastAPI 설정에서 비활성화해야 합니다.

## 10. 보안 및 개인정보

- 얼굴/피부 사진은 개인정보로 취급해야 합니다.
- 요청 원본과 전체 multipart body를 로그에 기록하지 않습니다.
- 추론 후 원본 이미지를 저장하지 않는 방식을 권장합니다.
- Nginx에서 HTTPS, 인증, 요청 빈도 제한과 본문 크기 제한을 적용합니다.
- 서비스 UI와 API 소비자는 결과를 의료 진단으로 표현하면 안 됩니다.
- `needs_review: true` 결과를 특정 피부 타입으로 강제 변환하면 안 됩니다.


---

# 부록 A. 실행 가이드 (원본 API_USAGE.md)

```bash
MODEL_CHECKPOINT=outputs/checkpoints/best_model.pt \
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
```

- `GET /health` 프로세스 상태와 체크포인트 준비 여부
- `POST /predict` `multipart/form-data`의 `file` 필드
- 허용 MIME: JPEG, PNG, WebP, BMP / 기본 최대 10 MiB
- 손상 이미지·MIME 불일치·크기 초과는 각각 400, 415, 413

```bash
curl -X POST https://hack26-5.syu-likelion.org/predict \
  -F "file=@sample.jpg;type=image/jpeg"
```

---

# 부록 B. 바름 적용 검토 (2026-08-15 실측)

배포 주소 `https://hack26-5.syu-likelion.org/` 로 실제 호출해 판단한 결과.

## 결론 — **주 신호로 쓸 수 없다. 보조로만, 그것도 조건부.**

## 1. 판단 보류가 100%다

얼굴 사진 6장 + 대조군(풍경) 1장, 총 7장 전부 `needs_review: true` / `predicted_class: null`.

| 항목 | 값 |
|---|---|
| needs_review 비율 | **7/7 (100%)** |
| confidence 중앙값 | **0.32** (임계값 0.55) |
| 응답 시간 중앙값 | 0.38초 |

4클래스라 무작위 기대값이 0.25인데 중앙값이 0.32다. Macro F1 0.37도 같은 얘기를 한다.
**임계값을 낮춰서 억지로 확정시키면 안 된다** — 명세도 `needs_review: true`일 때
최대 확률 클래스를 결과로 저장하지 말라고 명시하고 있다.

대조군으로 넣은 **풍경 사진도 `normal` 0.30**을 반환했다. 얼굴 여부를 판별하지 않으므로
사용자가 엉뚱한 사진을 올려도 그럴듯한 확률이 나온다.

## 2. 출력이 화면이 필요한 것과 다르다

| | |
|---|---|
| 이 API | 피부 **타입** — normal / dry / oily / combination |
| 화면 4·12가 필요한 것 | 피부 **상태** 한 줄 — "턱 주변에 트러블이 보여요" |

타입과 상태는 다른 축이다. `dry` → "건조해 보여요" 정도는 옮길 수 있지만,
`docs/PLAN.md`가 정의한 셀카 판독 항목(건조·유분·**홍조**·**트러블**) 중
홍조와 트러블은 이 모델이 아예 다루지 않는다.

## 3. 배포된 모델이 명세와 다르다

명세는 운영 모델을 `skin-type-efficientnet-b0-additional-v1`로 적었는데
`/health`가 돌려주는 값은 `skin-type-efficientnet-b0-v1`이다.
**구 체크포인트가 떠 있다.** 위 수치는 그 상태에서 잰 것이다.

## 4. 그래서 어떻게 쓰나

**셀카 판독은 GPT-4o Vision으로 간다.** `CLAUDE.md` 스택도 원래 그렇게 적혀 있고,
상태 한 줄(건조·유분·홍조·트러블)을 자연어로 뽑는 건 그쪽이 맞다.

이 API는 **보조 신호**로만 쓴다. 붙인다면 이 조건으로:

- `needs_review: true`면 **버린다.** 확률만 보고 타입을 확정하지 않는다
- `false`이고 `dry` 또는 `oily`일 때만 루틴 프롬프트에 한 줄 더한다
  ("사진상 건조해 보여요" 정도, 진단 표현 금지 — 원칙 3)
- 호출 실패·타임아웃은 무시하고 진행한다. 셀카는 원래 보조 신호라
  없어도 날씨와 화장대만으로 루틴이 나온다(`routine.build_prompt`가 `skin=None`을 처리한다)

**현재 상태(판단 보류 100%)로는 붙여도 화면에 아무것도 안 나온다.**
모델이 개선돼 confidence가 올라오면 그때 켜는 스위치 정도로 두는 게 맞다.
