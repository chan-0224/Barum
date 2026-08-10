"""성분 조합 룰 CSV 검증 + Supabase 적재.

    python scripts/load_rules.py --check-only   # 검증만
    python scripts/load_rules.py                # 검증 + 적재

검증을 통과 못 하면 적재하지 않는다. 룰테이블은 M3 완료 기준이 "오답 0"이라
DB에 없는 성분명이 하나라도 섞이면 그 룰은 영원히 매칭되지 않는다.

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import csv
import os
import sys
from pathlib import Path

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "ingredient_rules.csv"
LEVELS = {"AVOID", "CAUTION", "GOOD"}


def load_csv(path: Path) -> list[dict]:
    """CSV를 읽어 쌍을 정렬한다. 정렬 기준은 DB의 COLLATE "C"와 같은 코드포인트 순."""
    rows = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            a, b = sorted([row["ingredient_a"].strip(), row["ingredient_b"].strip()])
            rows.append({
                "ingredient_a": a, "ingredient_b": b,
                "level": row["level"].strip(),
                "label": row["label"].strip(),
                "reason": row["reason"].strip(),
                "source": row["source"].strip(),
                "verified": row["verified"].strip().lower() == "true",
            })
    return rows


def validate(rows: list[dict], known: set[str]) -> list[str]:
    errors, seen = [], {}
    for i, r in enumerate(rows, start=2):  # 헤더가 1행
        where = f"{i}행 [{r['ingredient_a']} + {r['ingredient_b']}]"

        if r["level"] not in LEVELS:
            errors.append(f"{where} level이 {LEVELS} 밖: {r['level']!r}")
        if r["ingredient_a"] == r["ingredient_b"]:
            errors.append(f"{where} 자기 자신과의 조합")
        for col in ("label", "reason", "source"):
            if not r[col]:
                errors.append(f"{where} {col}이 비었다")

        # 역순 중복도 여기서 잡힌다 — 이미 정렬해 뒀으므로 키가 같아진다
        key = (r["ingredient_a"], r["ingredient_b"])
        if key in seen:
            errors.append(f"{where} {seen[key]}행과 중복(역순 포함)")
        else:
            seen[key] = i

        for name in (r["ingredient_a"], r["ingredient_b"]):
            if name not in known:
                errors.append(f"{where} '{name}'이 ingredients.std_name에 없다")
    return errors


def fetch_known_names(names: set[str]) -> set[str]:
    """입력한 이름들 중 ingredients에 실제 존재하는 것만 돌려준다."""
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    quoted = ",".join('"' + n.replace('"', '""') + '"' for n in sorted(names))
    r = httpx.get(f"{url}/rest/v1/ingredients",
                  params={"std_name": f"in.({quoted})", "select": "std_name"},
                  headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=30)
    if r.is_error:
        raise RuntimeError(f"ingredients 조회 실패 HTTP {r.status_code}: {r.text[:300]}")
    return {x["std_name"] for x in r.json()}


def upsert(rows: list[dict]) -> None:
    """CSV를 DB에 반영한다. CSV가 유일한 원본이므로 CSV에서 빠진 룰은 DB에서도 지운다.

    지우지 않으면 근거가 틀려서 뺀 룰이 DB에 남아 계속 판정된다. M3 기준이 "오답 0"이라 치명적.
    """
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    r = httpx.post(f"{url}/rest/v1/ingredient_rules?on_conflict=ingredient_a,ingredient_b",
                   headers={**h, "Prefer": "resolution=merge-duplicates,return=minimal"},
                   json=rows, timeout=60)
    if r.is_error:
        raise RuntimeError(f"적재 실패 HTTP {r.status_code}: {r.text[:400]}")

    r = httpx.get(f"{url}/rest/v1/ingredient_rules",
                  params={"select": "ingredient_a,ingredient_b"}, headers=h, timeout=30)
    if r.is_error:
        raise RuntimeError(f"기존 룰 조회 실패 HTTP {r.status_code}: {r.text[:300]}")

    keep = {(x["ingredient_a"], x["ingredient_b"]) for x in rows}
    stale = [(x["ingredient_a"], x["ingredient_b"]) for x in r.json()
             if (x["ingredient_a"], x["ingredient_b"]) not in keep]
    for a, b in stale:
        d = httpx.delete(f"{url}/rest/v1/ingredient_rules",
                         params={"ingredient_a": f"eq.{a}", "ingredient_b": f"eq.{b}"},
                         headers=h, timeout=30)
        if d.is_error:
            raise RuntimeError(f"삭제 실패 [{a}+{b}] HTTP {d.status_code}: {d.text[:200]}")
        print(f"  CSV에서 빠진 룰 삭제: {a} + {b}", file=sys.stderr)


def main() -> None:
    rows = load_csv(CSV_PATH)
    print(f"CSV {len(rows)}건 읽음")

    names = {n for r in rows for n in (r["ingredient_a"], r["ingredient_b"])}
    known = fetch_known_names(names)
    print(f"성분 {len(names)}종 중 {len(known)}종이 ingredients에 존재")

    errors = validate(rows, known)
    if errors:
        print(f"\n검증 실패 {len(errors)}건:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    by_level = {lv: sum(1 for r in rows if r["level"] == lv) for lv in sorted(LEVELS)}
    n_verified = sum(1 for r in rows if r["verified"])
    print(f"검증 통과 — {by_level}")
    print(f"출처 원문 확인: {n_verified}/{len(rows)}건 (verified=true만 발표 인용 가능)")

    if "--check-only" in sys.argv:
        return
    upsert(rows)
    print(f"적재 완료 {len(rows)}건")


if __name__ == "__main__":
    main()
