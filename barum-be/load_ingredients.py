"""식약처 원료성분정보 21,863건 → Supabase ingredients 테이블 일괄 적재.

한 번 돌리면 끝나는 스크립트다. 서비스 런타임은 이 API를 호출하지 않고 DB만 조회한다.
성분 데이터는 갱신 주기가 길어서 재적재가 필요하면 그냥 다시 돌리면 된다(std_name 기준 upsert).

    python load_ingredients.py --dry-run   # 수집만 하고 건수 확인
    python load_ingredients.py             # 수집 + 적재

필요 환경변수: DATA_GO_KR_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
(service_role 키여야 RLS를 우회해 쓰기가 된다. 이 키는 절대 프론트에 넣지 말 것)
"""

import os
import sys

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

INGD_URL = "https://apis.data.go.kr/1471000/CsmtcsIngdCpntInfoService01/getCsmtcsIngdCpntInfoService01"
PAGE_SIZE = 500  # API 상한. 초과하면 resultCode 11
FIELDS = {
    "std_name": "INGR_KOR_NAME",
    "eng_name": "INGR_ENG_NAME",
    "synonym": "INGR_SYNONYM",
    "cas_no": "CAS_NO",
    "origin_def": "ORIGIN_MAJOR_KOR_NAME",
}


def fetch_all() -> list[dict]:
    key = os.environ["DATA_GO_KR_KEY"]
    rows, page = [], 1
    with httpx.Client(timeout=30) as client:
        while True:
            r = client.get(INGD_URL, params={
                "serviceKey": key, "pageNo": page, "numOfRows": PAGE_SIZE, "type": "json",
            })
            if r.is_error:
                raise RuntimeError(f"원료성분 API HTTP {r.status_code}: {r.text[:300]}")
            body = r.json()["body"]
            items = body.get("items") or []
            rows += items
            print(f"  {page}페이지 {len(rows)}/{body['totalCount']}", file=sys.stderr)
            if not items or len(rows) >= body["totalCount"]:
                return rows
            page += 1


def to_records(raw: list[dict]) -> list[dict]:
    out, seen = [], set()
    for item in raw:
        name = (item.get("INGR_KOR_NAME") or "").strip()
        if not name or name in seen:  # std_name은 NOT NULL UNIQUE
            continue
        seen.add(name)
        rec = {col: (item.get(src) or "").strip() or None for col, src in FIELDS.items()}
        rec["std_name"] = name
        out.append(rec)
    return out


def upsert(records: list[dict]) -> None:
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    with httpx.Client(timeout=60) as client:
        for i in range(0, len(records), 1000):
            chunk = records[i:i + 1000]
            r = client.post(f"{url}/rest/v1/ingredients?on_conflict=std_name",
                            headers=headers, json=chunk)
            if r.is_error:
                raise RuntimeError(f"적재 실패 (offset {i}) HTTP {r.status_code}: {r.text[:300]}")
            print(f"  적재 {i + len(chunk)}/{len(records)}", file=sys.stderr)


def _selfcheck():
    raw = [
        {"INGR_KOR_NAME": "레티놀", "INGR_ENG_NAME": "Retinol", "INGR_SYNONYM": None,
         "CAS_NO": "68-26-8", "ORIGIN_MAJOR_KOR_NAME": "..."},
        {"INGR_KOR_NAME": "레티놀", "INGR_ENG_NAME": "dup"},          # 중복 → 제거
        {"INGR_KOR_NAME": "  ", "INGR_ENG_NAME": "빈 표준명"},          # NOT NULL 위반 → 제거
        {"INGR_KOR_NAME": "가공소금", "INGR_ENG_NAME": "", "CAS_NO": None},  # 빈 문자열 → None
    ]
    recs = to_records(raw)
    assert [r["std_name"] for r in recs] == ["레티놀", "가공소금"], recs
    assert recs[1]["eng_name"] is None and recs[1]["cas_no"] is None
    assert recs[0]["cas_no"] == "68-26-8"
    print("selfcheck ok", file=sys.stderr)


if __name__ == "__main__":
    _selfcheck()
    print("수집 중...", file=sys.stderr)
    records = to_records(fetch_all())
    print(f"적재 대상 {len(records)}건", file=sys.stderr)

    if "--dry-run" in sys.argv:
        for r in records[:3]:
            print(r)
        sys.exit(0)
    upsert(records)
    print("완료", file=sys.stderr)
