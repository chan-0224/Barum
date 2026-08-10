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

# 배지 정렬 순서. 위험한 것이 위로 온다
_LEVEL_ORDER = {"AVOID": 0, "CAUTION": 1, "GOOD": 2}


def _in_list(names: set[str]) -> str:
    """PostgREST in.(...) 값. 표준명에 쉼표가 들어간 성분이 있어 반드시 따옴표로 감싼다.

    예: 2,4,5-트라이메틸아닐린 — 따옴표가 없으면 세 개 값으로 쪼개진다.
    """
    return "(" + ",".join('"' + n.replace('"', '""') + '"' for n in sorted(names)) + ")"


async def check_conflicts(ingredient_names: list[str]) -> list[dict]:
    """성분 목록에서 룰테이블에 걸리는 조합을 전부 찾는다.

    쌍을 만들어 하나씩 조회하지 않는다. 룰은 두 성분이 **모두** 입력에 있을 때만 성립하므로
    `a IN (목록) AND b IN (목록)` 한 번이면 정확히 그 집합이 나온다. 성분이 늘어도 쿼리는 1회.
    저장된 쌍이 정렬돼 있든 아니든 결과가 같아서 순서를 신경 쓸 필요도 없다.
    """
    names = {n.strip() for n in ingredient_names if n and n.strip()}
    if len(names) < 2:
        return []

    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_ANON_KEY"]  # 읽기 전용이면 충분하다. service 키를 쓰지 않는다
    in_list = _in_list(names)

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{url}/rest/v1/ingredient_rules",
            params={
                "ingredient_a": f"in.{in_list}",
                "ingredient_b": f"in.{in_list}",
                "select": "ingredient_a,ingredient_b,level,label,reason,source",
            },
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
        )
    if r.is_error:
        raise RuntimeError(f"룰 조회 실패 HTTP {r.status_code}: {r.text[:300]}")

    rules = [
        {
            "ingredients": [row["ingredient_a"], row["ingredient_b"]],
            "level": row["level"],
            "label": row["label"],
            "reason": row["reason"],
            "source": row["source"],
        }
        for row in r.json()
    ]
    rules.sort(key=lambda x: (_LEVEL_ORDER.get(x["level"], 9), x["ingredients"]))
    return rules


def _selfcheck() -> None:
    assert _in_list({"레티놀"}) == '("레티놀")'
    assert _in_list({"b", "a"}) == '("a","b")'
    # 쉼표가 든 표준명이 한 값으로 유지되는지 — 따옴표가 빠지면 여기서 깨진다
    assert _in_list({"2,4,5-트라이메틸아닐린"}) == '("2,4,5-트라이메틸아닐린")'

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
