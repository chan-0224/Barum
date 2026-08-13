package com.barum.db;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * RLS가 실제로 걸리는지 검증한다. 원칙 4가 여기서 지켜지거나 깨진다.
 *
 * <p>"막았다고 생각했는데 안 막혀 있었다"가 이 구조에서 가장 비싼 사고라, 눈으로 확인하고 넘어간다.
 * 실행: {@code ./gradlew test} (spring/.env 를 환경변수로 로드한 상태)
 */
// webEnvironment=NONE으로 두면 SecurityConfig가 HttpSecurity를 못 찾아 컨텍스트가 안 뜬다.
// 기본값(MOCK)은 포트를 열지 않으면서 서블릿 스택만 올려준다.
@SpringBootTest
@EnabledIfEnvironmentVariable(named = "SUPABASE_JDBC_URL", matches = ".+")
class RlsIsolationTest {

    private static final ObjectMapper JSON = new ObjectMapper();
    private static String userA;
    private static String userB;

    @Autowired
    Rls rls;

    @Autowired
    JdbcTemplate rawJdbc;

    /** Supabase 익명 로그인으로 실제 auth.users 행을 만든다. products.user_id가 FK라 필요하다. */
    @BeforeAll
    static void createAnonymousUsers() throws Exception {
        userA = signInAnonymously();
        userB = signInAnonymously();
        assertThat(userA).isNotEqualTo(userB);
    }

    private static String signInAnonymously() throws Exception {
        String base = System.getenv("SUPABASE_URL");
        String anonKey = System.getenv("SUPABASE_ANON_KEY");
        HttpRequest req = HttpRequest.newBuilder(URI.create(base + "/auth/v1/signup"))
                .header("apikey", anonKey)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString("{}"))
                .build();
        HttpResponse<String> res = HttpClient.newHttpClient().send(req, HttpResponse.BodyHandlers.ofString());
        if (res.statusCode() >= 400) {
            throw new IllegalStateException("익명 로그인 실패 " + res.statusCode() + ": " + res.body());
        }
        return JSON.readTree(res.body()).get("user").get("id").asText();
    }

    private UUID insertProduct(String owner, String name) {
        return rls.asUser(owner, jdbc -> jdbc.queryForObject(
                "insert into products (user_id, name, source) values (?::uuid, ?, 'OCR') returning id",
                UUID.class, owner, name));
    }

    private List<Map<String, Object>> listProducts(String viewer) {
        return rls.asUser(viewer, jdbc -> jdbc.queryForList("select id, name from products"));
    }

    @Test
    @DisplayName("A가 넣은 제품을 B는 볼 수 없다")
    void userIsolation() {
        UUID pid = insertProduct(userA, "격리검증 세럼");

        // 다른 테스트가 B의 제품을 남길 수 있으므로 "비어 있다"가 아니라 "A의 것이 안 보인다"로 본다
        assertThat(listProducts(userA)).extracting(m -> m.get("id")).contains(pid);
        assertThat(listProducts(userB)).extracting(m -> m.get("id")).doesNotContain(pid);

        // 수정·삭제도 막혀야 한다. RLS는 0행 영향으로 조용히 끝난다
        int updated = rls.asUser(userB, jdbc ->
                jdbc.update("update products set name = '탈취됨' where id = ?::uuid", pid));
        assertThat(updated).isZero();

        int deleted = rls.asUser(userB, jdbc ->
                jdbc.update("delete from products where id = ?::uuid", pid));
        assertThat(deleted).isZero();
    }

    @Test
    @DisplayName("B가 user_id를 A로 위조해 넣을 수 없다 (with check)")
    void forgedInsertRejected() {
        // RLS 위반은 SQLSTATE 42501로 오고 Spring이 BadSqlGrammarException으로 감싼다.
        // 최상위 메시지에는 안 남으므로 원인 사슬 전체에서 확인한다.
        assertThatThrownBy(() -> rls.asUser(userB, jdbc -> jdbc.update(
                "insert into products (user_id, name, source) values (?::uuid, '위조', 'OCR')", userA)))
                .hasStackTraceContaining("row-level security");
    }

    @Test
    @DisplayName("★ set local이 커넥션 재사용 시 다음 요청으로 새지 않는다")
    void settingsDoNotLeakAcrossRequests() {
        insertProduct(userA, "A의 제품");
        insertProduct(userB, "B의 제품");

        // 두 유저를 번갈아 여러 번. 커넥션이 재사용되면서 앞 요청의 role/claims가 남으면 여기서 깨진다
        for (int i = 0; i < 20; i++) {
            String seenByA = rls.asUser(userA, jdbc ->
                    jdbc.queryForObject("select coalesce(string_agg(name, ','), '') from products", String.class));
            String seenByB = rls.asUser(userB, jdbc ->
                    jdbc.queryForObject("select coalesce(string_agg(name, ','), '') from products", String.class));

            assertThat(seenByA).as("%d회차 A", i).doesNotContain("B의 제품");
            assertThat(seenByB).as("%d회차 B", i).doesNotContain("A의 제품");
        }
    }

    @Test
    @DisplayName("★ Rls 밖에서는 auth.uid()가 비어 있다 (설정이 세션에 남지 않는다)")
    void claimsClearedOutsideTransaction() {
        rls.asUser(userA, jdbc -> jdbc.queryForObject("select 1", Integer.class));

        // 앞 트랜잭션의 set local이 살아 있으면 A의 uid가 나온다
        String leaked = rawJdbc.queryForObject(
                "select coalesce(current_setting('request.jwt.claims', true), '')", String.class);
        assertThat(leaked).as("이전 요청의 JWT 클레임이 남아 있으면 안 된다").isEmpty();

        String role = rawJdbc.queryForObject("select current_user", String.class);
        assertThat(role).as("역할도 원래대로 돌아와야 한다").isNotEqualTo("authenticated");
    }

    @Test
    @DisplayName("참조 테이블은 익명으로 읽힌다")
    void referenceTablesReadableAsAnon() {
        Integer ingredients = rls.asAnon(jdbc ->
                jdbc.queryForObject("select count(*) from ingredients", Integer.class));
        assertThat(ingredients).isGreaterThan(20000);

        Integer catalog = rls.asAnon(jdbc ->
                jdbc.queryForObject("select count(*) from catalog_products", Integer.class));
        assertThat(catalog).isPositive();

        Integer rules = rls.asAnon(jdbc ->
                jdbc.queryForObject("select count(*) from ingredient_rules", Integer.class));
        assertThat(rules).isPositive();

        // 뷰도 익명으로 읽혀야 한다. keyIngredients가 여기서 나온다
        List<Map<String, Object>> key = rls.asAnon(jdbc -> jdbc.queryForList(
                "select std_name from catalog_key_ingredients where rank <= 3 limit 3"));
        assertThat(key).isNotEmpty();
    }

    @Test
    @DisplayName("익명 권한으로는 참조 테이블에 쓸 수 없다")
    void referenceTablesNotWritable() {
        assertThatThrownBy(() -> rls.asAnon(jdbc ->
                jdbc.update("insert into ingredients (std_name) values ('가짜성분')")))
                .isInstanceOf(Exception.class);
    }

    @AfterAll
    static void cleanup(@Autowired Rls rls) {
        for (String uid : List.of(userA, userB)) {
            rls.asUser(uid, jdbc -> jdbc.update("delete from products"));
        }
    }
}
