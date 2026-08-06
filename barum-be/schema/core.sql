-- 바름 코어 스키마. M1(화장대) · M2(루틴) · M4(타임라인)이 전부 여기 의존한다.
-- 적용 순서: ingredients.sql → core.sql
--
-- users 테이블은 만들지 않는다.
--   Supabase 익명 로그인이 auth.users에 행을 만들어주고, MVP에 프로필 데이터가 없다.
--   별도 users 테이블은 지금 시점에 auth.users의 id를 복사만 하는 빈 껍데기가 된다.
--   닉네임·피부타입 같은 프로필이 생기면 그때 profiles 테이블을 추가하면 된다.
--   격리는 전부 auth.uid() 기준이라 users 테이블 유무와 무관하게 동작한다.

-- ── M1: 내 화장대 ────────────────────────────────────────────────
create table if not exists products (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  name        text not null,              -- 사용자 입력 또는 OCR 추정. "수분 세럼" 수준이면 충분
  image_path  text,                       -- 비공개 버킷 'labels' 내 경로. 원칙 5
  created_at  timestamptz not null default now()
);
create index if not exists products_user_idx on products (user_id, created_at desc);

-- 전성분표 1줄 = 1행. 기재 순서가 곧 함량 순서라 position을 보존한다.
create table if not exists product_ingredients (
  product_id     uuid not null references products(id) on delete cascade,
  position       int  not null,           -- 전성분표상 순서(0부터). 앞쪽이 주성분
  raw_name       text not null,           -- OCR이 읽은 원문. 매칭 실패해도 버리지 않는다
  ingredient_id  bigint references ingredients(id),  -- 매칭 실패 시 null
  primary key (product_id, position)
);
-- 룰테이블 충돌 검사가 "이 성분을 가진 내 제품들"을 역조회한다
create index if not exists product_ingredients_ingredient_idx
  on product_ingredients (ingredient_id);

-- ── M2/M4: 데일리 기록 ───────────────────────────────────────────
create table if not exists daily_records (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  record_date   date not null default (now() at time zone 'Asia/Seoul')::date,
  selfie_path   text,                     -- 비공개 버킷 'selfies' 내 경로. 원칙 5
  skin_context  jsonb,                    -- 비전 판독 {dry, oily, redness, trouble}
  weather       jsonb,                    -- get_daily_context() 반환값 통째로
  routine       jsonb,                    -- 생성된 루틴 카드 {apply[], skip[], reason}
  created_at    timestamptz not null default now(),
  unique (user_id, record_date)           -- 하루 한 장. 다시 찍으면 upsert
);
-- M4 타임라인: 최근 7일 역순 조회
create index if not exists daily_records_timeline_idx
  on daily_records (user_id, record_date desc);

-- weather/skin_context/routine을 jsonb로 둔 이유: 셋 다 아직 모양이 바뀐다.
-- 컬럼으로 쪼개면 프롬프트 튜닝할 때마다 마이그레이션이 따라온다.
-- 조회 조건으로 쓰이지 않고 통째로 읽고 쓰기만 하므로 jsonb가 손해가 없다.

-- ── RLS: 원칙 4. 격리는 전부 auth.uid() = user_id ─────────────────
alter table products            enable row level security;
alter table product_ingredients enable row level security;
alter table daily_records       enable row level security;

drop policy if exists "own products" on products;
create policy "own products" on products
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "own daily_records" on daily_records;
create policy "own daily_records" on daily_records
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- product_ingredients에는 user_id가 없다. 부모 products를 통해 소유권을 판정한다.
drop policy if exists "own product_ingredients" on product_ingredients;
create policy "own product_ingredients" on product_ingredients
  for all using (
    exists (select 1 from products p where p.id = product_id and p.user_id = auth.uid())
  ) with check (
    exists (select 1 from products p where p.id = product_id and p.user_id = auth.uid())
  );

-- ── Storage: 원칙 5. 얼굴 사진은 민감정보 → 비공개 버킷 + Signed URL ──
insert into storage.buckets (id, name, public) values ('selfies', 'selfies', false)
  on conflict (id) do update set public = false;
insert into storage.buckets (id, name, public) values ('labels', 'labels', false)
  on conflict (id) do update set public = false;

-- 경로 규약: {user_id}/{파일명}. 첫 폴더가 본인 uid일 때만 접근 허용
drop policy if exists "own files" on storage.objects;
create policy "own files" on storage.objects
  for all using (
    bucket_id in ('selfies', 'labels')
    and (storage.foldername(name))[1] = auth.uid()::text
  ) with check (
    bucket_id in ('selfies', 'labels')
    and (storage.foldername(name))[1] = auth.uid()::text
  );
