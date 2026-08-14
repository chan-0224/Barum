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


async def check_conflicts_by_product(products: dict[str, list[str]]) -> list[dict]:
    """제품별 성분을 받아, **서로 다른 두 제품 사이**의 조합만 판정한다.

    AVOID의 뜻은 "이 둘을 같이 바르지 마세요"다. 한 제품 안에 두 성분이 함께 들어 있는 건
    제조사가 배합을 조율한 결과이므로 경고 대상이 아니다. 성분을 한 덩어리로 넘기면
    이걸 구분할 수 없어, 레티놀과 하이드록시피나콜론레티노에이트를 같이 넣은 앰플 하나를
    등록했을 뿐인데 "같이 쓰지 마세요"가 뜬다(실제 카탈로그 113건 중 2건이 그렇다).

    반환 형태는 check_conflicts와 같다 — docs/API.md의 conflict 이벤트를 그대로 쓴다.
    """
    owners: dict[str, set[str]] = {}
    for product, names in products.items():
        for n in names:
            n = (n or "").strip()
            if n:
                owners.setdefault(n, set()).add(product)
    if len(owners) < 2:
        return []

    out = []
    for row in await _fetch_rules():
        a, b = row["ingredient_a"], row["ingredient_b"]
        pa, pb = owners.get(a), owners.get(b)
        if not pa or not pb:
            continue
        # 두 성분이 같은 제품에만 있으면 건너뛴다. 서로 다른 제품에 걸쳐야 성립한다
        if not any(x != y for x in pa for y in pb):
            continue
        out.append({
            "ingredients": [a, b],
            "level": row["level"],
            "label": row["label"],
            "reason": row["reason"],
            "source": row["source"],
        })
    out.sort(key=lambda x: (_LEVEL_ORDER.get(x["level"], 9), x["ingredients"]))
    return out


# 카드에 보여줄 대표명. 표준명을 그대로 쓰면 화면에서 읽히지 않는다
# ("하이드록시피나콜론레티노에이트 + 아스코빅애씨드"). docs/SCREENS.md 화면 5가
# 조합명을 "레티놀 + 비타민C"로 적어 둔 것도 같은 이유다.
#
# 테이블로 빼지 않은 이유: 룰에 쓰이는 성분이 20종뿐이고, 룰이 바뀔 때만 같이 바뀌며,
# 소비자가 이 모듈 하나다. 룰을 추가하면 여기도 함께 본다(data/README.md에 적어 뒀다).
_DISPLAY = {
    "레티닐팔미테이트": "레티놀 계열",
    "레티닐레티노에이트": "레티놀 계열",
    "하이드록시피나콜론레티노에이트": "레티놀 계열",
    "세라마이드엔피": "세라마이드",
    "세라마이드엔에스": "세라마이드",
    "세라마이드에이피": "세라마이드",
    "아스코빅애씨드": "비타민C",
    "토코페롤": "비타민E",
}

MAX_GOOD = 2  # AVOID는 전부 보여준다. GOOD은 배지가 넘치지 않게 제한


async def conflict_badges(products: dict[str, list[str]]) -> list[dict]:
    """루틴 카드에 그대로 올릴 판정 목록.

    check_conflicts_by_product의 결과를 화면에 맞게 줄인다.
      1) 같은 제품 쌍 + 같은 등급이면 1건만 남긴다.
         세라마이드 아형이 여러 개 든 제품 하나 때문에 같은 말이 세 번 뜨는 걸 막는다.
      2) 성분명을 대표명으로 바꾼다(_DISPLAY).
      3) AVOID는 전부, GOOD은 MAX_GOOD건까지.

    반환 형태는 docs/API.md의 conflict 이벤트와 같다. `ingredients`가 대표명이라는 점만 다르다.
    """
    owners: dict[str, set[str]] = {}
    for product, names in products.items():
        for n in names:
            n = (n or "").strip()
            if n:
                owners.setdefault(n, set()).add(product)

    picked: dict[tuple, dict] = {}
    for c in await check_conflicts_by_product(products):
        a, b = c["ingredients"]
        pair = min(
            ((x, y) for x in owners.get(a, ()) for y in owners.get(b, ()) if x != y),
            default=None, key=lambda t: tuple(sorted(t)))
        if pair is None:
            continue
        key = (tuple(sorted(pair)), c["level"])
        # 대표명으로 바뀌는 성분이 적은 쪽을 남긴다 —
        # "레티놀 + 비타민C"가 "비타민C + 레티놀 계열"보다 전달이 낫다
        renamed = sum(1 for n in (a, b) if n in _DISPLAY)
        if key not in picked or renamed < picked[key][0]:
            picked[key] = (renamed, c)

    out = []
    for _, c in sorted(picked.values(), key=lambda t: (_LEVEL_ORDER.get(t[1]["level"], 9),
                                                       t[1]["ingredients"])):
        out.append({**c, "ingredients": [_DISPLAY.get(n, n) for n in c["ingredients"]]})

    avoid = [c for c in out if c["level"] == "AVOID"]
    good = [c for c in out if c["level"] == "GOOD"][:MAX_GOOD]
    return avoid + good


def _selfcheck() -> None:
    assert asyncio.run(check_conflicts([])) == []
    assert asyncio.run(check_conflicts(["레티놀"])) == []       # 한 종이면 조합 자체가 없다
    assert asyncio.run(check_conflicts(["레티놀", "  "])) == []  # 공백은 성분으로 안 친다

    # 한 제품 안의 배합은 경고 대상이 아니다
    one = asyncio.run(check_conflicts_by_product({"앰플": ["레티놀", "아스코빅애씨드"]}))
    assert one == [], one
    # 서로 다른 제품에 걸치면 판정한다
    two = asyncio.run(check_conflicts_by_product({"앰플": ["레티놀"], "세럼": ["아스코빅애씨드"]}))
    assert [c["level"] for c in two] == ["AVOID"], two
    # 한 제품이 둘 다 갖고 있어도, 다른 제품이 한쪽을 가지면 성립한다
    three = asyncio.run(check_conflicts_by_product(
        {"앰플": ["레티놀", "아스코빅애씨드"], "세럼": ["아스코빅애씨드"]}))
    assert [c["level"] for c in three] == ["AVOID"], three

    # 카드용 — 같은 제품 쌍의 같은 등급은 1건, 성분명은 대표명
    vanity = {
        "레티놀 앰플": ["레티놀", "하이드록시피나콜론레티노에이트", "나이아신아마이드"],
        "비타민C 세럼": ["아스코빅애씨드"],
        "장벽 크림": ["세라마이드엔피", "세라마이드엔에스", "세라마이드에이피", "콜레스테롤"],
    }
    badges = asyncio.run(conflict_badges(vanity))
    avoid = [c for c in badges if c["level"] == "AVOID"]
    assert len(avoid) == 1, avoid                      # 앰플↔세럼에서 2건이 나오지만 1건으로
    assert avoid[0]["ingredients"] == ["레티놀", "비타민C"], avoid[0]["ingredients"]
    good = [c for c in badges if c["level"] == "GOOD"]
    assert len(good) <= MAX_GOOD, good                 # 세라마이드 3아형이 3건이 되지 않는다
    assert all("세라마이드엔" not in n for c in badges for n in c["ingredients"]), badges
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
