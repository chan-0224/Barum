"""데일리 루틴 생성 (M2). 프롬프트 조립 + 응답 검증.

LLM에 맡기는 것은 **어떤 제품을 고르고 왜 그런지 한 줄로 쓰는 것**뿐이다.
나머지는 코드가 정한다.

  원칙 1  성분 충돌은 룰테이블이 이미 판정했다(conflicts.conflict_badges).
          LLM은 그 결과를 받아 문장으로 풀 뿐 판정하지 않는다.
  원칙 2  제품을 **번호로만** 주고받는다. 모델이 이름을 쓸 일이 없으므로
          보유하지 않은 제품을 지어내는 것이 구조적으로 불가능하다.
          범위 밖 번호는 검증에서 버린다.
  원칙 3  병명 표현 금지. 시스템 프롬프트로 지시하고, 출력에서 한 번 더 걸러낸다.

바르는 순서도 모델이 아니라 코드가 정한다 — 클렌저→토너→세럼→크림→선크림.
모델에게 순서까지 맡기면 매번 흔들리고 검증할 방법이 없다.

    python routine.py     # 샘플 화장대로 프롬프트를 조립해 출력(모델 호출 없음)
"""

import json
import logging
import re
import sys
import time

log = logging.getLogger(__name__)

MODEL = "gpt-4o"
FIRST_TIMEOUT = 10.0   # 화면 3이 10초에서 "조금만 더 기다려 주세요"로 바뀐다
TOTAL_BUDGET = 25.0    # 30초 초과 시 오류 화면. 그 전에 우리가 먼저 포기한다

# 바르는 순서. docs/SCREENS.md 화면 4의 "바를 것" 순번이 이걸 따른다
_STEP = {"CLEANSER": 0, "TONER": 1, "SERUM": 2, "CREAM": 3, "SUNSCREEN": 4}

# 원칙 3 — 진단으로 읽히는 표현. 출력에 섞이면 그 문장을 버린다
_BANNED = ["여드름", "아토피", "지루성", "습진", "피부염", "모낭염", "주사", "진단",
           "질환", "증상", "치료", "処方", "처방"]

SYSTEM = """너는 스킨케어 루틴을 짜주는 조수다. 사용자가 오늘 아침에 무엇을 바를지 정해 준다.

지켜야 할 것
1. 제품은 반드시 주어진 목록에서만 고른다. 번호로만 지목하고 제품명을 쓰지 않는다.
2. 병명이나 진단으로 읽히는 말을 쓰지 않는다.
   "여드름이 있어요" ✗ → "트러블이 보여요" ✓
   "피부염" "치료" "처방" 같은 단어를 쓰지 않는다.
3. 이유는 한 문장, 30자 이내. 반드시 "~해요" 체로 쓴다.
   "보습막을 형성합니다" ✗ → "건조함을 막아줘요" ✓
   기호(※, [], ―)나 입력에 있던 표시를 그대로 옮겨 쓰지 않는다.
4. 성분 충돌 판정은 이미 내려져 있다. 판단을 바꾸지 말고 그대로 따른다.
   AVOID로 묶인 성분을 가진 제품이 둘 다 목록에 있으면 **둘 다 skip에 넣는다.**
   어느 제품이 걸렸는지는 "충돌 판정에 걸린 성분"으로 표시돼 있다.
   skip 이유에는 어떤 성분과 겹쳐서 오늘 쉬는지 적는다.
5. **skip에는 충돌로 오늘 쉬는 제품만 넣는다. 최대 2개.**
   고르지 않았을 뿐인 제품은 skip이 아니다. "클렌저는 하나만 써요" 같은 문장은 쓰지 않는다.
   충돌이 없으면 skip은 빈 배열이다.
6. 아침 루틴이다. 밤에 바르라는 안내를 하지 않는다.

고르는 기준
- 클렌저 1개, 선크림 1개는 되도록 넣는다. 아침 루틴의 기본이다.
- 습도가 낮으면 보습을 두텁게, 높으면 가볍게 간다.
- 미세먼지가 나쁘면 세정과 자외선 차단을 확실히 한다.
- 같은 단계(예: 세럼) 제품을 여러 개 바르게 하지 않는다. 많아야 2개.
- 전체 4~6개로 맞춘다. 아침에 바를 수 있는 양이어야 한다.

출력은 JSON만. 설명을 덧붙이지 않는다.
{"apply":[{"product":번호,"reason":"이유"}],"skip":[{"product":번호,"reason":"이유"}]}"""


def _weather_line(w: dict) -> str:
    parts = []
    if w.get("temp") is not None:
        parts.append(f"기온 {w['temp']:.0f}도")
    if w.get("humidity") is not None:
        h = w["humidity"]
        state = "건조" if h < 40 else ("습함" if h > 70 else "보통")
        parts.append(f"습도 {h:.0f}%({state})")
    if w.get("pm10") is not None:
        p = w["pm10"]
        state = "좋음" if p <= 30 else ("보통" if p <= 80 else "나쁨")
        parts.append(f"미세먼지 {p}({state})")
    return " · ".join(parts) or "정보 없음"


def build_prompt(weather: dict, skin: dict | None, products: list[dict],
                 conflicts: list[dict], conflict_ingredients: set[str] = frozenset()) -> str:
    """사용자 메시지. products는 [{category, name, key_ingredients, ingredients}] 순서가 곧 번호다.

    conflict_ingredients — **AVOID 판정**에 관여한 성분의 표준명.
    `check_conflicts_by_product()` 결과에서 뽑는다:
        {n for c in raw if c["level"] == "AVOID" for n in c["ingredients"]}

    이게 없으면 모델이 어느 제품을 빼야 할지 모른다. keyIngredients는 표기 순서 상위 3개라
    레티놀처럼 저농도로 뒤쪽에 오는 활성이 빠지고, 그러면 "레티놀 + 비타민C를 같이 쓰지 말라"는
    판정을 받고도 그게 몇 번 제품인지 알 수 없다.

    **GOOD은 넣지 않는다.** 나이아신아마이드·판테놀·토코페롤은 거의 모든 제품에 들어 있어
    전부 표시하면 정작 빼야 할 제품이 묻힌다. 제품을 빼야 하는 판정은 AVOID뿐이다.
    """
    lines = [f"[오늘 날씨] {_weather_line(weather)}"]

    if skin and skin.get("summary"):
        lines.append(f"[피부 상태] {skin['summary']}")
    else:
        lines.append("[피부 상태] 확인하지 않음 (날씨와 보유 제품만으로 정해 줘)")

    lines.append("\n[보유 제품]")
    for i, p in enumerate(products):
        ing = ", ".join(p.get("key_ingredients") or []) or "-"
        hit = sorted(set(p.get("ingredients") or []) & set(conflict_ingredients))
        mark = f"  <충돌 판정에 걸린 성분: {', '.join(hit)}>" if hit else ""
        lines.append(f"  {i}. [{p['category']}] {p['name']}  (주요 성분: {ing}){mark}")

    if conflicts:
        lines.append("\n[성분 충돌 판정 — 이미 확정된 결과다. 그대로 따를 것]")
        for c in conflicts:
            pair = " + ".join(c["ingredients"])
            lines.append(f"  {c['level']}  {pair} — {c['label']}. {c['reason']}")
    else:
        lines.append("\n[성분 충돌 판정] 없음")

    lines.append("\n오늘 아침 루틴을 JSON으로 정해 줘.")
    return "\n".join(lines)


MAX_SKIP = 2  # docs/SCREENS.md 화면 4 — "뺄 것: 제품 1~2개"


def _clean(text: str) -> str | None:
    """원칙 3. 진단으로 읽히는 문장은 통째로 버린다 — 고쳐 쓰려다 뜻이 틀어지는 게 더 나쁘다."""
    t = (text or "").strip()
    if not t or any(w in t for w in _BANNED):
        return None
    # 프롬프트의 표시를 이유로 그대로 옮겨 쓰는 경우가 있다. 화면에 나가면 안 된다
    if any(ch in t for ch in "※<>[]") or "충돌 판정에 걸린" in t:
        return None
    return t[:60]


def parse(raw: str, products: list[dict]) -> dict:
    """모델 출력 → 카드에 올릴 형태. 번호가 유일한 연결고리라 범위 밖이면 버린다."""
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        raise ValueError("JSON을 찾지 못했다")
    data = json.loads(m.group(0))

    def pick(key: str) -> list[dict]:
        out, seen = [], set()
        for item in data.get(key) or []:
            try:
                i = int(item.get("product"))
            except (TypeError, ValueError):
                continue
            if not (0 <= i < len(products)) or i in seen:
                continue  # 없는 제품을 지어낼 수 없다(원칙 2)
            reason = _clean(item.get("reason"))
            if reason is None:
                continue
            seen.add(i)
            out.append({"index": i, "name": products[i]["name"],
                        "category": products[i]["category"], "reason": reason})
        return out

    apply_ = pick("apply")
    # 순서는 코드가 정한다. 모델에게 맡기면 매번 흔들린다
    apply_.sort(key=lambda x: _STEP.get(x["category"], 9))
    for n, x in enumerate(apply_, start=1):
        x["order"] = n

    # 모델이 "고르지 않은 제품"을 전부 skip에 넣는 경향이 있다. 카드가 무너지므로 잘라낸다
    skip = [x for x in pick("skip")
            if x["index"] not in {a["index"] for a in apply_}][:MAX_SKIP]
    return {
        "apply": [{"order": x["order"], "name": x["name"], "reason": x["reason"]} for x in apply_],
        "skip": [{"name": x["name"], "reason": x["reason"]} for x in skip],
    }


class RoutineTimeout(RuntimeError):
    """예산 안에 루틴을 못 만들었다. 호출부는 API.md의 AI_TIMEOUT(504)로 내보낸다."""


async def generate(client, weather: dict, skin: dict | None, products: list[dict],
                   conflicts: list[dict], conflict_ingredients: set[str] = frozenset(),
                   *, model: str = MODEL) -> dict:
    """루틴 카드를 만든다. client는 openai.AsyncOpenAI 인스턴스.

    실측에서 대부분 2초 안에 끝나지만 20초를 넘긴 경우가 있었다. 모델 쪽 지연이라
    우리가 통제할 수 없으므로, 첫 시도를 10초에서 끊고 한 번만 다시 시도한다.
    총 25초를 넘기면 포기한다 — 화면 3이 30초에서 오류로 넘어가기 때문에
    그 전에 우리가 먼저 끝내야 재시도 버튼이라도 보여줄 수 있다.
    """
    prompt = build_prompt(weather, skin, products, conflicts, conflict_ingredients)
    started = time.monotonic()
    last = None

    for attempt in (1, 2):
        left = TOTAL_BUDGET - (time.monotonic() - started)
        if left <= 1.0:
            break
        try:
            res = await client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.4,
                max_tokens=600,
                timeout=min(FIRST_TIMEOUT, left) if attempt == 1 else left,
            )
            return parse(res.choices[0].message.content, products)
        except Exception as e:  # 타임아웃·일시적 오류·JSON 깨짐 모두 한 번은 다시 해본다
            last = e
            log.warning("루틴 생성 %d회차 실패 (%.1f초 경과): %s",
                        attempt, time.monotonic() - started, e)

    raise RoutineTimeout(f"{time.monotonic() - started:.1f}초 안에 실패: {last}")


def _selfcheck() -> None:
    products = [
        {"category": "CLEANSER", "name": "녹두 클렌징폼", "key_ingredients": ["녹두가루"]},
        {"category": "SUNSCREEN", "name": "그린 선크림", "key_ingredients": ["징크옥사이드"]},
        {"category": "SERUM", "name": "레티놀 앰플", "key_ingredients": ["레티놀"]},
    ]
    raw = json.dumps({"apply": [{"product": 1, "reason": "자외선 막아요"},
                                {"product": 0, "reason": "가볍게 세안해요"}],
                      "skip": [{"product": 2, "reason": "오늘은 쉬어가요"}]}, ensure_ascii=False)
    got = parse(raw, products)
    assert [a["name"] for a in got["apply"]] == ["녹두 클렌징폼", "그린 선크림"], got  # 순서 재정렬
    assert [a["order"] for a in got["apply"]] == [1, 2]
    assert got["skip"] == [{"name": "레티놀 앰플", "reason": "오늘은 쉬어가요"}]

    # 없는 번호는 버린다(원칙 2)
    assert parse('{"apply":[{"product":99,"reason":"x"}]}', products)["apply"] == []
    # 병명 표현이 든 문장은 버린다(원칙 3)
    assert parse('{"apply":[{"product":0,"reason":"여드름을 치료해요"}]}', products)["apply"] == []
    # 같은 제품이 apply와 skip에 동시에 오면 apply가 이긴다
    both = parse('{"apply":[{"product":0,"reason":"세안"}],"skip":[{"product":0,"reason":"쉬어요"}]}',
                 products)
    assert both["skip"] == [], both
    print("selfcheck ok", file=sys.stderr)


if __name__ == "__main__":
    _selfcheck()
