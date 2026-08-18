package com.barum.crud;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import com.barum.common.ApiException;
import com.barum.common.ErrorCode;
import com.barum.config.SecurityConfig;
import com.barum.db.Rls;

/**
 * API.md 3·4·7 — 내 화장대.
 *
 * <p><b>모든 DB 접근은 {@link Rls}를 통한다</b>(원칙 4). JPA Repository를 쓰면 커넥션의
 * 기본 역할(postgres, rolbypassrls)로 질의하게 되어 RLS가 통째로 우회된다. 그러면 격리가
 * {@code where user_id = ?}를 빠뜨리지 않는 앱 코드 품질에만 의존한다.
 *
 * <p>그래서 아래 질의에는 {@code where user_id = ?}가 없다. 일부러 없는 것이다 —
 * RLS 정책이 걸러 주는지를 코드가 아니라 DB로 보장한다.
 */
@Service
public class ProductService {

    /** 화면 6의 배지. 표기 순서 상위 3개까지(카탈로그는 catalog_key_ingredients 뷰와 같은 규칙). */
    private static final int KEY_INGREDIENTS = 3;

    /** OCR 등록 제품은 카탈로그가 없어 카테고리를 알 수 없다. */
    private static final String OCR_CATEGORY = "ETC";

    /**
     * 화장대 상한. 아침 30초에 쓰는 물건이라 50개도 현실에서는 넘치는 수다.
     *
     * <p>상한이 없으면 루틴 프롬프트가 그대로 커진다 — 실측에서 제품 1000개면 38,000토큰이라
     * 분당 한도(TPM 30,000)를 한 번의 요청이 넘겨 서비스 전체가 429가 됐다.
     * 화면 문제가 아니라 가용성 문제라 서버에서 막는다.
     */
    private static final int MAX_PRODUCTS = 50;

    /** 한 번에 담을 수 있는 카탈로그 제품 수. */
    private static final int MAX_CATALOG_IDS = 50;

    /** OCR 별칭 길이. 화면 6의 제품명 자리에 들어가야 한다. */
    private static final int MAX_ALIAS = 100;

    /** 전성분표 성분 수. 실물 최대가 60개 안팎이라 200이면 충분히 넉넉하다. */
    private static final int MAX_INGREDIENTS = 200;

    private final Rls rls;

    public ProductService(Rls rls) {
        this.rls = rls;
    }

    // ── 3. 목록 ────────────────────────────────────────────────

    public Map<String, Object> list() {
        String userId = SecurityConfig.currentUserId();

        List<Map<String, Object>> rows = rls.asUser(userId, jdbc -> {
            if (count(jdbc) == 0) {
                seedSample(jdbc, userId);
            }
            return select(jdbc);
        });

        boolean isSample = !rows.isEmpty()
                && rows.stream().allMatch(r -> "SAMPLE".equals(r.get("source")));

        Map<UUID, List<String>> keyIngredients = rls.asUser(userId, this::keyIngredients);

        List<Map<String, Object>> items = new ArrayList<>();
        for (Map<String, Object> r : rows) {
            UUID id = (UUID) r.get("id");
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("productId", id.toString());
            item.put("brand", r.get("brand"));
            item.put("name", r.get("name"));
            item.put("category", r.get("category") == null ? OCR_CATEGORY : r.get("category"));
            item.put("imageUrl", r.get("image_url"));
            item.put("source", r.get("source"));
            item.put("keyIngredients", keyIngredients.getOrDefault(id, List.of()));
            item.put("createdAt", r.get("created_at"));
            items.add(item);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("isSample", isSample);
        out.put("items", items);
        return out;
    }

    private int count(JdbcTemplate jdbc) {
        Integer n = jdbc.queryForObject("select count(*) from products", Integer.class);
        return n == null ? 0 : n;
    }

    /**
     * 샘플 13종 백업 시드.
     *
     * <p><b>평소에는 실행되지 않는다.</b> 계정이 만들어질 때 DB 트리거가 이미 채운다
     * ({@code barum-be/schema/seed_trigger.sql}). 루틴 생성은 프론트가 FastAPI를 직접
     * 부르므로 Spring을 거치지 않고, 그래서 주입을 여기에만 두면 첫 진입에서 EMPTY_VANITY가 떴다.
     *
     * <p>트리거가 예외를 삼키도록 되어 있어(가입이 막히면 안 된다) 드물게 비어 있을 수 있다.
     * 그때를 위한 그물로 남겨 둔다.
     *
     * <p>{@code created_at}을 position만큼 어긋나게 넣는다. 한 문장으로 13행을 넣으면
     * {@code now()}가 전부 같은 값이라 정렬이 실행할 때마다 달라지는데, 그 순서가 화면 6에
     * 그대로 보인다. sample_vanity.position은 클렌저→토너→세럼→크림→선크림으로 짜여 있다.
     *
     * <p>{@code where not exists}는 동시에 두 번 들어와도 13종이 겹쳐 들어가지 않게 한다.
     */
    private void seedSample(JdbcTemplate jdbc, String userId) {
        jdbc.update("""
                insert into products (user_id, catalog_id, name, source, created_at)
                select ?::uuid, v.catalog_id, v.name, 'SAMPLE',
                       now() + (v.position * interval '1 millisecond')
                  from sample_vanity v
                 where not exists (select 1 from products)
                 order by v.position
                """, userId);
    }

    /** 등록 순서대로. 샘플은 position 순, 이후 사용자가 넣은 제품이 뒤에 붙는다. */
    private List<Map<String, Object>> select(JdbcTemplate jdbc) {
        // created_at을 두 번 뽑지 않는다. 같은 이름이면 앞의 값이 남아 to_char이 무시되고
        // UTC 타임스탬프가 그대로 나간다(API.md는 +09:00 문자열)
        return jdbc.queryForList("""
                select p.id, p.name, p.source,
                       c.brand, c.category, c.image_url,
                       to_char(p.created_at at time zone 'Asia/Seoul',
                               'YYYY-MM-DD"T"HH24:MI:SS+09:00') as created_at
                  from products p
                  left join catalog_products c on c.id = p.catalog_id
                 order by p.created_at, p.id
                """);
    }

    /**
     * 배지에 쓸 주요 성분. 카탈로그 제품은 뷰가, OCR 제품은 product_ingredients가 출처다.
     * 제외 목록(정제수·글리세린 등)은 양쪽 모두에 같은 기준으로 적용된다.
     */
    private Map<UUID, List<String>> keyIngredients(JdbcTemplate jdbc) {
        Map<UUID, List<String>> out = new HashMap<>();

        jdbc.queryForList("""
                select p.id, k.std_name
                  from products p
                  join catalog_key_ingredients k on k.catalog_id = p.catalog_id
                 where k.rank <= ?
                 order by p.id, k.rank
                """, KEY_INGREDIENTS)
                .forEach(r -> out.computeIfAbsent((UUID) r.get("id"), x -> new ArrayList<>())
                        .add((String) r.get("std_name")));

        jdbc.queryForList("""
                select pi.product_id as id, i.std_name
                  from product_ingredients pi
                  join ingredients i on i.id = pi.ingredient_id
                 where not exists (select 1 from key_ingredient_excluded e
                                    where e.std_name = i.std_name)
                 order by pi.product_id, pi.position
                """)
                .forEach(r -> {
                    List<String> list = out.computeIfAbsent((UUID) r.get("id"), x -> new ArrayList<>());
                    if (list.size() < KEY_INGREDIENTS) {
                        list.add((String) r.get("std_name"));
                    }
                });

        return out;
    }

    // ── 4. 등록 ────────────────────────────────────────────────

    public Map<String, Object> add(ProductDto.CreateRequest req) {
        String userId = SecurityConfig.currentUserId();

        boolean hasCatalog = req != null && req.catalogIds() != null && !req.catalogIds().isEmpty();
        boolean hasOcr = req != null && req.ocrProduct() != null;
        if (hasCatalog == hasOcr) {
            // 둘 다 비면 등록할 게 없고, 둘 다 오면 어느 쪽이 의도인지 알 수 없다.
            // 예전 구현은 조용히 added:0 / 201을 돌려줘서 프론트가 성공으로 오인했다
            throw new ApiException(ErrorCode.VALIDATION_ERROR,
                    "catalogIds 또는 ocrProduct 중 하나만 보내 주세요.");
        }

        if (hasCatalog && req.catalogIds().size() > MAX_CATALOG_IDS) {
            throw new ApiException(ErrorCode.VALIDATION_ERROR,
                    "한 번에 " + MAX_CATALOG_IDS + "개까지 담을 수 있습니다.");
        }

        return rls.asUser(userId, jdbc -> {
            boolean sampleCleared = clearSampleIfNeeded(jdbc);
            checkCapacity(jdbc, hasCatalog ? req.catalogIds().size() : 1);
            List<Map<String, Object>> created =
                    hasCatalog ? addCatalog(jdbc, userId, req.catalogIds())
                               : addOcr(jdbc, userId, req.ocrProduct());

            Map<String, Object> out = new LinkedHashMap<>();
            out.put("added", created.size());
            out.put("sampleCleared", sampleCleared);
            out.put("items", created);
            return out;
        });
    }

    /** 등록 시점에 화장대가 샘플뿐이면 통째로 비운다(API.md 4의 서버 규칙). */
    private boolean clearSampleIfNeeded(JdbcTemplate jdbc) {
        Integer total = jdbc.queryForObject("select count(*) from products", Integer.class);
        Integer sample = jdbc.queryForObject(
                "select count(*) from products where source = 'SAMPLE'", Integer.class);
        if (total == null || sample == null || total == 0 || !total.equals(sample)) {
            return false;
        }
        jdbc.update("delete from products where source = 'SAMPLE'");
        return true;
    }

    /** 샘플을 비운 뒤에 센다. 샘플 13종 때문에 상한에 걸리는 일이 없어야 한다. */
    private void checkCapacity(JdbcTemplate jdbc, int adding) {
        Integer now = jdbc.queryForObject("select count(*) from products", Integer.class);
        int have = now == null ? 0 : now;
        if (have + adding > MAX_PRODUCTS) {
            throw new ApiException(ErrorCode.VANITY_FULL,
                    "화장대에는 " + MAX_PRODUCTS + "개까지 담을 수 있습니다. 쓰지 않는 제품을 지워 주세요.");
        }
    }

    private List<Map<String, Object>> addCatalog(JdbcTemplate jdbc, String userId, List<Long> ids) {
        // 요청 안에서 겹치는 것부터 거른다. DB를 보기 전에 잡히는 쪽이 메시지가 정확하다
        if (ids.stream().distinct().count() != ids.size()) {
            throw new ApiException(ErrorCode.DUPLICATE_PRODUCT, "같은 제품이 여러 번 들어 있습니다.");
        }

        List<Map<String, Object>> out = new ArrayList<>();
        for (Long catalogId : ids) {
            if (catalogId == null) {
                throw new ApiException(ErrorCode.VALIDATION_ERROR, "catalogId가 비어 있습니다.");
            }
            Integer dup = jdbc.queryForObject(
                    "select count(*) from products where catalog_id = ?", Integer.class, catalogId);
            if (dup != null && dup > 0) {
                throw new ApiException(ErrorCode.DUPLICATE_PRODUCT,
                        "이미 화장대에 있는 제품입니다.");
            }
            List<Map<String, Object>> found = jdbc.queryForList(
                    "select name from catalog_products where id = ?", catalogId);
            if (found.isEmpty()) {
                // 조용히 건너뛰면 added가 줄어든 이유를 프론트가 알 수 없다
                throw new ApiException(ErrorCode.PRODUCT_NOT_FOUND,
                        "카탈로그에 없는 제품입니다: " + catalogId);
            }
            String name = (String) found.get(0).get("name");
            UUID id = jdbc.queryForObject("""
                    insert into products (user_id, catalog_id, name, source)
                    values (?::uuid, ?, ?, 'CATALOG')
                    returning id
                    """, UUID.class, userId, catalogId, name);
            out.add(item(id, name));
        }
        return out;
    }

    /**
     * 사진으로 등록. 6번 응답을 그대로 받는다.
     *
     * <p>성분을 {@code product_ingredients}에 함께 넣는다. 이게 없으면 제품은 등록되는데
     * 충돌 검사(M3)와 루틴 생성이 그 제품의 성분을 못 읽는다 — FastAPI가 OCR 제품의 성분을
     * 이 테이블에서 찾는다({@code supa.py}).
     *
     * <p>매칭 실패분도 {@code raw_name}으로 남긴다. 표준명을 못 찾았을 뿐 화면에는 보여야 하고,
     * 나중에 성분 사전이 늘면 다시 이어 붙일 수 있다.
     */
    private List<Map<String, Object>> addOcr(JdbcTemplate jdbc, String userId,
                                             ProductDto.OcrProduct ocr) {
        String alias = ocr.alias() == null ? "" : ocr.alias().trim();
        if (alias.isEmpty()) {
            throw new ApiException(ErrorCode.VALIDATION_ERROR, "제품 이름을 입력해 주세요.");
        }
        if (alias.length() > MAX_ALIAS) {
            throw new ApiException(ErrorCode.VALIDATION_ERROR,
                    "제품 이름은 " + MAX_ALIAS + "자까지 입력할 수 있습니다.");
        }
        List<ProductDto.OcrIngredient> raw =
                ocr.ingredients() == null ? List.of() : ocr.ingredients();
        List<ProductDto.OcrIngredient> ingredients = raw.stream()
                .filter(x -> x != null && x.display() != null && !x.display().isEmpty())
                .toList();
        if (ingredients.isEmpty()) {
            throw new ApiException(ErrorCode.VALIDATION_ERROR, "성분이 하나도 없습니다.");
        }
        if (ingredients.size() > MAX_INGREDIENTS) {
            throw new ApiException(ErrorCode.VALIDATION_ERROR,
                    "성분은 " + MAX_INGREDIENTS + "개까지 등록할 수 있습니다.");
        }

        // catalog_id는 null이어야 한다 — products의 (source = 'OCR') = (catalog_id is null) 제약
        UUID productId = jdbc.queryForObject("""
                insert into products (user_id, catalog_id, name, source)
                values (?::uuid, null, ?, 'OCR')
                returning id
                """, UUID.class, userId, alias);

        Map<String, Long> matched = lookup(jdbc, ingredients);

        List<Object[]> batch = new ArrayList<>();
        for (int i = 0; i < ingredients.size(); i++) {
            ProductDto.OcrIngredient ing = ingredients.get(i);
            String toMatch = ing.toMatch();
            batch.add(new Object[]{productId, i, ing.display(),
                    toMatch == null ? null : matched.get(toMatch)});
        }
        jdbc.batchUpdate("""
                insert into product_ingredients (product_id, position, raw_name, ingredient_id)
                values (?, ?, ?, ?)
                """, batch);

        return List.of(item(productId, alias));
    }

    /** 표준명 → ingredients.id. 한 번에 조회한다(성분이 40~60개라 건별 조회는 왕복이 아깝다). */
    private Map<String, Long> lookup(JdbcTemplate jdbc, List<ProductDto.OcrIngredient> ingredients) {
        List<String> names = ingredients.stream()
                .map(ProductDto.OcrIngredient::toMatch)
                .filter(n -> n != null)
                .distinct()
                .toList();
        Map<String, Long> out = new HashMap<>();
        if (names.isEmpty()) {
            return out;
        }
        jdbc.queryForList("select id, std_name from ingredients where std_name = any(?)",
                        (Object) names.toArray(new String[0]))
                .forEach(r -> out.put((String) r.get("std_name"), ((Number) r.get("id")).longValue()));
        return out;
    }

    private Map<String, Object> item(UUID id, String name) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("productId", id.toString());
        m.put("name", name);
        return m;
    }

    // ── 7. 삭제 ────────────────────────────────────────────────

    public void delete(UUID productId) {
        String userId = SecurityConfig.currentUserId();
        // where user_id 조건이 없다. 남의 제품이면 RLS가 걸러 0행이 되고 404가 나간다
        int deleted = rls.asUser(userId,
                jdbc -> jdbc.update("delete from products where id = ?", productId));
        if (deleted == 0) {
            throw new ApiException(ErrorCode.PRODUCT_NOT_FOUND);
        }
    }
}
