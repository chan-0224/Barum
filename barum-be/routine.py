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
   AVOID로 묶인 두 제품이 목록에 있으면 **하나는 반드시 apply에, 나머지 하나는 skip에**
   넣는다. 판정 문구가 "오늘은 하나만 쓰세요"라서, 둘 다 빼거나 둘 다 안 고르면
   화면에 경고만 뜨고 정작 바를 게 없어진다. 둘 다 apply에 넣어서도 안 된다.
   어느 제품이 걸렸는지는 "충돌 판정에 걸린 성분"으로 표시돼 있다.

   어느 쪽을 남길지는 오늘 날씨와 피부 상태를 보고 정한다.
     - 건조하거나 피부가 예민해 보이면 자극이 적은 쪽을 남긴다.
     - 레티놀 계열은 아침에 맞지 않는다. 다른 쪽을 남기고 레티놀 계열을 skip한다.
   skip 이유에는 어떤 성분과 겹쳐서 오늘 쉬는지 적는다.
   남긴 제품의 apply 이유에는 왜 이쪽을 골랐는지 적는다.
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
                 conflicts: list[dict], conflict_ingredients: set[str] = frozenset(),
                 avoid_pairs: list[tuple[int, int]] = ()) -> str:
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

    # 짝을 제품 줄에 직접 붙인다. 아래에 따로 블록으로 적어 두면 모델이 "skip 하나 넣었으니
    # 됐다"로 읽고 나머지 하나를 목록에서 통째로 빠뜨린다(실측 5/5)
    partner = {}
    for i, j in avoid_pairs:
        partner.setdefault(i, []).append(j)
        partner.setdefault(j, []).append(i)

    lines.append("\n[보유 제품]")
    for i, p in enumerate(products):
        ing = ", ".join(p.get("key_ingredients") or []) or "-"
        hit = sorted(set(p.get("ingredients") or []) & set(conflict_ingredients))
        mark = f"  <충돌 성분: {', '.join(hit)}>" if hit else ""
        if i in partner:
            others = ", ".join(f"{k}번" for k in sorted(partner[i]))
            mark += f"  <{others}과 동시 사용 불가 — 이 중 하나는 반드시 apply에 들어가야 함>"
        lines.append(f"  {i}. [{p['category']}] {p['name']}  (주요 성분: {ing}){mark}")

    if conflicts:
        lines.append("\n[성분 충돌 판정 — 이미 확정된 결과다. 그대로 따를 것]")
        for c in conflicts:
            pair = " + ".join(c["ingredients"])
            lines.append(f"  {c['level']}  {pair} — {c['label']}. {c['reason']}")
    else:
        lines.append("\n[성분 충돌 판정] 없음")

    # 등급과 성분명만 주면 모델이 걸린 제품을 통째로 피해 버린다 — 실측에서 5개 시나리오
    # 전부 둘 다 안 골랐다. 번호로 직접 지목하고 무엇을 해야 하는지 한 줄로 붙인다
    if avoid_pairs:
        lines.append("\n[반드시 지킬 것]")
        for i, j in avoid_pairs:
            lines.append(
                f"  {i}번과 {j}번은 함께 쓸 수 없다.\n"
                f"   - 둘 중 **정확히 하나**를 apply 배열에 넣어라. "
                f"apply에 둘 다 없으면 틀린 답이다.\n"
                f"   - **그냥 고르지 않고 넘어가는 것도 틀린 답이다.** "
                f"skip에 하나 넣었다고 끝이 아니다.\n"
                f"   - 나머지 하나를 skip 배열에 넣어라.")
        lines.append("  이 제품은 '같은 단계 최대 2개'와 '전체 4~6개'보다 우선한다. "
                     "자리가 모자라면 충돌과 무관한 제품을 대신 빼라.")
        lines.append("  어느 쪽을 고를지는 위의 날씨와 피부 상태를 근거로 정하고, "
                     "그 근거를 apply 이유에 쓴다.")

    lines.append("\n오늘 아침 루틴을 JSON으로 정해 줘.")
    return "\n".join(lines)


MAX_SKIP = 2  # docs/SCREENS.md 화면 4 — "뺄 것: 제품 1~2개"

# AVOID 쌍에서 살아남은 제품의 이유. 서버가 고정한다 —
# 모델이 이미 둘 다 빼기로 결정한 상태라 쓸 만한 문장이 없다
KEPT_REASON = "겹치는 제품 중 오늘은 이것만 써요"
DROPPED_REASON = "겹치는 성분이 있어 오늘은 쉬어요"

# 아침 루틴이라 레티놀 계열을 뺀다. AVOID 룰 35건은 전부
# 레티놀 계열 · 각질 정리 산 · 순수 비타민C 세 축의 조합이고, 이 중 아침에 맞지 않는 건
# 레티놀 계열뿐이다(광분해·광민감).
# ponytail: 표준명 부분일치. 룰테이블의 레티놀 계열 4종(레티놀, 레티닐팔미테이트,
# 레티닐레티노에이트, 하이드록시피나콜론레티노에이트)이 모두 "레티"를 포함한다.
# 나중에 추가되는 유도체도 자동으로 걸린다. 판정이 아니라 **둘 중 뭘 남길지**에만 쓰므로
# 오탐이 나도 안전 문제는 없다 — 어느 쪽을 남기든 둘을 같이 바르지는 않는다.
_RETINOID = "레티"


def avoid_product_pairs(products: list[dict], raw_conflicts: list[dict]) -> list[tuple[int, int]]:
    """AVOID 판정에 걸린 **제품 번호 쌍**. parse()가 "정확히 하나만 skip"을 강제할 때 쓴다.

    raw_conflicts는 `conflicts.check_conflicts_by_product()`의 반환값 그대로.
    성분 쌍만 오므로 어느 제품끼리 걸렸는지는 여기서 되짚는다.
    """
    owners: dict[str, set[int]] = {}
    for i, p in enumerate(products):
        for n in p.get("ingredients") or []:
            n = (n or "").strip()
            if n:
                owners.setdefault(n, set()).add(i)

    pairs = set()
    for c in raw_conflicts:
        if c.get("level") != "AVOID":
            continue
        a, b = c["ingredients"]
        for x in owners.get(a, ()):
            for y in owners.get(b, ()):
                if x != y:  # 한 제품 안의 배합은 판정 대상이 아니다
                    pairs.add((min(x, y), max(x, y)))
    return sorted(pairs)


def _keep_side(i: int, j: int, products: list[dict],
               conflict_ingredients: set[str]) -> int:
    """AVOID 쌍에서 남길 제품 번호. 모델이 못 고르면 여기서 정한다."""
    def is_retinoid(k: int) -> bool:
        hit = set(products[k].get("ingredients") or []) & set(conflict_ingredients)
        return any(_RETINOID in n for n in hit)

    ri, rj = is_retinoid(i), is_retinoid(j)
    if ri != rj:
        return j if ri else i   # 레티놀 계열이 아닌 쪽을 남긴다
    return min(i, j)            # 둘 다 같은 계열이면 목록 순서대로. 임의지만 재현된다


def _clean(text: str) -> str | None:
    """원칙 3. 진단으로 읽히는 문장은 통째로 버린다 — 고쳐 쓰려다 뜻이 틀어지는 게 더 나쁘다."""
    t = (text or "").strip()
    if not t or any(w in t for w in _BANNED):
        return None
    # 프롬프트의 표시를 이유로 그대로 옮겨 쓰는 경우가 있다. 화면에 나가면 안 된다
    if any(ch in t for ch in "※<>[]") or "충돌 판정에 걸린" in t:
        return None
    return t[:60]


def parse(raw: str, products: list[dict], avoid_pairs: list[tuple[int, int]] = (),
          conflict_ingredients: set[str] = frozenset()) -> dict:
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
    # 모델이 "고르지 않은 제품"을 전부 skip에 넣는 경향이 있다. 카드가 무너지므로 잘라낸다
    skip = [x for x in pick("skip")
            if x["index"] not in {a["index"] for a in apply_}]

    def entry(i: int, reason: str) -> dict:
        return {"index": i, "name": products[i]["name"],
                "category": products[i]["category"], "reason": reason}

    # AVOID 쌍은 **정확히 하나만** 빠져야 한다. 판정 문구가 "오늘은 하나만 쓰세요"인데
    # 둘 다 빼면 사용자가 아무것도 안 바르고, 둘 다 넣으면 경고를 무시하는 셈이 된다.
    # 프롬프트로 지시하고 여기서 한 번 더 보장한다 — 모델이 어느 쪽이든 틀릴 수 있다
    for i, j in avoid_pairs:
        in_apply = {i, j} & {x["index"] for x in apply_}
        if len(in_apply) == 1:
            continue  # 이미 하나만 골랐다. 모델의 선택을 존중한다

        keep = _keep_side(i, j, products, conflict_ingredients)
        drop = j if keep == i else i

        if len(in_apply) == 2:
            # 경고를 무시하고 둘 다 바르라고 한 경우. 한쪽을 내린다
            log.info("AVOID 쌍 %s가 둘 다 apply에 있어 %d번을 skip으로 내린다", (i, j), drop)
            apply_ = [x for x in apply_ if x["index"] != drop]
            if drop not in {x["index"] for x in skip}:
                skip.append(entry(drop, DROPPED_REASON))
        else:
            # 둘 다 skip이거나, 둘 다 아예 고르지 않은 경우. 후자가 실제로 더 잦다 —
            # 모델이 충돌 제품을 통째로 피해 버린다. 어느 쪽이든 사용자는 아무것도 못 바르는데
            # 배지에는 "오늘은 하나만 쓰세요"가 떠 있어 말이 맞지 않는다
            log.info("AVOID 쌍 %s에서 apply가 0개라 %d번을 올린다", (i, j), keep)
            skip = [x for x in skip if x["index"] != keep]
            apply_.append(entry(keep, KEPT_REASON))
            if drop not in {x["index"] for x in skip}:
                skip.append(entry(drop, DROPPED_REASON))

    # 순서는 코드가 정한다. 모델에게 맡기면 매번 흔들린다.
    # 위에서 apply가 바뀔 수 있으므로 번호는 여기서 매긴다
    apply_.sort(key=lambda x: _STEP.get(x["category"], 9))
    for n, x in enumerate(apply_, start=1):
        x["order"] = n

    return {
        "apply": [{"order": x["order"], "name": x["name"], "reason": x["reason"]} for x in apply_],
        "skip": [{"name": x["name"], "reason": x["reason"]} for x in skip[:MAX_SKIP]],
    }


class RoutineTimeout(RuntimeError):
    """예산 안에 루틴을 못 만들었다. 호출부는 API.md의 AI_TIMEOUT(504)로 내보낸다."""


async def generate(client, weather: dict, skin: dict | None, products: list[dict],
                   conflicts: list[dict], conflict_ingredients: set[str] = frozenset(),
                   raw_conflicts: list[dict] = (), *, model: str = MODEL) -> dict:
    """루틴 카드를 만든다. client는 openai.AsyncOpenAI 인스턴스.

    실측에서 대부분 2초 안에 끝나지만 20초를 넘긴 경우가 있었다. 모델 쪽 지연이라
    우리가 통제할 수 없으므로, 첫 시도를 10초에서 끊고 한 번만 다시 시도한다.
    총 25초를 넘기면 포기한다 — 화면 3이 30초에서 오류로 넘어가기 때문에
    그 전에 우리가 먼저 끝내야 재시도 버튼이라도 보여줄 수 있다.
    """
    pairs = avoid_product_pairs(products, raw_conflicts or [])
    prompt = build_prompt(weather, skin, products, conflicts, conflict_ingredients, pairs)
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
            return parse(res.choices[0].message.content, products,
                         pairs, conflict_ingredients)
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

    # ── AVOID 쌍은 정확히 하나만 빠진다 ────────────────────────────
    pair_products = [
        {"category": "CLEANSER", "name": "클렌징폼", "ingredients": ["소듐라우로암포아세테이트"]},
        {"category": "SERUM", "name": "레티놀 앰플", "ingredients": ["레티놀"]},
        {"category": "SERUM", "name": "비타민C 세럼", "ingredients": ["아스코빅애씨드"]},
    ]
    raw_conf = [{"ingredients": ["레티놀", "아스코빅애씨드"], "level": "AVOID"}]
    pairs = avoid_product_pairs(pair_products, raw_conf)
    assert pairs == [(1, 2)], pairs
    ing = {"레티놀", "아스코빅애씨드"}

    # 둘 다 skip → 레티놀이 아닌 쪽(2번 비타민C)이 apply로 올라온다
    both_skip = parse(json.dumps({"apply": [{"product": 0, "reason": "세안해요"}],
                                  "skip": [{"product": 1, "reason": "겹쳐서 쉬어요"},
                                           {"product": 2, "reason": "겹쳐서 쉬어요"}]}),
                      pair_products, pairs, ing)
    assert [s["name"] for s in both_skip["skip"]] == ["레티놀 앰플"], both_skip
    assert "비타민C 세럼" in [a["name"] for a in both_skip["apply"]], both_skip
    assert [a["order"] for a in both_skip["apply"]] == [1, 2], both_skip  # 번호 재부여

    # 둘 다 apply → 레티놀 쪽이 skip으로 내려간다 (경고를 무시하면 안 된다)
    both_apply = parse(json.dumps({"apply": [{"product": 1, "reason": "결을 정리해요"},
                                             {"product": 2, "reason": "환하게 해줘요"}],
                                   "skip": []}),
                       pair_products, pairs, ing)
    assert [a["name"] for a in both_apply["apply"]] == ["비타민C 세럼"], both_apply
    assert [s["name"] for s in both_apply["skip"]] == ["레티놀 앰플"], both_apply

    # 모델이 이미 하나만 골랐으면 그대로 둔다
    ok_one = parse(json.dumps({"apply": [{"product": 1, "reason": "결을 정리해요"}],
                               "skip": [{"product": 2, "reason": "겹쳐서 쉬어요"}]}),
                   pair_products, pairs, ing)
    assert [a["name"] for a in ok_one["apply"]] == ["레티놀 앰플"], ok_one
    assert [s["name"] for s in ok_one["skip"]] == ["비타민C 세럼"], ok_one

    # 같은 계열끼리 걸리면 목록 순서가 앞선 쪽을 남긴다
    same = [{"category": "SERUM", "name": "A", "ingredients": ["레티놀"]},
            {"category": "SERUM", "name": "B", "ingredients": ["레티닐팔미테이트"]}]
    sp = avoid_product_pairs(same, [{"ingredients": ["레티놀", "레티닐팔미테이트"],
                                     "level": "AVOID"}])
    got = parse(json.dumps({"apply": [], "skip": [{"product": 0, "reason": "쉬어요"},
                                                  {"product": 1, "reason": "쉬어요"}]}),
                same, sp, {"레티놀", "레티닐팔미테이트"})
    assert [a["name"] for a in got["apply"]] == ["A"], got

    # 쌍을 아예 안 고른 경우에도 하나는 올라온다 (실제로 가장 잦았다)
    neither = parse(json.dumps({"apply": [{"product": 0, "reason": "세안해요"}], "skip": []}),
                    pair_products, pairs, ing)
    assert "비타민C 세럼" in [a["name"] for a in neither["apply"]], neither
    assert [s["name"] for s in neither["skip"]] == ["레티놀 앰플"], neither

    # 한 제품 안에 두 성분이 다 있으면 쌍이 아니다 (docs/API.md 표시 규칙)
    solo = [{"category": "SERUM", "name": "복합 앰플", "ingredients": ["레티놀", "아스코빅애씨드"]}]
    assert avoid_product_pairs(solo, raw_conf) == []

    print("selfcheck ok", file=sys.stderr)


if __name__ == "__main__":
    _selfcheck()
