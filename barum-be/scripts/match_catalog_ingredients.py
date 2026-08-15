"""catalog_products.raw_ingredients(전성분 원문) → catalog_product_ingredients 정규화.

수집 담당자는 전성분 문자열만 넣으면 된다. 표준명 매칭은 이 스크립트가 한다.

    python scripts/match_catalog_ingredients.py --dry-run   # 매칭률만 확인
    python scripts/match_catalog_ingredients.py             # 실제 적재
    python scripts/match_catalog_ingredients.py --only 101  # 특정 제품만

매칭 실패해도 raw_name은 보존한다(ingredient_id만 null). 실패 목록을 봐야 개선된다.
필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import os
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# 분해·매칭 규칙은 matching.py가 단일 원본이다. OCR(api/ocr.py)도 같은 것을 쓴다
from matching import build_index, candidates, match, split_ingredients  # noqa: E402,F401


def _api(path: str, **kw) -> httpx.Response:
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    method = kw.pop("method", "GET")
    r = httpx.request(method, f"{url}/rest/v1/{path}", headers={**headers, **kw.pop("headers", {})},
                      timeout=60, **kw)
    if r.is_error:
        raise RuntimeError(f"{method} {path} HTTP {r.status_code}: {r.text[:300]}")
    return r


def fetch_ingredients() -> list[dict]:
    rows, page = [], 0
    while True:  # PostgREST 기본 상한이 1000이라 range로 끊어 받는다
        r = _api("ingredients", params={"select": "id,std_name,synonym", "order": "id"},
                 headers={"Range": f"{page * 1000}-{page * 1000 + 999}"})
        batch = r.json()
        rows += batch
        if len(batch) < 1000:
            return rows
        page += 1


def main() -> None:
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]

    params = {"select": "id,brand,name,raw_ingredients", "order": "id"}
    if only:
        params["id"] = f"eq.{only}"
    products = _api("catalog_products", params=params).json()
    if not products:
        print("catalog_products가 비어 있다. 수집 결과를 먼저 넣어야 한다.", file=sys.stderr)
        return

    by_std, by_syn = build_index(fetch_ingredients())
    print(f"성분 사전 {len(by_std)}종 + 이명 {len(by_syn)}종", file=sys.stderr)

    total, matched, unmatched_names = 0, 0, {}
    for p in products:
        names = split_ingredients(p.get("raw_ingredients") or "")
        if not names:
            print(f"  [{p['id']}] {p['brand']} {p['name']} — raw_ingredients 비어 있음", file=sys.stderr)
            continue

        rows = []
        for pos, name in enumerate(names):
            iid = match(name, by_std, by_syn)
            total += 1
            if iid:
                matched += 1
            else:
                unmatched_names[name] = unmatched_names.get(name, 0) + 1
            rows.append({"catalog_id": p["id"], "position": pos,
                         "raw_name": name, "ingredient_id": iid})

        hit = sum(1 for r in rows if r["ingredient_id"])
        print(f"  [{p['id']}] {p['brand']} {p['name']} — {hit}/{len(rows)} 매칭", file=sys.stderr)

        if "--dry-run" not in sys.argv:
            # 재실행이 안전하도록 해당 제품 행을 지우고 다시 넣는다(성분 순서가 바뀔 수 있다)
            _api("catalog_product_ingredients", method="DELETE",
                 params={"catalog_id": f"eq.{p['id']}"})
            _api("catalog_product_ingredients", method="POST", json=rows,
                 headers={"Prefer": "return=minimal"})

    rate = matched / total * 100 if total else 0
    print(f"\n제품 {len(products)}건 / 성분 {total}줄 중 {matched}줄 매칭 ({rate:.1f}%)")
    if unmatched_names:
        print(f"\n매칭 실패 상위 20종 (원문은 보존됨):")
        for name, n in sorted(unmatched_names.items(), key=lambda x: -x[1])[:20]:
            print(f"  {n:3}회  {name}")
    if "--dry-run" in sys.argv:
        print("\n--dry-run 이므로 적재하지 않았다.")


def _selfcheck() -> None:
    assert split_ingredients("정제수, 글리세린, 부틸렌글라이콜") == ["정제수", "글리세린", "부틸렌글라이콜"]
    assert split_ingredients("정제수·글리세린\n판테놀") == ["정제수", "글리세린", "판테놀"]
    # 괄호·함량은 split이 아니라 match의 후보 생성이 처리한다
    assert split_ingredients("나이아신아마이드 2%, 향료(리모넨)") == ["나이아신아마이드 2%", "향료(리모넨)"]
    assert "나이아신아마이드" in candidates("나이아신아마이드 2%")
    assert "향료" in candidates("향료(리모넨)")
    # 괄호까지가 표준명인 성분은 원형 그대로도 후보에 남아야 한다
    assert "하이드로제네이티드폴리(C6-14올레핀)" in candidates("하이드로제네이티드폴리(C6-14올레핀)")
    assert "레티놀" in candidates("레티놀 1,000IU/g")
    # 유기농 별표, 제품을 잇는 ■ 구분자
    assert split_ingredients("오렌지껍질오일**, 아시아티코사이드*") == ["오렌지껍질오일", "아시아티코사이드"]
    assert split_ingredients("리모넨 ■ 우르오스 정제수")[0] == "리모넨"
    assert split_ingredients("정제수, , 글리세린") == ["정제수", "글리세린"]
    assert split_ingredients("") == []
    # 숫자 사이 쉼표는 성분명의 일부다. 국내 화장품에 가장 흔한 함정
    assert split_ingredients("글리세린, 1,2-헥산다이올, 판테놀") == ["글리세린", "1,2-헥산다이올", "판테놀"]
    assert split_ingredients("부틸렌글라이콜,1,2-헥산다이올") == ["부틸렌글라이콜", "1,2-헥산다이올"]
    assert split_ingredients("2,4,5-트라이메틸아닐린, 정제수") == ["2,4,5-트라이메틸아닐린", "정제수"]

    rows = [
        {"id": 1, "std_name": "하이알루로닉애씨드", "synonym": "히알루론산"},
        {"id": 2, "std_name": "레티놀", "synonym": None},
        {"id": 3, "std_name": "리치추출물", "synonym": "리치열매추출물,여지열매추출물"},
        {"id": 4, "std_name": "1,10-데칸다이올", "synonym": "1,10-데칸디올"},
    ]
    by_std, by_syn = build_index(rows)
    assert match("레티놀", by_std, by_syn) == 2
    assert match("히알루론산", by_std, by_syn) == 1          # 이명 폴백
    assert match("여지열매추출물", by_std, by_syn) == 3       # 쉼표로 분해된 복수 이명
    assert match("하이알루로닉 애씨드", by_std, by_syn) == 1  # 공백 차이 보정
    assert match("없는성분", by_std, by_syn) is None
    # 이명이 숫자 조각으로 쪼개져 인덱스를 오염시키면 안 된다
    assert "1" not in by_syn and "10" not in by_syn, by_syn
    assert by_syn.get("1,10-데칸디올") == 4
    assert match("1", by_std, by_syn) is None
    print("selfcheck ok", file=sys.stderr)


if __name__ == "__main__":
    _selfcheck()
    main()
