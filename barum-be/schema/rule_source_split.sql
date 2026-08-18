-- source를 sourceLabel / sourceUrl로 나눈다 (M3).
-- 적용 순서: ingredient_rules.sql → rule_source_split.sql
--
-- 왜
--   source가 "The Ordinary 공식 레티노이드 가이드 https://..." 처럼 설명과 URL이 한 문자열이라
--   프론트가 정규식으로 잘라 링크를 만들어야 했고, 그러다 "이유 보기"가 404로 깨졌다.
--   게다가 54건 중 17건은 URL이 아예 없다(논문 인용, DOI만) — 문자열 전체를 href에 넣으면
--   그 17건은 링크가 될 수 없다. 파싱을 클라이언트에 맡길 일이 아니라 서버가 나눠서 준다.
--
-- 기존 source 컬럼은 지우지 않는다. 프론트가 이미 쓰고 있어 지우면 그 자리에서 깨진다.

alter table ingredient_rules add column if not exists source_label text;
alter table ingredient_rules add column if not exists source_url   text;

-- 첫 http(s) 링크를 URL로, 그걸 걷어낸 나머지를 라벨로.
-- URL이 없으면 source_url은 null이고 라벨이 곧 인용 문구가 된다.
update ingredient_rules
   set source_url   = substring(source from 'https?://[^[:space:]]+'),
       source_label = nullif(btrim(regexp_replace(source, 'https?://[^[:space:]]+', '', 'g')), '')
 where source_label is null;

-- 라벨이 비는 경우(= source가 URL 하나뿐)는 URL을 그대로 라벨로 쓴다. 화면에 빈 칸이 남지 않게
update ingredient_rules
   set source_label = source_url
 where source_label is null and source_url is not null;

alter table ingredient_rules alter column source_label set not null;

-- 되돌리려면
--   alter table ingredient_rules drop column if exists source_label, drop column if exists source_url;
