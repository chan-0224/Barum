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

네 가지 신호의 유무만 판단한다.
  dry      건조해 보이는가 (각질, 당김)
  oily     번들거리는가
  redness  붉은 기가 있는가
  trouble  트러블(솟아오른 자국)이 보이는가

규칙
- 병명이나 진단으로 읽히는 말을 쓰지 않는다. "여드름" "피부염" "치료" 금지.
- summary는 보이는 것만 한 문장으로. 30자 이내, "~해요" 체.
  "턱 주변에 트러블이 보여요" "볼이 조금 붉어 보여요" "전반적으로 건조해 보여요"
- 얼굴이 없거나 판단이 어려우면 모든 신호를 false로 두고 summary를 빈 문자열로 둔다.
- 조명이나 화질 때문에 확신이 없으면 false로 둔다. 없는 걸 있다고 하지 않는다.

출력은 JSON만.
{"dry":bool,"oily":bool,"redness":bool,"trouble":bool,"summary":"..."}"""

_OCR_SYSTEM = """화장품 전성분표 사진에서 성분명만 순서대로 읽는다.

규칙
- 표기된 순서 그대로. 함량 순이라 순서가 중요하다.
- 성분명만. "전성분", "성분정보" 같은 머리말이나 제품명은 제외한다.
- 괄호는 원문 그대로 둔다. 하이드로제네이티드폴리(C6-14올레핀)처럼 괄호까지가 이름인 경우가 있다.
- 읽히지 않는 글자는 건너뛴다. 추측해서 지어내지 않는다.
- 증정품이 함께 인쇄돼 [본품] [증정]처럼 나뉘어 있으면 본품 것만 읽는다.

출력은 JSON만. {"ingredients":["정제수","글리세린",...]}"""


def _b64(image: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(image).decode()}"


def _json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        raise ValueError("JSON을 찾지 못했다")
    return json.loads(m.group(0))


async def read_skin(client, image: bytes, *, model: str = MODEL) -> dict | None:
    """셀카 → {dry, oily, redness, trouble, summary}. 실패하면 None.

    셀카는 보조 신호다(docs/PLAN.md). 실패해도 루틴은 날씨와 화장대로 만든다 —
    그래서 예외를 올리지 않고 None을 준다.
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

    summary = (d.get("summary") or "").strip()
    if any(w in summary for w in _BANNED):  # 원칙 3 — 걸리면 문장을 버린다
        log.warning("셀카 요약에 진단 표현이 섞여 버림: %r", summary)
        summary = ""
    flags = {k: bool(d.get(k)) for k in ("dry", "oily", "redness", "trouble")}
    if not summary and not any(flags.values()):
        return None  # 아무것도 못 읽었다
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
        temperature=0, max_tokens=2000, timeout=OCR_TIMEOUT,
    )
    d = _json(res.choices[0].message.content)
    names = d.get("ingredients") or []
    return [str(n).strip() for n in names if str(n).strip()]
