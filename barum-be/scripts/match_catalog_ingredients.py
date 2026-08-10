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

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# 전성분표 표기에 흔히 붙는 군더더기. 성분명 자체가 아니다
_NOISE = re.compile(r"\s*[\(（][^)）]*[\)）]\s*|\s*\d+(\.\d+)?\s*%|\s*[\[\]]|\s*등$|\s*외\s*\d+\s*종$")

# 구분자 쉼표만 자른다. 숫자 사이 쉼표는 성분명의 일부다 — 1,2-헥산다이올은 국내 화장품에
# 대단히 흔하고, 쪼개면 "1"과 "2-헥산다이올" 둘 다 쓰레기가 된다.
_SEP = re.compile(r"[\n·•;]|,(?![0-9])|(?<![0-9]),")


def split_ingredients(raw: str) -> list[str]:
    """전성분 원문 → 성분명 목록.

    괄호 주석("향료(리모넨)" → "향료")과 함량 표기("나이아신아마이드 2%")는 떼어낸다.
    """
    out = []
    for token in _SEP.split(raw or ""):
        name = _NOISE.sub("", token or "").strip().strip(".·")
        # 숫자 조각이나 한 글자는 성분명이 아니다. 이런 게 이명 인덱스에 우연히 걸리면
        # 없는 성분이 제품에 등록되고 충돌 판정까지 오염된다(원칙 1).
        if len(name) >= 2 and not name.isdigit():
            out.append(name)
    return out


def build_index(rows: list[dict]) -> tuple[dict, dict]:
    """(표준명 → id, 이명 → id). 이명은 쉼표로 분해해 완전일치로만 쓴다.

    부분일치(ilike)를 쓰면 '가지추출물'이 '잔가지추출물'에 걸린다 — data/README.md 참조.
    """
    by_std = {r["std_name"]: r["id"] for r in rows}
    by_syn = {}
    for r in rows:
        # 이명도 같은 규칙으로 분해한다. 단순 split(",")을 쓰면 "1,10-데칸디올"이
        # "1"과 "10-데칸디올"로 쪼개져 by_syn["1"]이 생기고, 전성분에서 떨어져 나온
        # 숫자 조각이 여기에 걸려 엉뚱한 성분으로 매칭된다.
        for syn in split_ingredients(r.get("synonym") or ""):
            if syn not in by_std:  # 표준명이 우선한다
                by_syn.setdefault(syn, r["id"])
    return by_std, by_syn


def match(name: str, by_std: dict, by_syn: dict) -> int | None:
    """표준명 완전일치 → 이명 완전일치 → 공백 제거 후 재시도."""
    if name in by_std:
        return by_std[name]
    if name in by_syn:
        return by_syn[name]
    squeezed = name.replace(" ", "")
    return by_std.get(squeezed) or by_syn.get(squeezed)


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
    assert split_ingredients("나이아신아마이드 2%, 향료(리모넨)") == ["나이아신아마이드", "향료"]
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
