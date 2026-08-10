-- keyIngredients(주요 성분 2~3개) 산출용 제외 목록.
-- 적용 순서: ingredients.sql → core.sql → catalog.sql → key_ingredients.sql
--
-- 왜 필요한가: 전성분표는 함량 순이라 앞쪽이 거의 항상 정제수·글리세린·부틸렌글라이콜이다.
--   그대로 3개를 뽑으면 모든 제품의 "주요 성분"이 똑같아 보인다(화면 6·8).
--   베이스·용매·점증제 계열을 걷어내고 그다음 성분을 뽑는다.
--
-- 주의: 이건 **화면 표시용**이다. 성분 충돌 판정(conflicts.py)은 제외 없이
--   product_ingredients 전체를 본다. 표시에서 감췄다고 판정에서 빠지면 안 된다.

create table if not exists key_ingredient_excluded (
  std_name  text primary key references ingredients(std_name),
  category  text not null
            constraint key_ingredient_excluded_category_check
            check (category in ('SOLVENT', 'POLYOL', 'SILICONE', 'EMULSIFIER',
                                'THICKENER', 'PRESERVATIVE', 'PH', 'FRAGRANCE_COLOR'))
);

-- ingredients(std_name) FK라 오타가 있으면 여기서 터진다. 조용히 안 걸러지는 일이 없다.
insert into key_ingredient_excluded (std_name, category) values
  -- 용매·베이스
  ('정제수', 'SOLVENT'), ('에탄올', 'SOLVENT'), ('변성알코올', 'SOLVENT'),
  ('프로판다이올', 'SOLVENT'), ('다이프로필렌글라이콜', 'SOLVENT'),
  -- 폴리올(보습 베이스). 활성이 아니라 용제·보습 기재로 쓰인다
  ('글리세린', 'POLYOL'), ('부틸렌글라이콜', 'POLYOL'), ('프로필렌글라이콜', 'POLYOL'),
  ('1,2-헥산다이올', 'POLYOL'), ('펜틸렌글라이콜', 'POLYOL'), ('카프릴릴글라이콜', 'POLYOL'),
  ('메틸프로판다이올', 'POLYOL'), ('글리세레스-26', 'POLYOL'),
  -- 실리콘(사용감 조절)
  ('다이메티콘', 'SILICONE'), ('사이클로펜타실록세인', 'SILICONE'),
  ('사이클로헥사실록세인', 'SILICONE'), ('다이메티콘올', 'SILICONE'), ('메티콘', 'SILICONE'),
  ('페닐트라이메티콘', 'SILICONE'), ('다이메티콘크로스폴리머', 'SILICONE'),
  -- 유화제·계면활성제
  ('세테아릴알코올', 'EMULSIFIER'), ('세틸알코올', 'EMULSIFIER'),
  ('글리세릴스테아레이트', 'EMULSIFIER'), ('피이지-100스테아레이트', 'EMULSIFIER'),
  ('세테아레스-20', 'EMULSIFIER'), ('하이드로제네이티드레시틴', 'EMULSIFIER'),
  ('코카미도프로필베타인', 'EMULSIFIER'), ('스테아릭애씨드', 'EMULSIFIER'),
  ('소듐라우로일메틸이세티오네이트', 'EMULSIFIER'),
  -- 점증제
  ('카보머', 'THICKENER'), ('잔탄검', 'THICKENER'),
  ('아크릴레이트/C10-30알킬아크릴레이트크로스폴리머', 'THICKENER'),
  ('암모늄아크릴로일다이메틸타우레이트/브이피코폴리머', 'THICKENER'),
  ('하이드록시에틸셀룰로오스', 'THICKENER'),
  -- 방부·킬레이트
  ('페녹시에탄올', 'PRESERVATIVE'), ('에틸헥실글리세린', 'PRESERVATIVE'),
  ('다이소듐이디티에이', 'PRESERVATIVE'), ('이디티에이', 'PRESERVATIVE'),
  ('클로페네신', 'PRESERVATIVE'), ('벤질알코올', 'PRESERVATIVE'),
  ('소듐벤조에이트', 'PRESERVATIVE'),
  -- pH 조절
  ('소듐하이드록사이드', 'PH'), ('시트릭애씨드', 'PH'), ('트라이에탄올아민', 'PH'),
  ('포타슘하이드록사이드', 'PH'), ('소듐시트레이트', 'PH'),
  -- 향·색소·부형
  ('향료', 'FRAGRANCE_COLOR'), ('리모넨', 'FRAGRANCE_COLOR'), ('리날룰', 'FRAGRANCE_COLOR'),
  ('제라니올', 'FRAGRANCE_COLOR'), ('마이카', 'FRAGRANCE_COLOR'), ('실리카', 'FRAGRANCE_COLOR'),
  ('적색201호', 'FRAGRANCE_COLOR'), ('황색4호', 'FRAGRANCE_COLOR')
on conflict (std_name) do nothing;

-- 일부러 넣지 않은 것 (활성 성분이라 감추면 안 된다)
--   티타늄디옥사이드 / 징크옥사이드 — 선크림에서는 이게 주인공이다
--   락틱애씨드 — pH 조절로도 쓰이지만 AHA 활성으로 내세우는 제품이 많다
--   토코페릴아세테이트 — 항산화 활성

alter table key_ingredient_excluded enable row level security;
drop policy if exists "key_ingredient_excluded read for all" on key_ingredient_excluded;
create policy "key_ingredient_excluded read for all" on key_ingredient_excluded
  for select using (true);


-- ── Spring이 그대로 조회하는 뷰 ────────────────────────────────────
-- 제외 로직을 Java에 넣지 않는다. 목록이 바뀌어도 재배포가 필요 없게.
create or replace view catalog_key_ingredients
with (security_invoker = on) as
select
  cpi.catalog_id,
  i.std_name,
  cpi.position,
  row_number() over (partition by cpi.catalog_id order by cpi.position) as rank
from catalog_product_ingredients cpi
join ingredients i on i.id = cpi.ingredient_id      -- 매칭 실패분(null)은 표시하지 않는다
where not exists (
  select 1 from key_ingredient_excluded e where e.std_name = i.std_name
);

grant select on catalog_key_ingredients to anon, authenticated;

-- 사용법 (API.md 2번 keyIngredients):
--   select std_name from catalog_key_ingredients
--    where catalog_id = ? and rank <= 3
--    order by rank;
