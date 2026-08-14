# 바름 API 명세

**1부 — 프론트 ↔ Spring** (프론트·백엔드 공용) / **2부 — DB 스키마** / **3부 — Spring ↔ FastAPI**

프론트는 Spring만 호출한다. 단 루틴 스트리밍(SSE)만 프론트가 FastAPI를 직접 호출한다.

> AI 서버 연동 항목(1 날씨 · 6 OCR · 8 루틴 · 9 기록 저장)은 구교승 명세 확정 후 조정된다. 나머지는 확정.

---

## 공통

**Base**: Spring `/api/v1`, FastAPI `/internal/v1`

**인증**: Supabase 익명 세션 JWT를 `Authorization: Bearer <token>`으로 전달.
프론트는 진입 시 `signInAnonymously()` 호출. Spring은 Supabase 공개키(JWKS)로 검증 후 `sub`에서 `user_id` 추출.

**포맷**: ISO 8601 KST / 날짜 키 `YYYY-MM-DD` / 생성 201, 삭제 204

**에러**

```json
{ "code": "PRODUCT_NOT_FOUND", "message": "제품을 찾을 수 없습니다." }
```

| code | HTTP | 상황 | 프론트 처리 |
|---|---|---|---|
| `UNAUTHORIZED` | 401 | 토큰 없음/만료 | 익명 세션 재발급 후 재시도 |
| `VALIDATION_ERROR` | 400 | 파라미터 오류 | 입력 안내 |
| `PRODUCT_NOT_FOUND` | 404 | 제품 없음 | 목록 새로고침 |
| `EMPTY_VANITY` | 409 | 보유 제품 0개인데 루틴 요청 | 화장대 탭 유도 |
| `OCR_NO_TEXT` | 422 | 전성분표 인식 실패 | 인식 실패 화면 |
| `AI_TIMEOUT` | 504 | AI 응답 초과 | 재시도 버튼 |
| `EXTERNAL_API_ERROR` | 502 | 날씨 API 실패 | 해당 영역만 비움 |

**enum**
- `category`: `CLEANSER` `TONER` `SERUM` `CREAM` `SUNSCREEN`
- `source`: `SAMPLE` `CATALOG` `OCR`
- `conflict.level`: `AVOID`(오늘 같이 바르지 않기) `GOOD`(함께 쓰면 좋음) — **2단계뿐이다.** 바름은 아침 루틴만 제시하므로 "시간대를 나눠 쓰세요"(구 `CAUTION`)가 성립하지 않아 폐지했다

---

# 1부. 프론트 ↔ Spring

## 1. 날씨 조회 — 화면 1

```
GET /weather?lat=37.5665&lon=126.9780
```

`lat`/`lon` 생략 시 서울 좌표 폴백.

```json
{
  "temp": 29.0, "humidity": 38.0, "pm10": 22, "pm25": 14,
  "regionLabel": "서울",
  "summary": "건조하고 미세먼지 보통이에요",
  "observedAt": "2026-08-11T08:00:00+09:00"
}
```

## 2. 카탈로그 검색 — 화면 8

```
GET /catalog/products?q=토너&category=TONER&page=0&size=20
```

`q` 생략 시 `id` 오름차순 목록(별도 rank 컬럼 없음).

```json
{
  "items": [{
    "catalogId": 101,
    "brand": "브랜드명",
    "name": "제품명",
    "category": "SERUM",
    "imageUrl": "https://...",
    "keyIngredients": ["나이아신아마이드", "판테놀"]
  }],
  "page": 0, "size": 20, "totalElements": 87
}
```

`keyIngredients`는 **베이스·용매·점증제 계열을 제외하고** `position` 앞쪽 기준 최대 3개.

전성분표는 함량 순이라 그냥 앞 3개를 뽑으면 모든 제품이 `정제수 · 글리세린 · 부틸렌글라이콜`로 똑같아진다. 제외 목록은 `key_ingredient_excluded` 테이블에 있고, Spring은 미리 만들어 둔 뷰를 그대로 조회하면 된다 (제외 로직을 Java에 넣지 말 것 — 목록이 바뀌면 재배포해야 한다):

```sql
select std_name from catalog_key_ingredients
 where catalog_id = ? and rank <= 3
 order by rank;
```

정의는 `barum-be/schema/key_ingredients.sql`. **이 제외는 화면 표시용일 뿐이고, 성분 충돌 판정은 제외 없이 전체 성분을 본다.**

## 3. 내 화장대 목록 — 화면 6

```
GET /products
```

```json
{
  "isSample": true,
  "items": [{
    "productId": "uuid",
    "brand": "브랜드명",
    "name": "약산성 젤 클렌저",
    "category": "CLEANSER",
    "imageUrl": "https://...",
    "source": "SAMPLE",
    "keyIngredients": ["하이알루로닉애씨드"],
    "createdAt": "2026-08-11T09:12:00+09:00"
  }]
}
```

`isSample`: 보유 제품이 전부 `source = SAMPLE`이면 true → 체험용 배지 표시.

## 4. 제품 등록 — 화면 8 / 10

```
POST /products
```

두 경로가 같은 엔드포인트를 쓴다. 둘 중 하나만 채워 보낸다.

**(a) 카탈로그 선택**
```json
{ "catalogIds": [101, 205, 310] }
```

**(b) OCR 결과** — 6번 응답을 그대로 전달
```json
{
  "ocrProduct": {
    "alias": "직구 세럼",
    "ingredients": [
      { "standardName": "정제수", "matched": true },
      { "rawName": "부틸렌글리이콜", "matched": false }
    ]
  }
}
```

**201**
```json
{ "added": 3, "sampleCleared": true, "items": [{ "productId": "uuid", "name": "제품명" }] }
```

**서버 규칙**: 등록 시점에 화장대가 샘플 상태면 샘플 전체 삭제 후 등록. `sampleCleared: true` 반환 → 프론트가 토스트 표시.

## 5. 업로드 URL 발급 — 화면 2 / 9

```
POST /uploads
{ "purpose": "OCR" }     // OCR | SELFIE
```

```json
{
  "uploadUrl": "https://xxxx.supabase.co/storage/v1/object/upload/sign/labels/{userId}/{uuid}.jpg?token=...",
  "bucket": "labels",
  "storagePath": "{userId}/{uuid}.jpg",
  "expiresIn": 300
}
```

**`uploadUrl`은 절대 URL이다.** 프론트가 Storage 베이스 주소를 알 필요가 없다.
그대로 `PUT` 하면 된다 — 헤더는 `Content-Type: image/jpeg` 하나면 되고 인증 헤더는 붙이지 않는다(토큰이 URL에 들어 있다).

```js
await fetch(uploadUrl, { method: "PUT", headers: { "Content-Type": file.type }, body: file });
```

업로드 후 **`storagePath`** 를 다음 요청(6 인식 / 8 루틴 / 9 기록 저장)에 넘긴다. `uploadUrl`은 다시 쓰지 않는다.

**경로 규칙**: 용도는 **버킷**으로 나눈다 — OCR은 `labels`, 셀카는 `selfies`. 둘 다 비공개.
경로는 `{userId}/{파일명}` — OCR `{userId}/{uuid}.jpg`, 셀카 `{userId}/{date}.jpg`.

> Storage 정책이 `(storage.foldername(name))[1] = auth.uid()`라 **첫 폴더가 반드시 유저 ID여야 한다.**
> `ocr/{userId}/...` 처럼 앞에 용도를 두면 업로드가 거부된다(`barum-be/schema/core.sql`).

## 6. 전성분표 인식 — 화면 9·10

```
POST /products/ocr
{ "storagePath": "...", "alias": "직구 세럼" }
```

```json
{
  "alias": "직구 세럼",
  "ingredients": [
    { "standardName": "정제수", "matched": true },
    { "rawName": "부틸렌글리이콜", "matched": false }
  ],
  "matchedCount": 1, "totalCount": 2
}
```

**서버에 저장하지 않는다.** 프론트가 응답을 들고 있다가 "저장" 시 4-(b)로 전송. "다시 촬영"이면 상태만 버린다.
`matched: false`는 표준 성분 매칭 실패 → `rawName`을 회색 표시.
인식 0건이면 422 `OCR_NO_TEXT`.

## 7. 제품 삭제 — 화면 6

```
DELETE /products/{productId}
```
**204**

## 8. 루틴 생성 ★ — 화면 3·4

**이 요청만 Spring이 아니라 AI 서버를 직접 호출한다** (SSE 버퍼링 회피).

```
POST {AI_BASE}/internal/v1/routines/stream
Authorization: Bearer <supabase jwt>
Accept: text/event-stream
```

```json
{ "selfiePath": "selfie/{userId}/2026-08-11.jpg", "lat": 37.5665, "lon": 126.9780 }
```

`selfiePath` 생략 = 셀카 건너뛰기. `EventSource`는 POST를 못 쓰므로 `fetch` + `ReadableStream`으로 수신.

**SSE 이벤트**

```
event: stage
data: {"stage":"SKIN","label":"피부 상태 확인 중"}
```
로딩 화면 단계 텍스트. `SKIN` → `WEATHER` → `PICK`

```
event: context
data: {"weather":{"temp":29.0,"humidity":38.0,"pm10":22,"pm25":14,"summary":"건조하고 미세먼지 보통이에요"},"skin":{"summary":"턱 주변 트러블이 보여요","flags":["ACNE"]}}
```
카드 상단 영역. 셀카를 건너뛴 경우 `skin`은 null.

```
event: conflict
data: {"pairs":[{"ingredients":["레티놀","비타민C"],"level":"AVOID","label":"같이 쓰지 마세요","reason":"...","source":"..."}]}
```
경고 배지. **본문보다 먼저 도착한다.** 충돌 없으면 빈 배열.

**서버가 화면에 맞게 정리해서 내려준다.** 프론트는 받은 순서대로 그리기만 하면 된다
(`barum-be/conflicts.py`의 `conflict_badges()`).

| 규칙 | 이유 |
|---|---|
| **한 제품 안의 배합은 판정하지 않는다** | AVOID의 뜻은 "이 둘을 같이 바르지 마세요"다. 한 제품에 레티놀과 레티놀 유도체가 같이 들어간 건 제조사가 조율한 결과다. 서로 다른 두 제품에 걸칠 때만 판정한다 |
| **같은 제품 쌍 + 같은 등급은 1건** | 세라마이드 아형이 여러 개 든 제품 하나 때문에 같은 말이 세 번 뜨는 걸 막는다 |
| **성분명은 대표명** | `하이드록시피나콜론레티노에이트` → `레티놀 계열`, `세라마이드엔피/엔에스/에이피` → `세라마이드`, `아스코빅애씨드` → `비타민C`, `토코페롤` → `비타민E`. 표준명을 그대로 쓰면 화면에서 안 읽힌다 |
| **AVOID는 전부, GOOD은 최대 2건** | 안전 경고는 빠뜨리지 않고, 시너지는 배지가 넘치지 않게 |

실제 샘플 화장대(13종, 성분 242종)에서 판정 **16건 → 카드 3건**으로 줄어든다.

```
event: item
data: {"type":"APPLY","order":1,"productId":"uuid","name":"약산성 젤 클렌저","reason":"장벽은 남기고"}
```
`APPLY`는 `order` 있음(순서대로 도착), `SKIP`은 없음.

```
event: done
data: {"recordDraftId":"uuid"}
```

```
event: error
data: {"code":"AI_TIMEOUT","message":"..."}
```

## 9. 기록 저장 — 화면 4

**프론트가 8번 SSE로 받은 내용을 그대로 담아 보낸다.** `recordDraftId`는 쓰지 않는다 —
FastAPI는 DB에 쓰지 않으므로(원칙 6) draft를 서버가 들고 있을 곳이 없다.

```
POST /records
```

```json
{
  "date": "2026-08-14",
  "selfiePath": "{userId}/2026-08-14.jpg",
  "weather": { "temp": 29.0, "humidity": 38.0, "pm10": 22, "pm25": 14, "summary": "건조하고 미세먼지 보통이에요" },
  "skin": { "summary": "턱 주변 트러블이 보여요", "flags": ["ACNE"] },
  "routine": {
    "apply": [
      { "order": 1, "name": "약산성 젤 클렌저", "reason": "장벽은 남기고" },
      { "order": 2, "name": "수분 진정 토너", "reason": "수분 먼저 채워요" }
    ],
    "skip": [
      { "name": "레티놀 앰플", "reason": "비타민C와 겹쳐 자극이 커져요" }
    ]
  },
  "conflicts": [
    { "ingredients": ["레티놀", "아스코빅애씨드"], "level": "AVOID",
      "label": "같이 쓰지 마세요", "reason": "자극이 겹칠 수 있어요", "source": "The Ordinary 공식 가이드" }
  ]
}
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `date` | 아니오 | `YYYY-MM-DD`. 생략하면 서버가 오늘(KST)로 채운다 |
| `selfiePath` | 아니오 | 5번에서 받은 `storagePath`. 셀카를 건너뛰었으면 생략 |
| `weather` | 아니오 | `context` 이벤트의 `weather` 그대로 |
| `skin` | 아니오 | `context` 이벤트의 `skin` 그대로. 건너뛰었으면 생략 |
| `routine` | 아니오 | `item` 이벤트를 `apply`/`skip`으로 모아 담는다 |
| `conflicts` | 아니오 | `conflict` 이벤트의 `pairs` 그대로. 없으면 `[]` |

**201** `{ "date": "2026-08-14" }`

- 같은 날짜에 다시 보내면 **덮어쓴다**(upsert). 루틴을 다시 받아 저장해도 기록이 늘지 않는다
- `weather`·`skin`·`routine`·`conflicts`는 **보낸 그대로 저장되고 11번에서 그대로 돌아온다.**
  구조를 서버가 해석하지 않으므로 AI 서버 출력이 바뀌어도 이 엔드포인트는 안 바뀐다
- 단, 11번 응답에서 `conflicts`는 `routine` 바깥으로 갈라져 나온다

## 10. 타임라인 — 화면 11

```
GET /records?limit=30
```

```json
{
  "items": [{
    "date": "2026-08-11",
    "thumbnailUrl": "https://...signed...",
    "weatherSummary": "29° · 습도 38%",
    "routineSummary": "수분 충전 위주 · 레티놀 휴식",
    "hasConflict": true
  }]
}
```

`thumbnailUrl`은 만료 있는 Signed URL. 셀카 없으면 null.

## 11. 일자 상세 / 삭제 — 화면 12

```
GET    /records/{date}
DELETE /records/{date}
```

```json
{
  "date": "2026-08-11",
  "selfieUrl": "https://...signed...",
  "weather": { "temp": 29.0, "humidity": 38.0, "pm10": 22, "pm25": 14, "summary": "..." },
  "skin": { "summary": "턱 주변 트러블이 보여요" },
  "conflicts": [{ "ingredients": ["레티놀","아스코빅애씨드"], "level": "AVOID", "label": "같이 쓰지 마세요", "reason": "...", "source": "..." }],
  "routine": {
    "apply": [{ "order": 1, "name": "약산성 젤 클렌저", "reason": "장벽은 남기고" }],
    "skip":  [{ "name": "레티놀 앰플", "reason": "비타민C와 겹쳐 자극이 커져요" }]
  }
}
```

## 12. 데이터 전체 삭제 — 화면 13

```
DELETE /me/data
```
**204** — 제품·기록·업로드 이미지 전부 삭제.

---

## 화면별 호출 정리

| 화면 | API |
|---|---|
| 오늘(홈) | 1 날씨, 10 타임라인(미리보기 1건) |
| 셀카 촬영 | 5 업로드 URL(`SELFIE`) |
| 분석 로딩 → 루틴 카드 | 8 루틴 스트림 |
| 루틴 카드 저장 | 9 기록 저장 |
| 화장대 | 3 목록, 7 삭제 |
| 제품 검색 등록 | 2 카탈로그, 4 등록(a) |
| 사진 등록 | 5 업로드 URL(`OCR`), 6 인식, 4 등록(b) |
| 기록 | 10 타임라인 |
| 일자 상세 | 11 조회·삭제 |
| 설정 | 12 전체 삭제 |

---

# 2부. DB 스키마

**적재 완료**: `ingredients`(식약처 표준 성분 21,863건), `products`, `daily_records`
**RLS**: `products`·`daily_records`는 `auth.uid() = user_id`. 참조 테이블은 select만 전원 허용.

**추가 필요 — 카탈로그**

```sql
catalog_products
  id              bigserial pk
  brand           text not null
  name            text not null
  category        text not null   -- CLEANSER | TONER | SERUM | CREAM | SUNSCREEN
  image_url       text
  raw_ingredients text            -- 수집 원문
  created_at      timestamptz default now()

catalog_product_ingredients
  catalog_id      bigint not null references catalog_products(id) on delete cascade
  ingredient_id   bigint references ingredients(id)   -- 매칭 실패 시 null
  raw_name        text not null                       -- 실패해도 원문 보존
  position        int                                 -- 표기 순서
  primary key (catalog_id, position)
```

**적재 완료 — 성분 조합 룰** (16건: AVOID 9 / GOOD 7)

```sql
ingredient_rules
  id           bigserial pk
  ingredient_a text not null      -- ingredients.std_name 참조(FK)
  ingredient_b text not null      -- ingredients.std_name 참조(FK)
  level        text not null      -- AVOID | GOOD
  label        text not null      -- "같이 쓰지 마세요"
  reason       text not null      -- 사용자 노출 문구
  source       text not null      -- 근거 출처
  verified     boolean not null   -- 원문 확인 여부. 발표 인용은 true만
  unique (ingredient_a, ingredient_b)
```

조합은 정렬된 쌍으로 저장해 순서 무관 매칭. 실제 정의는 `barum-be/schema/ingredient_rules.sql`,
판정 함수는 `barum-be/conflicts.py`의 `check_conflicts()`, 룰 근거 기준은 `barum-be/data/README.md`.

**성분명 컬럼은 `std_name`이다.** `standard_name`이 아니다 — 쿼리 짤 때 주의.

`products`에 `catalog_id`(nullable), `source` 컬럼 필요.

---

# 3부. Spring ↔ FastAPI (내부)

구교승 명세 작성 중이라 엔드포인트 형태는 미정. 아래는 설계 원칙으로 고정.

- **FastAPI는 DB에 쓰지 않는다.** 읽고 결과만 반환, 저장은 전부 Spring
- 성분은 `ingredients` 표준명으로 매칭된 형태로 반환
- 성분 궁합 판정은 룰테이블(결정론적) 결과를 쓰고, AI가 판단하지 않는다
- 내부 호출 인증은 `X-Internal-Key` 헤더

예상 엔드포인트: 날씨 컨텍스트, 전성분표 OCR, 성분 충돌 판정, 루틴 스트리밍.
