package com.barum.api;

import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import com.barum.db.Rls;

/**
 * 외부에서 부르는 헬스체크.
 *
 * <p>{@code /actuator/health}는 Traefik이 {@code /api/v1} 접두사만 라우팅해서 밖에서 안 보인다.
 * 액추에이터를 통째로 노출하는 대신 라우팅되는 경로에 하나 둔다.
 *
 * <p>DB까지 확인한다 — 프로세스만 살아 있고 Supabase 연결이 끊긴 상태를 정상으로 보고하면
 * 헬스체크가 의미가 없다. 행사 종료까지 상시 가동이 요건이라 이 구분이 필요하다.
 */
@RestController
public class HealthController {

    private static final ZoneId KST = ZoneId.of("Asia/Seoul");

    private final Rls rls;

    public HealthController(Rls rls) {
        this.rls = rls;
    }

    @GetMapping("/api/v1/health")
    public Map<String, Object> health() {
        String db;
        try {
            Integer one = rls.asAnon(jdbc -> jdbc.queryForObject("select 1", Integer.class));
            db = (one != null && one == 1) ? "UP" : "DOWN";
        } catch (Exception e) {
            db = "DOWN";
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("status", "UP".equals(db) ? "UP" : "DEGRADED");
        out.put("service", "spring");
        out.put("db", db);
        out.put("time", ZonedDateTime.now(KST).toString());
        return out;
    }
}
