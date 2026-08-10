-- 성분 조합 룰테이블 (M3). 원칙 1: 안전 판정은 결정론적으로.
-- LLM은 이 표의 판정 결과를 설명만 한다. 판정 자체를 LLM에 맡기지 않는다.
-- 적용 순서: ingredients.sql → ingredient_rules.sql
-- 적재: python scripts/load_rules.py

create table if not exists ingredient_rules (
  id            bigserial primary key,
  ingredient_a  text not null references ingredients(std_name),
  ingredient_b  text not null references ingredients(std_name),
  -- 2단계만 쓴다. 바름은 아침 루틴만 제시하므로 "시간대를 나눠 쓰세요"(구 CAUTION)라는
  -- 지시 자체가 성립하지 않는다. 오늘 같이 바르지 말 것인가, 같이 발라도 좋은가 둘뿐이다.
  level         text not null
                constraint ingredient_rules_level_check check (level in ('AVOID', 'GOOD')),
  label         text not null,   -- "같이 쓰지 마세요" — 배지에 그대로 노출
  reason        text not null,   -- 한 문장. 사용자에게 그대로 보인다
  source        text not null,   -- 근거 출처. 발표에서 "근거 기반"의 증거로 쓴다
  verified      boolean not null default false,  -- 원문을 열어 확인했는가. 발표 인용은 true만
  created_at    timestamptz not null default now(),
  unique (ingredient_a, ingredient_b),

  -- 정렬된 쌍만 저장해 (A,B)와 (B,A)가 동시에 들어가는 걸 막는다.
  -- COLLATE "C"는 바이트 순서 = 파이썬 sorted()와 동일. 로케일에 따라 결과가 달라지지 않는다.
  constraint ingredient_rules_sorted_pair
    check (ingredient_a collate "C" < ingredient_b collate "C")
);

-- ingredients(std_name)에 FK를 건 이유:
--   룰에 DB에 없는 성분명을 쓰면 매칭이 영원히 안 되는데, 조용히 실패한다.
--   FK가 있으면 적재 시점에 터진다. 실제로 벤조일퍼옥사이드·아젤라익애씨드가 여기서 걸렀다
--   (둘 다 국내에서는 의약품이라 화장품 원료 목록에 없음).

-- 조회 패턴: ingredient_a IN (...) AND ingredient_b IN (...)
-- unique 인덱스가 (a, b) 순이라 a 조건이 인덱스를 탄다. b는 필터.
create index if not exists ingredient_rules_b_idx on ingredient_rules (ingredient_b);

-- 이미 만든 테이블에 반영할 때 (최초 생성이면 위 create가 처리한다)
alter table ingredient_rules add column if not exists verified boolean not null default false;

-- CAUTION 폐지: 3단계 → 2단계
delete from ingredient_rules where level = 'CAUTION';
alter table ingredient_rules drop constraint if exists ingredient_rules_level_check;
alter table ingredient_rules add constraint ingredient_rules_level_check
  check (level in ('AVOID', 'GOOD'));

alter table ingredient_rules enable row level security;

drop policy if exists "ingredient_rules read for all" on ingredient_rules;
create policy "ingredient_rules read for all" on ingredient_rules for select using (true);
