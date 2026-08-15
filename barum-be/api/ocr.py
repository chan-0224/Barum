"""POST /internal/v1/ocr/ingredients — 전성분표 OCR.

Spring이 부른다(docs/API.md B-1). **쓰기 없음** — 저장은 Spring이 한다(원칙 6).
GPT-4o Vision으로 읽고 matching.py로 표준명에 맞춘다.
카탈로그 일괄 정규화와 같은 규칙을 쓴다 — 한쪽만 고치면 결과가 갈라진다.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import supa
import vision
from api.deps import internal_key
from matching import match_name, split_ingredients

log = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/v1/ocr", tags=["ocr"])


class OcrRequest(BaseModel):
    storagePath: str
    bucket: str = "labels"


@router.post("/ingredients", dependencies=[Depends(internal_key)])
async def ingredients(req: OcrRequest, request: Request):
    try:
        image = await supa.download(req.bucket, req.storagePath)
    except Exception as e:
        log.warning("이미지 읽기 실패 %s/%s: %s", req.bucket, req.storagePath, e)
        raise HTTPException(422, "이미지를 읽지 못했습니다.")

    try:
        names = await vision.read_ingredients(request.app.state.openai, image)
    except Exception as e:
        log.warning("OCR 실패: %s", e)
        raise HTTPException(504, "인식이 지연되고 있습니다.")

    # 모델이 한 줄로 뱉는 경우가 있어 한 번 더 분해한다
    tokens = []
    for n in names:
        tokens += split_ingredients(n) or [n]

    by_std, by_syn, id_to_std = await supa.fetch_ingredient_index()
    out = []
    for t in tokens:
        std = match_name(t, by_std, by_syn, id_to_std)
        # 매칭 실패해도 원문은 남긴다. 화면 10이 회색으로 보여준다
        out.append({"rawName": t, "standardName": std, "matched": std is not None})

    matched = sum(1 for x in out if x["matched"])
    if not out:
        raise HTTPException(422, "전성분표를 읽지 못했습니다.")
    return {"ingredients": out, "matchedCount": matched, "totalCount": len(out)}
