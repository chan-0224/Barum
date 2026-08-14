-- 체험용 샘플 화장대 (TASK 3). 최초 진입 시 자동 세팅되는 13종.
-- 적용 순서: catalog.sql → sample_vanity.sql
--
-- 카탈로그 id를 상수로 박지 않는다. bigserial이라 재적재하면 값이 바뀌고,
-- 실제로 수집분을 다시 넣을 때마다 두 번 바뀌었다. (brand, name)은 UNIQUE라 안정적이다.
-- 뷰가 조회 시점에 id를 찾아 주므로 카탈로그를 다시 적재해도 이 파일은 손댈 필요가 없다.
--
-- 구성 근거 (docs/SCREENS.md 전역 규칙)
--   - 5개 카테고리를 고루: 클렌저 2 · 토너 2 · 세럼 4 · 크림 3 · 선크림 2
--   - AVOID 조합 최소 1쌍: 이니스프리 레티놀 앰플 ↔ 코스알엑스 비타민C 세럼
--     (무작위 구성에서는 AVOID가 20% 확률로만 뜬다. 시연에서 경고 기능이 반드시 보여야 해서
--      두 제품을 의도적으로 넣었다)
--   - 실제 판정 결과: AVOID 1건 + GOOD 2건 (conflicts.py의 conflict_badges 기준)

create or replace view sample_vanity
with (security_invoker = on) as
select
  v.position,
  c.id   as catalog_id,
  c.brand,
  c.name,
  c.category
from (values
  ( 1, '비플레인',   '녹두 약산성 클렌징폼'),
  ( 2, '에스네이처',  '아쿠아 라이스 약산성 클렌징폼'),
  ( 3, '토리든',    '다이브인 저분자 히알루론산 토너'),
  ( 4, '넘버즈인',   '1번 진정 맑게담은 청초토너'),
  ( 5, '이니스프리',  '레티놀 시카 모공 흔적 앰플'),          -- ★ AVOID 보장
  ( 6, '코스알엑스',  '어드밴스드 더 비타민C 23 세럼'),       -- ★ AVOID 보장
  ( 7, '메디힐',    '마데카소사이드 더마 세럼'),
  ( 8, '에스트라',   '아토베리어365 세라-히알 속수분 앰플'),
  ( 9, '에스트라',   '아토베리어365 크림'),
  (10, '닥터지',    '레드블레미쉬 클리어 수딩크림 EX'),
  (11, '파티온',    '노스카나인 트러블 크림'),
  (12, '닥터지',    '그린 마일드 업 선 플러스'),
  (13, '구달',     '맑은 어성초 진정 수분 선크림')
) as v(position, brand, name)
join catalog_products c on c.brand = v.brand and c.name = v.name
order by v.position;

grant select on sample_vanity to anon, authenticated;


-- ── Spring에서 쓰는 법 (왕종휘) ─────────────────────────────────
--
-- 익명 세션이 처음 만들어질 때 한 번 실행한다. 이미 제품이 있으면 넣지 않는다.
--
--   insert into products (user_id, catalog_id, name, source)
--   select :userId, catalog_id, name, 'SAMPLE'
--     from sample_vanity
--    where not exists (select 1 from products where user_id = :userId);
--
-- source = 'SAMPLE' 이 중요하다.
--   - GET /products 의 isSample 이 "보유 제품이 전부 SAMPLE인가"로 결정된다(docs/API.md 3)
--   - 첫 제품 등록 시 샘플 전체를 지우는 규칙도 이 값으로 판단한다(docs/API.md 4)
--   - products에는 source 기본값이 없다. 반드시 명시할 것
--
-- catalog_id 를 채워야 하는 이유
--   - products의 제약: (source = 'OCR') = (catalog_id is null)
--     SAMPLE인데 catalog_id가 비면 DB가 거부한다
--   - 브랜드·이미지·주요 성분을 카탈로그에서 조인해 온다(GET /products)
--
-- 성분은 products에 복사하지 않는다. 충돌 판정은 catalog_product_ingredients를 타고 읽는다.
--
-- 확인
--   select count(*) from sample_vanity;   -- 13이어야 한다
--   13보다 적으면 카탈로그에서 해당 제품이 빠진 것이다(이름이 바뀌었거나 재적재에서 누락).
--   그 경우 아래로 어느 줄이 안 붙었는지 볼 수 있다:
--
--   select v.* from (values
--     ( 1, '비플레인', '녹두 약산성 클렌징폼') /* … 위 목록과 동일 … */
--   ) as v(position, brand, name)
--   left join catalog_products c on c.brand = v.brand and c.name = v.name
--   where c.id is null;
