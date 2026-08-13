"""올리브영 수집 CSV → catalog_products 정제 적재.

수집 원본은 쇼핑몰 표기 그대로라 그냥 넣으면 못 쓴다. 세 가지를 고친다.

1) 제품명 — 마케팅 문구 제거. `[8월올영픽] 브랜드 제품명 50ml 기획 (+리필)` → `제품명`
2) 전성분 — **증정품·세트 성분 분리.** 수집본에는 `[본품] ... [증정] ...` 처럼 여러 제품의
   전성분이 한 칸에 합쳐져 있다. 그대로 두면 사용자가 쓰지도 않는 제품의 성분으로
   충돌 경고가 뜬다(원칙 1이 걸리는 지점). 첫 섹션만 남긴다.
3) 카테고리 — 허용값 5종으로 재분류. 수집 쪽 DB에 CHECK 제약이 없어 ETC·LOTION이 섞여 있다.

    python scripts/import_catalog_csv.py docs/catalog_products_rows.csv --dry-run
    python scripts/import_catalog_csv.py docs/catalog_products_rows.csv
"""

import csv
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

CATEGORIES = ("CLEANSER", "TONER", "SERUM", "CREAM", "SUNSCREEN")

# ── 제품명 ──────────────────────────────────────────────────
_BRACKET = re.compile(r"^\s*(\[[^\]]*\]\s*)+")
_PAREN = re.compile(r"\s*\([^)]*\)")
_VOLUME = re.compile(r"\s*\d+(\.\d+)?\s*(\+\s*\d+(\.\d+)?\s*)?(ml|mL|ML|g|G|kg|매|정|개입|개)\b")
_PROMO = re.compile(
    r"\s*(단독기획|리필기획|한정기획|기획|증정|단품|대용량|한정|리뉴얼|NEW|new"
    r"|\d+\s*입|\d+\s*종\s*택\s*\d+|\d+\s*종|택\s*\d+|1\s*\+\s*1|\d\+\d)")


def clean_name(name: str, brand: str) -> str:
    s = _BRACKET.sub("", name or "")
    s = _PAREN.sub("", s)
    s = _VOLUME.sub("", s)
    for _ in range(3):  # "150ml 단품/1+1 기획"처럼 겹쳐 있다
        s = _PROMO.sub("", s)
    s = re.sub(r"\s+", " ", s.replace("/", " ")).strip(" -·,/+")
    if brand and s.startswith(brand):  # name에 브랜드가 중복으로 들어있다
        s = s[len(brand):].strip(" -·,/")
    return re.sub(r"\s+", " ", s).strip()


# ── 전성분 ──────────────────────────────────────────────────
_SECTION = re.compile(r"\[[^\]]{2,40}\]")
_LEAD_NOISE = re.compile(r"^[\s\-–·]*((리뉴얼\s*적용|전성분|성분)\s*[:：]?\s*)?")


def clean_ingredients(raw: str) -> tuple[str, str | None]:
    """(정제된 전성분, 잘라낸 이유). 첫 섹션만 남긴다."""
    s = (raw or "").strip()
    if not s:
        return "", None

    note = None
    marks = list(_SECTION.finditer(s))
    if marks:
        # 표기가 두 가지다.
        #   (a) [본품] ... [증정] ...  → 첫 구분자 뒤 ~ 두 번째 구분자 앞
        #   (b) ... 본품 성분 ... [세럼] ...  → 본품이 라벨 없이 앞에 온다. 구분자 앞까지
        # (b)를 (a)로 처리하면 본품을 버리고 증정품 성분만 남는다.
        if s[:marks[0].start()].strip():
            s = s[:marks[0].start()].strip()
            note = f"증정 {len(marks)}개 섹션 제거(본품 무라벨)"
        else:
            end = marks[1].start() if len(marks) > 1 else len(s)
            s = s[marks[0].end():end].strip()
            if len(marks) > 1:
                note = f"증정·세트 {len(marks) - 1}개 섹션 제거"

    s = _LEAD_NOISE.sub("", s).strip()

    # 쉼표가 없고 공백만 있는 표기(라로슈포제 등). 공백을 구분자로 본다
    if "," not in s and s.count(" ") > 5:
        s = ", ".join(s.split())
        note = (note + " / " if note else "") + "공백 구분 → 쉼표 변환"
    return s.strip(" ,"), note


# ── 카테고리 ────────────────────────────────────────────────
# 팀 합의: 올인원 → CREAM(보습으로 끝맺는 제품), 미스트 → TONER(수분 공급 단계)
_RULES = [
    ("SUNSCREEN", ["선크림", "선스틱", "선세럼", "선블록", "선쿠션", "썬크림", "자외선차단", "SPF"]),
    ("CLEANSER", ["클렌징", "클렌저", "클렌즈", "클렌징폼", "워시", "버블", "필링젤"]),
    ("TONER", ["미스트", "토너", "패드", "엑스폴리언트"]),
    ("CREAM", ["올인원", "크림", "로션", "에멀전", "스킨밀크", "밤"]),
    ("SERUM", ["세럼", "앰플", "에센스", "부스터", "컨센트레이트", "리프터"]),
]


def classify(name: str, current: str) -> str:
    for cat, words in _RULES:
        if any(w in name for w in words):
            return cat
    return current if current in CATEGORIES else "SERUM"


# ── 적재 ────────────────────────────────────────────────────
def upsert(rows: list[dict]) -> None:
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
         "Prefer": "resolution=merge-duplicates,return=minimal"}
    for i in range(0, len(rows), 200):
        chunk = rows[i:i + 200]
        r = httpx.post(f"{url}/rest/v1/catalog_products?on_conflict=brand,name",
                       headers=h, json=chunk, timeout=60)
        if r.is_error:
            raise RuntimeError(f"적재 실패 (offset {i}) HTTP {r.status_code}: {r.text[:400]}")
        print(f"  적재 {i + len(chunk)}/{len(rows)}", file=sys.stderr)


def main() -> None:
    path = Path(sys.argv[1])
    src = list(csv.DictReader(path.open(encoding="utf-8")))
    print(f"원본 {len(src)}건\n")

    out, dropped, notes, seen = [], [], [], {}
    for r in src:
        brand = (r.get("brand") or "").strip()
        name = clean_name(r.get("name", ""), brand)
        ing, note = clean_ingredients(r.get("raw_ingredients", ""))

        if not name or len(name) < 2:
            dropped.append((r.get("id"), r.get("name", "")[:50], "정규화 후 이름이 비었다"))
            continue
        # 세트 상품은 어느 제품인지 특정할 수 없다. 성분도 섞여 있어 판정이 오염된다
        if "세트" in r.get("name", ""):
            dropped.append((r.get("id"), name, "세트 상품 — 단일 제품으로 특정 불가"))
            continue

        key = (brand, name)
        if key in seen:
            dropped.append((r.get("id"), name, f"중복 (id {seen[key]}와 동일)"))
            continue
        seen[key] = r.get("id")

        if note:
            notes.append((r.get("id"), name, note))
        out.append({
            "brand": brand,
            "name": name,
            "name_raw": (r.get("name") or "").strip(),
            "category": classify(name, (r.get("category") or "").strip()),
            "image_url": (r.get("image_url") or "").strip() or None,
            "raw_ingredients": ing,
        })

    from collections import Counter
    print("카테고리:", dict(Counter(x["category"] for x in out)))
    for c in CATEGORIES:
        if not any(x["category"] == c for x in out):
            print(f"  ※ {c} 0건 — 샘플 화장대 구성에 필요하다(docs/SCREENS.md)")

    if notes:
        print(f"\n전성분 정제 {len(notes)}건")
        for i, n, why in notes:
            print(f"  [{i:>3}] {n[:40]:40} {why}")

    if dropped:
        print(f"\n제외 {len(dropped)}건")
        for i, n, why in dropped:
            print(f"  [{i:>3}] {n[:40]:40} {why}")

    print(f"\n적재 대상 {len(out)}건")
    if "--dry-run" in sys.argv:
        print("\n--dry-run 이므로 적재하지 않았다.")
        return
    upsert(out)
    print("완료")


if __name__ == "__main__":
    main()
