# barum Spring API

`docs/API.md` 1부(프론트 ↔ Spring)를 구현한다. Spring Boot 3.3 · Java 21 · Gradle.

## 담당 경계

| 범위 | 담당 | API.md 번호 |
|---|---|---|
| 제품 목록·등록·삭제 (CRUD) | 왕종휘 | 3 · 4 · 7 |
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
