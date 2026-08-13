package com.barum.api;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.barum.common.ApiException;
import com.barum.common.ErrorCode;
import com.barum.db.Rls;

/** API.md 2 — 카탈로그 검색 (화면 8). 참조 데이터라 토큰 없이 열려 있다. */
@RestController
@RequestMapping("/api/v1/catalog")
public class CatalogController {

    private static final List<String> CATEGORIES =
            List.of("CLEANSER", "TONER", "SERUM", "CREAM", "SUNSCREEN");
    private static final int MAX_SIZE = 50;

    private final Rls rls;

    public CatalogController(Rls rls) {
        this.rls = rls;
    }

    @GetMapping("/products")
    public Map<String, Object> search(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String category,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {

        if (category != null && !CATEGORIES.contains(category)) {
            throw new ApiException(ErrorCode.VALIDATION_ERROR, "지원하지 않는 카테고리입니다.");
        }
        int limit = Math.min(Math.max(size, 1), MAX_SIZE);
        int offset = Math.max(page, 0) * limit;
        String like = (q == null || q.isBlank()) ? null : "%" + q.trim() + "%";

        return rls.asAnon(jdbc -> {
            Integer total = jdbc.queryForObject("""
                    select count(*) from catalog_products
                     where (?::text is null or name ilike ?::text or brand ilike ?::text)
                       and (?::text is null or category = ?::text)
                    """, Integer.class, like, like, like, category, category);

            List<Map<String, Object>> rows = jdbc.queryForList("""
                    select id, brand, name, category, image_url
                      from catalog_products
                     where (?::text is null or name ilike ?::text or brand ilike ?::text)
                       and (?::text is null or category = ?::text)
                     order by id
                     limit ? offset ?
                    """, like, like, like, category, category, limit, offset);

            Map<Long, List<String>> keyIngredients = keyIngredients(jdbc, rows);

            List<Map<String, Object>> items = new ArrayList<>();
            for (Map<String, Object> r : rows) {
                Long id = ((Number) r.get("id")).longValue();
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("catalogId", id);
                item.put("brand", r.get("brand"));
                item.put("name", r.get("name"));
                item.put("category", r.get("category"));
                item.put("imageUrl", r.get("image_url"));
                item.put("keyIngredients", keyIngredients.getOrDefault(id, List.of()));
                items.add(item);
            }

            Map<String, Object> out = new LinkedHashMap<>();
            out.put("items", items);
            out.put("page", page);
            out.put("size", limit);
            out.put("totalElements", total);
            return out;
        });
    }

    /**
     * 주요 성분은 뷰가 계산한다. 제외 목록을 Java로 옮기면 목록이 바뀔 때마다 재배포해야 한다
     * (schema/key_ingredients.sql). 제품마다 부르지 않고 한 번에 가져온다.
     */
    private Map<Long, List<String>> keyIngredients(org.springframework.jdbc.core.JdbcTemplate jdbc,
                                                   List<Map<String, Object>> rows) {
        Map<Long, List<String>> out = new LinkedHashMap<>();
        if (rows.isEmpty()) {
            return out;
        }
        Long[] ids = rows.stream().map(r -> ((Number) r.get("id")).longValue()).toArray(Long[]::new);
        jdbc.query("""
                select catalog_id, std_name
                  from catalog_key_ingredients
                 where catalog_id = any(?) and rank <= 3
                 order by catalog_id, rank
                """,
                ps -> ps.setArray(1, ps.getConnection().createArrayOf("bigint", ids)),
                rs -> {
                    out.computeIfAbsent(rs.getLong("catalog_id"), k -> new ArrayList<>())
                            .add(rs.getString("std_name"));
                });
        return out;
    }
}
