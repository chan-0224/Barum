-- 제품 카탈로그 (M1 주 경로). 왕종휘가 수집한 결과가 들어가는 곳.
-- 적용 순서: ingredients.sql → core.sql → catalog.sql
-- 성분 정규화: python scripts/match_catalog_ingredients.py

create table if not exists catalog_products (
  id               bigserial primary key,
  brand            text not null,
  name             text not null,
  category         text not null
                   constraint catalog_products_category_check
                   check (category in ('CLEANSER', 'TONER', 'SERUM', 'CREAM', 'SUNSCREEN')),
  image_url        text,
  raw_ingredients  text,   -- 수집 원문(전성분 문자열). 여기서 아래 테이블을 채운다
  -- 쇼핑몰 표기 그대로의 제품명. name은 마케팅 문구를 걷어낸 정리본이다.
  -- 정규화 규칙을 고쳐 다시 돌리려면 원문이 있어야 한다
  name_raw         text,
  created_at       timestamptz not null default now(),

  -- 같은 브랜드에 같은 이름이 두 번 들어가는 사고를 막는다. 수집을 여러 번 돌려도 안전
  unique (brand, name)
);

-- 전성분 1줄 = 1행. products의 product_ingredients와 같은 구조로 맞췄다.
create table if not exists catalog_product_ingredients (
  catalog_id     bigint not null references catalog_products(id) on delete cascade,
  position       int    not null,   -- 표기 순서(0부터). 앞쪽이 주성분 = keyIngredients 산출 기준
  raw_name       text   not null,   -- 매칭 실패해도 원문 보존
  ingredient_id  bigint references ingredients(id),  -- 표준명 매칭 결과. 실패 시 null
  primary key (catalog_id, position)
);
-- position이 PK 구성 컬럼이라 NOT NULL이어야 한다. docs에는 nullable로 적혀 있으나 성립 불가.

-- ponytail: 인덱스는 PK/FK만. 카탈로그가 올리브영 상위 100개 규모라 어떤 조회든 순차 스캔이 즉시 끝난다.
--   검색(GET /catalog/products?q=)이 느려지면 그때 pg_trgm 인덱스를 추가하면 된다.

alter table catalog_products            enable row level security;
alter table catalog_product_ingredients enable row level security;

-- 참조 테이블이다. 전원 읽기 가능, 쓰기는 service_role만(RLS 우회)
drop policy if exists "catalog read for all" on catalog_products;
create policy "catalog read for all" on catalog_products for select using (true);

drop policy if exists "catalog ingredients read for all" on catalog_product_ingredients;
create policy "catalog ingredients read for all" on catalog_product_ingredients for select using (true);


-- 이미 만든 테이블에 반영할 때 (최초 생성이면 위 create가 처리한다)
alter table catalog_products add column if not exists name_raw text;


-- ── products에 출처 컬럼 추가 (core.sql의 정의와 맞춘다) ──────────────
-- 신규 설치는 core.sql이 처리한다. 아래는 이미 만든 DB용 마이그레이션.

alter table products add column if not exists
  catalog_id bigint references catalog_products(id) on delete set null;

alter table products add column if not exists source text;

-- source에 default를 두지 않는다. isSample 배지가 "보유 제품이 전부 SAMPLE인가"로 결정되는데,
-- 기본값이 있으면 등록 경로를 잘못 기록해도 조용히 통과해 배지가 틀린다. 넣는 쪽이 명시하게 한다.
update products set source = 'OCR' where source is null;  -- 기존 행 보정(현재 0건)
alter table products alter column source set not null;

alter table products drop constraint if exists products_source_check;
alter table products add constraint products_source_check
  check (source in ('SAMPLE', 'CATALOG', 'OCR'));

-- 카탈로그에서 등록한 건 catalog_id가 있어야 하고, OCR로 등록한 건 없어야 한다
alter table products drop constraint if exists products_source_catalog_check;
alter table products add constraint products_source_catalog_check
  check ((source = 'OCR') = (catalog_id is null));

create index if not exists products_catalog_idx on products (catalog_id);
