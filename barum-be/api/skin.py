"""피부 타입 분류 API 연동 자리 (구교승).

지금은 붙이지 않는다. 배포본을 실제로 호출해 본 결과 판단 보류가 100%였다 —
얼굴 6장 + 대조군 1장 전부 needs_review=true, confidence 중앙값 0.32(임계값 0.55).
상세는 docs/SKIN_MODEL_API.md 부록 B.

붙일 때 지킬 것
  - needs_review가 true면 버린다. 확률만 보고 타입을 확정하지 않는다(명세가 금지한다).
  - false이고 dry/oily일 때만 루틴 프롬프트에 한 줄 더한다.
  - 실패·타임아웃은 무시하고 진행한다. 셀카는 보조 신호라 없어도 루틴이 나온다.
  - 이 결과로 병명을 말하지 않는다(원칙 3).

셀카 판독 자체는 vision.read_skin()이 GPT-4o Vision으로 하고 있다.
이 API는 그것을 보강하는 용도지 대체가 아니다.
"""

import logging
import os

import httpx

log = logging.getLogger(__name__)

BASE = os.environ.get("SKIN_MODEL_URL", "")  # 비어 있으면 호출하지 않는다
TIMEOUT = 5.0


async def classify(image: bytes) -> dict | None:
    """{predicted_class, confidence} 또는 None. 지금은 SKIN_MODEL_URL이 없어 항상 None."""
    if not BASE:
        return None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{BASE.rstrip('/')}/predict",
                             files={"file": ("selfie.jpg", image, "image/jpeg")})
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        log.warning("피부 분류 호출 실패: %s", e)
        return None

    if d.get("needs_review") or not d.get("predicted_class"):
        return None  # 판단 보류는 결과가 아니다
    return {"predicted_class": d["predicted_class"], "confidence": d.get("confidence")}
