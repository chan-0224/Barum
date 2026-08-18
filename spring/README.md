# barum Spring API

`docs/API.md` 1부(프론트 ↔ Spring)를 구현한다. Spring Boot 3.3 · Java 21 · Gradle.

## 담당 경계

| 범위 | 담당 | API.md 번호 |
|---|---|---|
| 제품 목록·등록·삭제 (CRUD) | 왕종휘 (마무리: 이찬영) | 3 · 4 · 7 |
| 그 외 전부 | 이찬영 + Claude Code | 1 · 2 · 5 · 9~13 |
| OCR·루틴 | 구교승 (AI 서버) | 6 · 8 — Spring은 프록시만 |

## 실행

```bash
cp .env.example .env      # 값 채우고
set -a && . ./.env && set +a
./gradlew bootRun
```

헬스체크: `GET /actuator/health`

## DB 접근 — service_role 키를 쓰지 않는다

**이 프로젝트에서 가장 중요한 설계 결정이다.** 원칙 4(격리는 RLS)가 여기서 지켜지거나 깨진다.

Supabase에는 RLS를 통째로 우회하는 `service_role` 키가 있다. 그걸 쓰면 편하지만,
격리가 **앱 코드 품질에 의존**하게 된다. 쿼리 하나에서 `where user_id = ?`를 빠뜨리는 순간
남의 셀카가 새고, 그걸 잡아줄 안전망이 없다.

그래서 Spring은 **JDBC로 직접 붙되 RLS가 걸린 상태로** 질의한다. `db/Rls.java`:

```java
rls.asUser(userId, jdbc -> jdbc.query("select * from daily_records", ...));
//  → set local role authenticated
//  → set_config('request.jwt.claims', '{"sub":"<uid>",...}', true)
//  → auth.uid()가 동작하고 RLS 정책이 실제로 적용된다
```

- `set local role authenticated` — 연결 계정이 테이블 소유자면 RLS가 무시된다. 소유자가 아닌 역할로 바꿔야 정책이 적용된다
- 둘 다 `local`이라 **트랜잭션이 끝나면 사라진다.** 커넥션 풀에서 다음 요청이 앞 사용자 권한을 물려받지 않는다
- 뒤집어 말하면 **트랜잭션 밖에서 쓰면 안 된다.** `SET LOCAL`이 무시돼 RLS 없이 질의된다. 그래서 `Rls`가 `TransactionTemplate`으로 감싼다
- 참조 테이블(`ingredients` `catalog_*` `ingredient_rules`)은 `asAnon()`으로 읽는다. select가 전원 허용이다

**모든 DB 접근은 `Rls`를 통한다.** `JdbcTemplate`을 직접 주입받아 쓰지 말 것.

`service_role` 키는 운영 스크립트(`barum-be/scripts/*.py`) 전용이다.

## 인증

프론트가 Supabase `signInAnonymously()`로 받은 JWT를 `Authorization: Bearer`로 보낸다.
검증은 **JWKS(공개키)** 로 한다 — 서버가 JWT 시크릿을 들고 있을 필요가 없다.

`SecurityConfig.currentUserId()`가 `sub` 클레임을 꺼낸다. 이 값이 곧 `auth.uid()`다.

`/api/v1/catalog/**`는 토큰 없이 열려 있다. 참조 데이터이고, 화장대를 만들기 전에
제품을 둘러볼 수 있어야 한다.

## Swagger UI — 테스트용 익명 토큰 받기

`http://barum-dev.duckdns.org:8081/swagger-ui.html` (개발 중에만. `DOCS_ENABLED=true`)

카탈로그 말고는 전부 `Authorize`에 토큰을 넣어야 401이 안 뜬다. 프론트 없이 토큰만
따로 뽑는 방법 두 가지. **둘 다 프론트의 `signInAnonymously()`와 똑같은 요청이다.**

`$SUPABASE_URL`·`$SUPABASE_ANON_KEY`는 `.env` 또는 Supabase 대시보드 →
Settings → API Keys. anon 키는 원래 브라우저에 노출되는 키라 공유해도 된다
(막는 건 키가 아니라 RLS다). **`service_role` 키는 절대 여기 쓰지 말 것** — RLS를
통째로 우회해서 남의 데이터가 다 보인다.

### curl

```bash
curl -s -X POST "$SUPABASE_URL/auth/v1/signup" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])"
```

출력된 문자열을 Swagger `Authorize`에 붙여넣는다. **`Bearer ` 접두사는 빼고 값만.**

### 브라우저 콘솔

아무 페이지에서나 F12 → Console. (Supabase가 Origin을 그대로 허용해서 CORS가 안 걸린다)

```js
const SUPABASE_URL = "https://xxxxxxxx.supabase.co";
const ANON_KEY = "sb_publishable_...";

const r = await fetch(`${SUPABASE_URL}/auth/v1/signup`, {
  method: "POST",
  headers: { apikey: ANON_KEY, "Content-Type": "application/json" },
  body: "{}",
});
const { access_token } = await r.json();
copy(access_token);            // 클립보드로 복사 (Chrome·Firefox 콘솔 전용 함수)
console.log(access_token);
```

### 알아둘 것

- **유효기간 1시간.** 401이 갑자기 뜨면 대개 만료다. 다시 뽑으면 된다
- **호출할 때마다 새 익명 유저가 생긴다.** 토큰을 바꾸면 화장대가 빈 상태로 돌아간다.
  제품을 등록하고 이어서 테스트하려면 **같은 토큰을 계속 쓸 것**
- 토큰의 `sub`가 곧 `auth.uid()`다. 디코딩해서 확인하려면 [jwt.io](https://jwt.io)
- FastAPI `/docs`도 같은 토큰을 쓴다. 단 `X-Internal-Key`가 걸린 두 개
  (`/context/daily`, `/ocr/ingredients`)는 Spring 전용이라 JWT가 아니라 `AI_INTERNAL_KEY`를 넣는다
- 응답에 `refresh_token`도 오지만 **테스트에는 필요 없다.** 만료되면 위 명령을 다시 돌리는 게 빠르다
- `{"code":"VALIDATION_ERROR","message":"존재하지 않는 경로입니다."}`가 **400**으로 오면
  토큰 문제가 아니라 **매핑이 없는 경로**다. 경로 오타를 의심할 것

## 커넥션 풀 주의

Supabase Transaction Pooler(6543)는 pgbouncer transaction 모드라 서버사이드 prepared
statement를 못 쓴다. JDBC URL에 **`prepareThreshold=0`을 반드시 붙일 것.**
없으면 부하가 걸릴 때 `prepared statement "S_1" already exists`가 간헐적으로 뜬다.

## 스키마

테이블은 이미 Supabase에 있다(`barum-be/schema/*.sql`). **Spring은 스키마를 만들지 않는다.**
JPA/Hibernate 대신 JdbcTemplate을 쓰는 이유도 이것 — 엔티티가 스키마를 재정의할 여지를 없앤다.

| 테이블/뷰 | 용도 |
|---|---|
| `ingredients` | 식약처 표준 성분 21,863건 |
| `ingredient_rules` | 성분 조합 룰 54건 |
| `products` / `product_ingredients` | 내 화장대 (RLS) |
| `daily_records` | 셀카·루틴 기록 (RLS) |
| `catalog_products` / `catalog_product_ingredients` | 제품 카탈로그 |
| `catalog_key_ingredients` (뷰) | 주요 성분 3개. **제외 로직을 Java에 넣지 말 것** |
