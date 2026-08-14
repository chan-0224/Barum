"""성분 조합 판정 (M3). 원칙 1 — 안전 판정은 결정론적으로.

    check_conflicts(["레티놀", "아스코빅애씨드"])
    → [{"ingredients": ["레티놀", "아스코빅애씨드"], "level": "AVOID", ...}]

**이 모듈에 LLM을 끼워넣지 말 것.** 룰테이블 조회만 한다.
LLM은 여기서 나온 결과를 자연어로 풀어 쓰는 역할만 맡는다.

    python conflicts.py    # 자체검증 + 실제 조회 확인
"""

import asyncio
import os
import sys

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# 배지 정렬 순서. 위험한 것이 위로 온다.
# 2단계뿐이다 — 바름은 아침 루틴만 제시하므로 "시간대 분리"(구 CAUTION)가 성립하지 않는다.
_LEVEL_ORDER = {"AVOID": 0, "GOOD": 1}


async def _fetch_rules() -> list[dict]:
    """룰테이블 전체. 54건이라 통째로 받아도 응답이 작다."""
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_ANON_KEY"]  # 읽기 전용이면 충분하다. service 키를 쓰지 않는다
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{url}/rest/v1/ingredient_rules",
            params={"select": "ingredient_a,ingredient_b,level,label,reason,source"},
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
        )
    if r.is_error:
        raise RuntimeError(f"룰 조회 실패 HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


async def check_conflicts(ingredient_names: list[str]) -> list[dict]:
    """성분 목록에서 룰테이블에 걸리는 조합을 전부 찾는다.

    룰 전체를 받아 메모리에서 대조한다. 성분 목록을 `a IN (...) AND b IN (...)` 으로
    보내지 않는 이유: 제품 5개면 고유 성분이 140종이 넘고, 한글 표준명이 퍼센트 인코딩되면
    쿼리스트링이 10KB를 넘어 400이 난다. **제품 서너 개만 등록해도 M3가 통째로 죽는다.**
    룰은 54건뿐이라 전부 받는 편이 응답도 작고 성분 수와 무관하게 일정하다.

    쌍이 정렬돼 저장돼 있든 아니든 결과가 같다 — 두 성분이 모두 입력에 있는지만 본다.
    """
    names = {n.strip() for n in ingredient_names if n and n.strip()}
    if len(names) < 2:
        return []

    rules = [
        {
            "ingredients": [row["ingredient_a"], row["ingredient_b"]],
            "level": row["level"],
            "label": row["label"],
            "reason": row["reason"],
            "source": row["source"],
        }
        for row in await _fetch_rules()
        if row["ingredient_a"] in names and row["ingredient_b"] in names
    ]
    rules.sort(key=lambda x: (_LEVEL_ORDER.get(x["level"], 9), x["ingredients"]))
    return rules


def _selfcheck() -> None:
    assert asyncio.run(check_conflicts([])) == []
    assert asyncio.run(check_conflicts(["레티놀"])) == []       # 한 종이면 조합 자체가 없다
    assert asyncio.run(check_conflicts(["레티놀", "  "])) == []  # 공백은 성분으로 안 친다
    print("selfcheck ok", file=sys.stderr)


if __name__ == "__main__":
    _selfcheck()

    cases = [
        ["레티놀", "아스코빅애씨드", "하이알루로닉애씨드"],
        ["아스코빅애씨드", "토코페롤", "페룰릭애씨드"],
        ["레티놀", "나이아신아마이드", "세라마이드엔피", "살리실릭애씨드"],
        ["글리세린", "정제수"],
    ]
    for names in cases:
        print(f"\n입력: {names}")
        for c in asyncio.run(check_conflicts(names)):
            print(f"  [{c['level']:7}] {' + '.join(c['ingredients'])} — {c['label']}")
            print(f"            {c['reason']}")
            print(f"            근거: {c['source']}")
