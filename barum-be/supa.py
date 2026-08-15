"""Supabase 읽기 전용 접근.

원칙 6 — FastAPI는 DB에 쓰지 않는다. 저장은 전부 Spring이 한다.
여기 있는 함수는 전부 조회다.

유저 데이터(화장대)는 **사용자 JWT**로 읽는다. RLS가 걸린 상태를 유지하기 위해서다(원칙 4).
service 키는 참조 테이블(ingredients)과 Storage 파일 읽기에만 쓴다 — 둘 다 유저 소유가 아니다.
"""

import os

import httpx

TIMEOUT = 20.0


def _base() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/")


def _anon() -> str:
    return os.environ["SUPABASE_ANON_KEY"]


def _service() -> str:
    return os.environ["SUPABASE_SERVICE_KEY"]


async def _get(client: httpx.AsyncClient, path: str, params: dict, jwt: str | None) -> list:
    key = _anon() if jwt else _service()
    headers = {"apikey": key, "Authorization": f"Bearer {jwt or _service()}"}
    r = await client.get(f"{_base()}/rest/v1/{path}", params=params, headers=headers)
    if r.is_error:
        raise RuntimeError(f"{path} HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


async def fetch_vanity(jwt: str) -> list[dict]:
    """사용자 화장대. RLS 때문에 본인 것만 돌아온다.

    성분이 두 곳에 나뉘어 있다.
      - 카탈로그에서 등록한 제품(SAMPLE/CATALOG): catalog_product_ingredients
      - 사진으로 등록한 제품(OCR): product_ingredients
    둘을 합쳐서 제품별 성분 집합을 만든다.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        products = await _get(c, "products", {
            "select": "id,name,catalog_id,source,catalog_products(category)",
            "order": "created_at",
        }, jwt)
        if not products:
            return []

        ids = [p["id"] for p in products]
        own = await _get(c, "product_ingredients", {
            "select": "product_id,ingredients(std_name)",
            "product_id": f"in.({','.join(ids)})",
        }, jwt)

        cat_ids = [str(p["catalog_id"]) for p in products if p.get("catalog_id")]
        cat = []
        if cat_ids:
            # 카탈로그는 참조 데이터라 익명 권한으로도 읽힌다
            cat = await _get(c, "catalog_product_ingredients", {
                "select": "catalog_id,ingredients(std_name)",
                "catalog_id": f"in.({','.join(cat_ids)})",
            }, jwt)

    by_own: dict[str, set] = {}
    for r in own:
        if r.get("ingredients"):
            by_own.setdefault(r["product_id"], set()).add(r["ingredients"]["std_name"])
    by_cat: dict[int, set] = {}
    for r in cat:
        if r.get("ingredients"):
            by_cat.setdefault(r["catalog_id"], set()).add(r["ingredients"]["std_name"])

    out = []
    for p in products:
        names = set(by_own.get(p["id"], set()))
        if p.get("catalog_id"):
            names |= by_cat.get(p["catalog_id"], set())
        category = (p.get("catalog_products") or {}).get("category") or "SERUM"
        out.append({
            "id": p["id"],
            "name": p["name"],
            "category": category,
            "ingredients": sorted(names),
        })
    return out


async def fetch_ingredient_index() -> tuple[dict, dict, dict]:
    """(표준명→id, 이명→id, id→표준명). OCR 매칭용. 참조 테이블이라 service 키로 읽는다."""
    rows, page = [], 0
    async with httpx.AsyncClient(timeout=60) as c:
        while True:
            key = _service()
            r = await c.get(f"{_base()}/rest/v1/ingredients",
                            params={"select": "id,std_name,synonym", "order": "id"},
                            headers={"apikey": key, "Authorization": f"Bearer {key}",
                                     "Range": f"{page * 1000}-{page * 1000 + 999}"})
            if r.is_error:
                raise RuntimeError(f"ingredients HTTP {r.status_code}: {r.text[:200]}")
            batch = r.json()
            rows += batch
            if len(batch) < 1000:
                break
            page += 1

    from matching import build_index
    by_std, by_syn = build_index(rows)
    return by_std, by_syn, {r["id"]: r["std_name"] for r in rows}


async def download(bucket: str, path: str, jwt: str | None = None) -> bytes:
    """Storage 파일. 얼굴 사진은 비공개 버킷이라 인증이 필요하다(원칙 5).

    jwt를 주면 사용자 권한으로 읽는다(본인 폴더만). Spring이 내부 호출로 부르는 OCR은
    jwt가 없어 service 키를 쓰는데, 이때 경로 소유권은 Spring이 이미 확인했다.
    """
    key = _anon() if jwt else _service()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{_base()}/storage/v1/object/{bucket}/{path}",
                        headers={"apikey": key, "Authorization": f"Bearer {jwt or _service()}"})
    if r.is_error:
        raise RuntimeError(f"storage {bucket}/{path} HTTP {r.status_code}")
    return r.content
