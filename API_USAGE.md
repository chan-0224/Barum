# API 사용 가이드

이 API는 의료 진단이 아닌 사진 기반 피부 타입 추정만 제공합니다.

## 실행과 엔드포인트

```bash
MODEL_CHECKPOINT=outputs/checkpoints/best_model.pt \
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
```

- `GET /health`: 프로세스 상태와 체크포인트 준비 여부
- `POST /predict`: `multipart/form-data`의 `file` 필드
- 허용 MIME: JPEG, PNG, WebP, BMP
- 기본 최대 크기: 10 MiB (`MAX_UPLOAD_BYTES`로 변경)
- 손상 이미지, MIME 불일치, 크기 초과는 각각 400, 415, 413 응답

```bash
curl -X POST http://localhost:8000/predict \
  -F "file=@sample.jpg;type=image/jpeg"
```

응답 예시(수치는 형식 설명용이며 모델 성능 수치가 아님):

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
  "model_version": "skin-type-efficientnet-b0-v1",
  "processing_time_ms": 42.1
}
```

0.55 미만이면 `predicted_class`는 `null`, `needs_review`는 `true`가 됩니다. Spring은 이 경우 특정 타입으로 저장하거나 사용자에게 확정적으로 표시하지 않아야 합니다.

## Spring Boot 호출 예시

Spring Framework 6의 `RestClient` 예시입니다.

```java
record SkinTypeResponse(
    String predicted_class,
    Map<String, Double> probabilities,
    double confidence,
    boolean needs_review,
    String message,
    String model_version,
    double processing_time_ms
) {}

RestClient client = RestClient.builder()
    .baseUrl("http://skin-type-ai:8000")
    .build();

MultipartBodyBuilder body = new MultipartBodyBuilder();
body.part("file", new ByteArrayResource(imageBytes) {
    @Override public String getFilename() { return "skin.jpg"; }
}).contentType(MediaType.IMAGE_JPEG);

SkinTypeResponse result = client.post()
    .uri("/predict")
    .contentType(MediaType.MULTIPART_FORM_DATA)
    .body(body.build())
    .retrieve()
    .body(SkinTypeResponse.class);
```

연결/응답 timeout, 4xx/5xx 매핑, 재시도 제한, 업로드 크기 제한을 Spring 측에도 설정하세요. 사진 원본과 추론 로그에는 개인정보 보존 정책을 적용하고, 불필요하면 원본을 저장하지 않는 방식을 권장합니다.

