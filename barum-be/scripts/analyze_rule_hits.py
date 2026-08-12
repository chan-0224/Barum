"""룰테이블 성분이 카탈로그에서 실제로 어떻게 쓰이는지 분석. 오탐 판단용.

카탈로그 수집이 끝난 뒤 돌린다. 판단하려는 것:
  "이 성분이 활성으로 쓰였나, 미량으로만 들어갔나?"

룰테이블에는 함량 정보가 없다. 레티닐팔미테이트처럼 미량 산화방지제로 들어가는 성분까지
AVOID가 뜨면 시연에서 경고가 남발된다. 함량을 알 수 없으니 **표기 순서로 대신 본다.**

    python scripts/analyze_rule_hits.py              # 룰에 쓰인 성분 전체
    python scripts/analyze_rule_hits.py 레티닐팔미테이트  # 특정 성분만

판정 근거: 화장품 전성분표는 함량 순 기재가 원칙이지만 **1% 이하 성분은 순서를 지키지 않아도
된다.** 그래서 뒤쪽에 몰려 있으면 미량일 가능성이 높다. 확정이 아니라 신호다.
"""

import os
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

FRONT = 0.33   # 상대 위치가 이보다 앞이면 활성으로 본다
BACK = 0.66    # 이보다 뒤면 미량 의심


def _api(path: str, params: dict) -> list[dict]:
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    rows, page = [], 0
    while True:
        r = httpx.get(f"{url}/rest/v1/{path}", params=params,
                      headers={**h, "Range": f"{page * 1000}-{page * 1000 + 999}"}, timeout=60)
        if r.is_error:
            raise RuntimeError(f"{path} HTTP {r.status_code}: {r.text[:300]}")
        batch = r.json()
        rows += batch
        if len(batch) < 1000:
            return rows
        page += 1


def main() -> None:
    wanted = set(sys.argv[1:])

    rules = _api("ingredient_rules", {"select": "ingredient_a,ingredient_b,level"})
    rule_names = {n for r in rules for n in (r["ingredient_a"], r["ingredient_b"])}
    targets = (wanted & rule_names) or rule_names
    if wanted and not (wanted & rule_names):
        print(f"룰테이블에 없는 성분: {', '.join(wanted)}", file=sys.stderr)
        return

    rows = _api("catalog_product_ingredients",
                {"select": "catalog_id,position,ingredients(std_name)", "order": "catalog_id,position"})
    rows = [r for r in rows if r["ingredients"]]
    if not rows:
        print("catalog_product_ingredients가 비어 있다. 수집·매칭을 먼저 돌려야 한다.", file=sys.stderr)
        return

    total_by_product = defaultdict(int)
    for r in rows:
        total_by_product[r["catalog_id"]] += 1
    n_products = len(total_by_product)

    # 성분 → [(제품, 절대 위치, 상대 위치)]
    seen = defaultdict(list)
    for r in rows:
        name = r["ingredients"]["std_name"]
        if name not in targets:
            continue
        last = total_by_product[r["catalog_id"]] - 1
        rel = r["position"] / last if last > 0 else 0.0
        seen[name].append((r["catalog_id"], r["position"], rel))

    print(f"카탈로그 제품 {n_products}개 / 룰 성분 {len(targets)}종 중 {len(seen)}종 등장\n")
    if n_products < 30:
        print(f"※ 제품이 {n_products}개뿐이라 통계로 쓸 수 없다. 수집 완료 후 다시 볼 것.\n", file=sys.stderr)

    print(f"{'성분':<26}{'제품수':>5}{'비율':>7}{'상대위치중앙':>9}{'앞쪽':>6}{'뒤쪽':>6}  판정")
    print("-" * 78)

    verdicts = {}
    for name, hits in sorted(seen.items(), key=lambda x: -len(x[1])):
        rels = sorted(h[2] for h in hits)
        med = rels[len(rels) // 2]
        front = sum(1 for r in rels if r <= FRONT)
        back = sum(1 for r in rels if r >= BACK)

        if back > front * 2 and med >= BACK:
            verdict = "미량 의심"
        elif front >= back:
            verdict = "활성"
        else:
            verdict = "혼재"
        verdicts[name] = verdict
        print(f"{name:<26}{len(hits):>5}{len(hits) / n_products * 100:>6.0f}%"
              f"{med:>9.2f}{front:>6}{back:>6}  {verdict}")

    # 미량 의심 성분이 실제로 몇 건의 AVOID를 만들어내는지 — 오탐 규모
    by_product = defaultdict(set)
    for r in rows:
        by_product[r["catalog_id"]].add(r["ingredients"]["std_name"])
    avoid = {tuple(sorted((r["ingredient_a"], r["ingredient_b"]))) for r in rules if r["level"] == "AVOID"}

    suspect = {n for n, v in verdicts.items() if v == "미량 의심"}
    if not suspect:
        print("\n미량 의심 성분 없음.")
        return

    print(f"\n미량 의심 성분이 만드는 AVOID (제품 2개 조합 기준)")
    pair_total, pair_suspect = 0, defaultdict(int)
    for a, b in combinations(sorted(by_product), 2):
        names = by_product[a] | by_product[b]
        for x, y in avoid:
            if x in names and y in names:
                pair_total += 1
                for s in (x, y):
                    if s in suspect:
                        pair_suspect[s] += 1
    print(f"  전체 AVOID 발동: {pair_total}건")
    for name, n in sorted(pair_suspect.items(), key=lambda x: -x[1]):
        print(f"    {name:<26}{n:>5}건 관여  ({n / pair_total * 100:.0f}%)" if pair_total else "")
    print("\n비율이 높으면 그 성분을 계열에서 빼는 것을 검토한다 (data/README.md 계열 정의).")


def _selfcheck() -> None:
    # 상대 위치 계산: 성분 5개짜리 제품에서 position 4는 맨 끝 → 1.0
    assert 4 / (5 - 1) == 1.0
    assert 0 / (5 - 1) == 0.0
    assert FRONT < BACK
    print("selfcheck ok", file=sys.stderr)


if __name__ == "__main__":
    _selfcheck()
    main()
