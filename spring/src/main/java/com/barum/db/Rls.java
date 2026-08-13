package com.barum.db;

import java.util.UUID;
import java.util.function.Function;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * RLS가 실제로 걸린 상태로 질의한다 (원칙 4).
 *
 * <p>Supabase의 {@code auth.uid()}는 세션 설정 {@code request.jwt.claims}의 sub를 읽는다.
 * 그래서 트랜잭션마다 두 가지를 세팅한다.
 * <ul>
 *   <li>{@code set local role authenticated} — 연결 계정이 테이블 소유자면 RLS가 무시된다.
 *       소유자가 아닌 역할로 바꿔야 정책이 실제로 적용된다.</li>
 *   <li>{@code request.jwt.claims} — {@code auth.uid()}가 읽을 값</li>
 * </ul>
 *
 * <p>둘 다 {@code local}이라 트랜잭션이 끝나면 사라진다. 커넥션 풀에서 다음 요청이
 * 앞 사용자의 권한을 물려받는 일이 없다. <b>그래서 반드시 트랜잭션 안에서 실행해야 한다.</b>
 *
 * <p>service_role 키를 쓰지 않는 이유: 그 키는 RLS를 통째로 우회하므로 격리가 앱 코드
 * 품질에 의존하게 된다. 쿼리 하나에서 {@code where user_id = ?}를 빠뜨리면 남의 데이터가 샌다.
 */
@Component
public class Rls {

    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;

    public Rls(JdbcTemplate jdbc, TransactionTemplate tx) {
        this.jdbc = jdbc;
        this.tx = tx;
    }

    /** 로그인한 사용자 권한으로 실행. userId는 검증된 JWT의 sub여야 한다. */
    public <T> T asUser(String userId, Function<JdbcTemplate, T> work) {
        UUID uid = UUID.fromString(userId);  // JSON에 넣기 전에 형식을 강제한다
        return tx.execute(status -> {
            jdbc.execute("set local role authenticated");
            // update()가 아니라 query다 — set_config는 SELECT로 호출해야 실제로 실행된다
            jdbc.queryForObject("select set_config('request.jwt.claims', ?::text, true)",
                    String.class, "{\"sub\":\"" + uid + "\",\"role\":\"authenticated\"}");
            return work.apply(jdbc);
        });
    }

    /**
     * 로그인 없이 읽는 참조 테이블용 (ingredients, catalog_*, ingredient_rules).
     * 이들은 select가 전원 허용이라 익명 권한으로 충분하다.
     */
    public <T> T asAnon(Function<JdbcTemplate, T> work) {
        return tx.execute(status -> {
            jdbc.execute("set local role anon");
            return work.apply(jdbc);
        });
    }
}
