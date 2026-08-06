-- 성분 사전. 식약처 화장품 원료성분정보(15111774) 21,863건을 그대로 적재한다.
-- 참조 데이터라 유저별 격리 대상이 아니다. 읽기는 전원 허용, 쓰기는 service_role만(RLS 우회).
-- 적재: python load_ingredients.py

create table if not exists ingredients (
  id          bigserial primary key,
  std_name    text not null unique,  -- INGR_KOR_NAME. 전성분표에 인쇄되는 표준명 = OCR 매칭 키
  eng_name    text,                  -- INGR_ENG_NAME          (채움률 94.2%)
  synonym     text,                  -- INGR_SYNONYM 이명       (16.5%, 복수는 쉼표 구분)
  cas_no      text,                  -- CAS_NO                 (7.2%)
  origin_def  text,                  -- ORIGIN_MAJOR_KOR_NAME 기원 및 정의 (99.7%)
  created_at  timestamptz not null default now()
);

-- std_name의 unique 인덱스가 곧 OCR 완전일치 조회 경로다.
-- ponytail: OCR 오독 보정은 일단 이명(synonym) 폴백까지만. 완전일치+이명으로 부족하면
--   create extension pg_trgm; create index on ingredients using gin (std_name gin_trgm_ops);
--   한 줄로 유사도 검색 추가 가능. OCR 스파이크 결과 보고 결정.

alter table ingredients enable row level security;

drop policy if exists "ingredients read for all" on ingredients;
create policy "ingredients read for all" on ingredients for select using (true);
