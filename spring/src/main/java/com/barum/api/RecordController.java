package com.barum.api;

import java.time.LocalDate;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import com.barum.client.StorageClient;
import com.barum.common.ApiException;
import com.barum.common.ErrorCode;
import com.barum.config.SecurityConfig;
import com.barum.db.Rls;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * API.md 9·10·11 — 기록 저장 / 타임라인 / 일자 상세·삭제 (화면 4·11·12).
 *
 * <p><b>충돌 판정은 routine jsonb 안에 함께 저장한다.</b> 별도 컬럼을 두지 않는 이유는
 * daily_records의 jsonb 3개를 고른 이유와 같다 — 모양이 아직 바뀌는 값에 마이그레이션을
 * 붙이지 않는다. 응답에서만 갈라서 내보낸다.
 */
@RestController
@RequestMapping("/api/v1/records")
public class RecordController {

    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    private static final int SIGNED_URL_TTL = 3600;

    private final Rls rls;
    private final StorageClient storage;
    private final ObjectMapper json;

    public RecordController(Rls rls, StorageClient storage, ObjectMapper json) {
        this.rls = rls;
        this.storage = storage;
        this.json = json;
    }

    public record SaveRequest(
            String date,
            String selfiePath,
            Map<String, Object> weather,
            Map<String, Object> skin,
            Map<String, Object> routine,
            List<Map<String, Object>> conflicts) {}

    /** 9 — 기록 저장. 같은 날짜면 덮어쓴다. */
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> save(@RequestBody SaveRequest req) {
        String userId = SecurityConfig.currentUserId();
        LocalDate date = req.date() == null ? LocalDate.now(KST) : parseDate(req.date());

        Map<String, Object> routine = new LinkedHashMap<>();
        if (req.routine() != null) {
            routine.putAll(req.routine());
        }
        routine.put("conflicts", req.conflicts() == null ? List.of() : req.conflicts());

        rls.asUser(userId, jdbc -> jdbc.update("""
                insert into daily_records (user_id, record_date, selfie_path, skin_context, weather, routine)
                values (?::uuid, ?::date, ?, ?::jsonb, ?::jsonb, ?::jsonb)
                on conflict (user_id, record_date) do update set
                  selfie_path = excluded.selfie_path,
                  skin_context = excluded.skin_context,
                  weather = excluded.weather,
                  routine = excluded.routine
                """,
                userId, date.toString(), req.selfiePath(),
                write(req.skin()), write(req.weather()), write(routine)));

        return Map.of("date", date.toString());
    }

    /** 10 — 타임라인. */
    @GetMapping
    public Map<String, Object> timeline(@RequestParam(defaultValue = "30") int limit) {
        String userId = SecurityConfig.currentUserId();
        int cap = Math.min(Math.max(limit, 1), 100);

        List<Map<String, Object>> rows = rls.asUser(userId, jdbc -> jdbc.queryForList("""
                select record_date, selfie_path, weather::text as weather, routine::text as routine
                  from daily_records
                 order by record_date desc
                 limit ?
                """, cap));

        List<String> paths = rows.stream()
                .map(r -> (String) r.get("selfie_path")).filter(p -> p != null).toList();
        Map<String, String> signed = storage.signedUrls(
                SecurityConfig.currentJwt(), StorageClient.BUCKET_SELFIE, paths, SIGNED_URL_TTL);

        List<Map<String, Object>> items = new ArrayList<>();
        for (Map<String, Object> r : rows) {
            Map<String, Object> weather = read(r.get("weather"));
            Map<String, Object> routine = read(r.get("routine"));
            String path = (String) r.get("selfie_path");

            Map<String, Object> item = new LinkedHashMap<>();
            item.put("date", String.valueOf(r.get("record_date")));
            item.put("thumbnailUrl", path == null ? null : signed.get(path));
            item.put("weatherSummary", weatherSummary(weather));
            item.put("routineSummary", routineSummary(routine));
            item.put("hasConflict", !conflicts(routine).isEmpty());
            items.add(item);
        }
        return Map.of("items", items);
    }

    /** 11 — 일자 상세. */
    @GetMapping("/{date}")
    public Map<String, Object> detail(@PathVariable String date) {
        String userId = SecurityConfig.currentUserId();
        LocalDate d = parseDate(date);

        List<Map<String, Object>> rows = rls.asUser(userId, jdbc -> jdbc.queryForList("""
                select record_date, selfie_path, skin_context::text as skin,
                       weather::text as weather, routine::text as routine
                  from daily_records where record_date = ?::date
                """, d.toString()));
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.PRODUCT_NOT_FOUND, "해당 날짜의 기록이 없습니다.");
        }

        Map<String, Object> r = rows.get(0);
        Map<String, Object> routine = read(r.get("routine"));
        String path = (String) r.get("selfie_path");
        String selfieUrl = path == null ? null : storage.signedUrls(
                SecurityConfig.currentJwt(), StorageClient.BUCKET_SELFIE,
                List.of(path), SIGNED_URL_TTL).get(path);

        Map<String, Object> body = new LinkedHashMap<>(routine);
        body.remove("conflicts");

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("date", String.valueOf(r.get("record_date")));
        out.put("selfieUrl", selfieUrl);
        out.put("weather", read(r.get("weather")));
        out.put("skin", read(r.get("skin")));
        out.put("conflicts", conflicts(routine));
        out.put("routine", body);
        return out;
    }

    /** 11 — 일자 삭제. 셀카 파일도 같이 지운다(원칙 5 — 기록만 지우고 사진이 남으면 안 된다). */
    @DeleteMapping("/{date}")
    public ResponseEntity<Void> delete(@PathVariable String date) {
        String userId = SecurityConfig.currentUserId();
        LocalDate d = parseDate(date);

        String path = rls.asUser(userId, jdbc -> {
            List<String> found = jdbc.queryForList(
                    "select selfie_path from daily_records where record_date = ?::date",
                    String.class, d.toString());
            jdbc.update("delete from daily_records where record_date = ?::date", d.toString());
            return found.isEmpty() ? null : found.get(0);
        });
        if (path != null) {
            storage.deleteObjects(SecurityConfig.currentJwt(), StorageClient.BUCKET_SELFIE, List.of(path));
        }
        return ResponseEntity.noContent().build();
    }

    // ── 표시용 문자열 ────────────────────────────────────────────

    static String weatherSummary(Map<String, Object> w) {
        if (w == null || w.isEmpty()) {
            return "";
        }
        Object temp = w.get("temp");
        Object humidity = w.get("humidity");
        StringBuilder sb = new StringBuilder();
        if (temp instanceof Number n) {
            sb.append(Math.round(n.doubleValue())).append("°");
        }
        if (humidity instanceof Number n) {
            if (sb.length() > 0) {
                sb.append(" · ");
            }
            sb.append("습도 ").append(Math.round(n.doubleValue())).append("%");
        }
        return sb.toString();
    }

    @SuppressWarnings("unchecked")
    static String routineSummary(Map<String, Object> routine) {
        if (routine == null) {
            return "";
        }
        List<Map<String, Object>> apply = (List<Map<String, Object>>) routine.getOrDefault("apply", List.of());
        List<Map<String, Object>> skip = (List<Map<String, Object>>) routine.getOrDefault("skip", List.of());

        StringBuilder sb = new StringBuilder();
        if (!apply.isEmpty()) {
            sb.append(String.valueOf(apply.get(0).get("name")));
            if (apply.size() > 1) {
                sb.append(" 외 ").append(apply.size() - 1).append("개");
            }
        }
        if (!skip.isEmpty()) {
            if (sb.length() > 0) {
                sb.append(" · ");
            }
            sb.append(String.valueOf(skip.get(0).get("name"))).append(" 휴식");
        }
        return sb.toString();
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> conflicts(Map<String, Object> routine) {
        if (routine == null) {
            return List.of();
        }
        Object c = routine.get("conflicts");
        return c instanceof List<?> list ? (List<Map<String, Object>>) list : List.of();
    }

    // ── jsonb 변환 ──────────────────────────────────────────────

    private String write(Object value) {
        try {
            return value == null ? null : json.writeValueAsString(value);
        } catch (Exception e) {
            throw new ApiException(ErrorCode.VALIDATION_ERROR, "요청 본문을 처리할 수 없습니다.");
        }
    }

    private Map<String, Object> read(Object text) {
        if (text == null) {
            return Map.of();
        }
        try {
            return json.readValue(String.valueOf(text), new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            return Map.of();
        }
    }

    private static LocalDate parseDate(String s) {
        try {
            return LocalDate.parse(s);
        } catch (Exception e) {
            throw new ApiException(ErrorCode.VALIDATION_ERROR, "날짜 형식은 YYYY-MM-DD 입니다.");
        }
    }
}
