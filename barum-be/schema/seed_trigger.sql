-- 익명 계정이 만들어질 때 샘플 화장대를 채운다.
-- 적용 순서: catalog.sql → sample_vanity.sql → seed_trigger.sql
--
-- 왜 트리거인가
--   샘플 주입이 GET /products 안에 있었다. 그런데 루틴 생성(API.md 8)은 프론트가
--   FastAPI를 직접 부르기 때문에 Spring을 거치지 않는다. 첫 진입에서 곧바로 루틴을
--   요청하면 화장대가 비어 있어 EMPTY_VANITY가 떴다.
--
--   FastAPI가 대신 넣을 수는 없다 — 원칙 6(FastAPI는 DB에 쓰지 않는다).
--   Spring의 어느 엔드포인트에 넣어도 "그 엔드포인트를 먼저 부른다"는 가정이 남는다.
--   계정 생성 시점에 넣으면 어떤 경로로 들어와도 화장대가 이미 있다.
--
--   조회(GET)가 쓰기를 하던 구조도 같이 사라진다.

create or replace function public.seed_sample_vanity()
returns trigger
language plpgsql
security definer          -- products는 RLS가 걸려 있다. 트리거는 소유자 권한으로 넣는다
set search_path = public  -- search_path 탈취 방지
as $$
begin
  -- created_at을 position만큼 어긋나게 둔다. 한 문장으로 13행을 넣으면 now()가 전부 같아
  -- 정렬이 실행할 때마다 달라지는데, 그 순서가 화면 6에 그대로 보인다
  insert into products (user_id, catalog_id, name, source, created_at)
  select new.id, v.catalog_id, v.name, 'SAMPLE',
         now() + (v.position * interval '1 millisecond')
    from sample_vanity v;

  return new;
exception when others then
  -- 시드 실패가 회원 가입 자체를 막으면 안 된다. 카탈로그가 비었거나 뷰가 없을 때
  -- 로그인 전체가 죽는 것이 훨씬 나쁘다. Spring의 백업 시드가 다음 요청에서 채운다
  raise warning '샘플 화장대 시드 실패 (user %): %', new.id, sqlerrm;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created_seed_vanity on auth.users;
create trigger on_auth_user_created_seed_vanity
  after insert on auth.users
  for each row execute function public.seed_sample_vanity();

-- 되돌리려면
--   drop trigger if exists on_auth_user_created_seed_vanity on auth.users;
--   drop function if exists public.seed_sample_vanity();
