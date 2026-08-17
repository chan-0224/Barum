"""GPT-4o Vision — 셀카 판독과 전성분표 OCR.

원칙 3: 병명 진단 표현 금지. 프롬프트로 지시하고 출력에서 한 번 더 거른다.
셀카에서 읽는 것은 **상태 신호 넷(건조·유분·홍조·트러블)의 유무**뿐이다.
점수나 등급을 매기지 않는다 — 그건 진단 영역이고, 조명 편차에 무너진다.
"""

import base64
import json
import logging
import re

log = logging.getLogger(__name__)

MODEL = "gpt-4o"
SKIN_TIMEOUT = 12.0
OCR_TIMEOUT = 25.0

_BANNED = ["여드름", "아토피", "지루성", "습진", "피부염", "모낭염", "진단", "질환", "치료", "처방"]

_SKIN_SYSTEM = """사진 속 피부의 겉보기 상태만 확인한다. 진단하지 않는다.

먼저 face를 판단한다.
  face  사진에 사람 얼굴이 보이고 피부를 살펴볼 수 있는가

face가 false면 나머지는 모두 false, summary는 빈 문자열로 둔다.
face가 true면 네 가지 신호의 유무를 판단한다.
  dry      건조해 보이는가 (각질, 당김)
  oily     번들거리는가
  redness  붉은 기가 있는가
  trouble  트러블(솟아오른 자국)이 보이는가

규칙
- 병명이나 진단으로 읽히는 말을 쓰지 않는다. "여드름" "피부염" "치료" 금지.
- summary는 보이는 것만 한 문장으로. 30자 이내, "~해요" 체.
  "턱 주변에 트러블이 보여요" "볼이 조금 붉어 보여요" "전반적으로 건조해 보여요"
- 조명이나 화질 때문에 확신이 없으면 그 신호는 false로 둔다. 없는 걸 있다고 하지 않는다.
- **얼굴은 보이는데 네 신호가 다 없으면 그대로 전부 false로 두고 summary는 빈 문자열로 둔다.**
  이건 정상이다. 억지로 신호를 만들어 내지 않는다. face는 true로 유지한다.

출력은 JSON만.
{"face":bool,"dry":bool,"oily":bool,"redness":bool,"trouble":bool,"summary":"..."}"""

# 곧바로 성분 목록을 뽑게 하면 읽지 못한 자리를 아는 성분으로 메운다.
# 실측에서 "프로판다이올"을 "모로칸용암"으로, "1,2-헥산다이올"을 "쉐어버터"로 바꿔 놨다.
# 시어버터 기반 제형의 전형적 조합이 통째로 들어오는 식이라 그럴듯해서 걸러지지도 않는다.
# 먼저 보이는 대로 옮겨 적게 하고 그 transcript에서만 뽑게 하면 사라진다.
_OCR_SYSTEM = """화장품 전성분표 사진을 읽는다.

먼저 transcript에 "전성분" 표기 이후의 글자를 **보이는 그대로** 옮겨 적는다.
띄어쓰기·쉼표·괄호까지 사진에 있는 대로. 안 보이는 글자는 ? 로 표시한다.
그다음 transcript를 쉼표로 끊어 ingredients 배열에 담는다.

절대 규칙
- transcript에 없는 단어를 ingredients에 넣지 않는다.
- 흐릿해서 확신이 없으면 그 성분은 빼고 unreadable 배열에 남긴다.
- 아는 화장품 성분으로 추측해서 채우지 않는다. 빠뜨리는 편이 낫다.
- 순서는 표기 그대로. 함량 순이라 순서가 중요하다.
- 괄호는 원문 그대로 둔다. 하이드로제네이티드폴리(C6-14올레핀)처럼 괄호까지가 이름인 경우가 있다.
- 제품명·주의사항·고객센터 번호는 제외한다.
- 증정품이 함께 인쇄돼 [본품] [증정]처럼 나뉘어 있으면 본품 것만 읽는다.

출력은 JSON만. {"transcript":"...","ingredients":[...],"unreadable":[...]}"""


def _b64(image: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(image).decode()}"


def _json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        raise ValueError("JSON을 찾지 못했다")
    return json.loads(m.group(0))


NO_FINDING = "오늘은 특별한 이상이 없어요"


async def read_skin(client, image: bytes, *, model: str = MODEL) -> dict | None:
    """셀카 → {dry, oily, redness, trouble, summary}. **판독에 실패했을 때만** None.

    셀카는 보조 신호다(docs/PLAN.md). 실패해도 루틴은 날씨와 화장대로 만든다 —
    그래서 예외를 올리지 않고 None을 준다.

    None과 "특이사항 없음"은 다르다.
      None                    호출 실패·타임아웃·얼굴 없음 → 화면 4에 피부 영역을 그리지 않는다
      summary=NO_FINDING      잘 읽었고 신호가 하나도 없었다 → "오늘은 특별한 이상이 없어요"

    예전에는 둘을 모두 None으로 뭉쳤다. 실측에서 얼굴 6장 중 3장이 여기 걸려
    멀쩡한 판독이 실패로 처리됐다.
    """
    try:
        res = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SKIN_SYSTEM},
                {"role": "user", "content": [
                    {"type": "text", "text": "이 사진의 피부 상태를 판단해 줘."},
                    {"type": "image_url", "image_url": {"url": _b64(image), "detail": "low"}},
                ]},
            ],
            response_format={"type": "json_object"},
            temperature=0.2, max_tokens=200, timeout=SKIN_TIMEOUT,
        )
        d = _json(res.choices[0].message.content)
    except Exception as e:
        log.warning("셀카 판독 실패: %s", e)
        return None

    return _interpret(d)


def _interpret(d: dict) -> dict | None:
    """모델 응답 → 반환값. 네트워크를 타지 않아 그대로 테스트할 수 있다."""
    # face 키가 빠진 응답은 얼굴이 있는 것으로 본다. 없다고 단정하면 멀쩡한 판독이
    # 다시 실패로 잡히는데, 그게 원래 고치려던 문제다
    if not bool(d.get("face", True)):
        log.info("셀카에서 얼굴을 찾지 못했다")
        return None

    summary = (d.get("summary") or "").strip()
    if any(w in summary for w in _BANNED):  # 원칙 3 — 걸리면 문장을 버린다
        log.warning("셀카 요약에 진단 표현이 섞여 버림: %r", summary)
        summary = ""
    flags = {k: bool(d.get(k)) for k in ("dry", "oily", "redness", "trouble")}
    if not any(flags.values()):
        # 얼굴은 읽었는데 신호가 없다. 문구를 모델에 맡기지 않고 서버가 고정한다 —
        # 매번 표현이 흔들리면 화면 4가 지저분해지고 금칙어가 섞일 여지도 생긴다
        return {**flags, "summary": NO_FINDING}
    # 신호는 있는데 summary가 금칙어로 비워진 경우 빈 문자열로 남긴다.
    # 없는 문장을 지어내는 것보다 화면에서 한 줄 비는 편이 낫다
    return {**flags, "summary": summary[:40]}


async def read_ingredients(client, image: bytes, *, model: str = MODEL) -> list[str]:
    """전성분표 사진 → 성분명 목록(원문 그대로). 매칭은 matching.py가 한다."""
    res = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _OCR_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": "이 전성분표를 읽어 줘."},
                # 작은 글씨라 detail=high가 필요하다. low로는 성분명이 뭉개진다
                {"type": "image_url", "image_url": {"url": _b64(image), "detail": "high"}},
            ]},
        ],
        response_format={"type": "json_object"},
        # transcript까지 받으므로 출력이 두 배가 된다
        temperature=0, max_tokens=3000, timeout=OCR_TIMEOUT,
    )
    d = _json(res.choices[0].message.content)
    names = [str(n).strip() for n in (d.get("ingredients") or []) if str(n).strip()]
    if d.get("unreadable"):
        log.info("전성분표에서 못 읽은 부분 %d개", len(d["unreadable"]))
    return names


if __name__ == "__main__":
    # 판독 실패와 "특이사항 없음"이 갈리는지. 네트워크를 타지 않는다
    ok = _interpret({"face": True, "dry": False, "oily": True,
                     "redness": False, "trouble": False, "summary": "번들거려 보여요"})
    assert ok == {"dry": False, "oily": True, "redness": False,
                  "trouble": False, "summary": "번들거려 보여요"}, ok

    clear = _interpret({"face": True, "dry": False, "oily": False,
                        "redness": False, "trouble": False, "summary": ""})
    assert clear is not None and clear["summary"] == NO_FINDING, clear
    assert not any(clear[k] for k in ("dry", "oily", "redness", "trouble")), clear

    assert _interpret({"face": False, "dry": False, "oily": False,
                       "redness": False, "trouble": False, "summary": ""}) is None

    # face 키가 없는 구형 응답은 얼굴이 있는 것으로 본다
    assert _interpret({"dry": False, "oily": False, "redness": False,
                       "trouble": False, "summary": ""})["summary"] == NO_FINDING

    # 금칙어가 섞이면 문장만 버린다. 신호가 있으므로 None이 아니다 (원칙 3)
    banned = _interpret({"face": True, "dry": False, "oily": False,
                         "redness": True, "trouble": True, "summary": "여드름이 보여요"})
    assert banned["summary"] == "" and banned["trouble"] is True, banned

    # 금칙어를 지운 뒤 신호도 없으면 "특이사항 없음"이 된다
    assert _interpret({"face": True, "dry": False, "oily": False, "redness": False,
                       "trouble": False, "summary": "피부염 진단"})["summary"] == NO_FINDING

    print("vision 자체검사 통과")
