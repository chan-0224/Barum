"""POST /internal/v1/routines/stream — 루틴 카드 SSE.

**프론트가 직접 호출한다**(docs/API.md 8). Spring을 거치면 SSE가 버퍼링된다.
이벤트 구조는 docs/API.md 그대로다. 순서도 고정이다:

    stage(SKIN) → stage(WEATHER) → context → stage(PICK) → conflict
      → item × N → done

conflict가 item보다 먼저 나가는 것이 중요하다. 경고 배지가 카드 본문보다 늦게 뜨면
사용자가 이미 읽은 뒤에 경고가 붙는다.
"""

import asyncio
import json
import logging
import os
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import conflicts
import routine
import supa
import vision
from api.deps import user_jwt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/v1/routines", tags=["routines"])

SEOUL = (37.5665, 126.9780)


class RoutineRequest(BaseModel):
    selfiePath: str | None = None
    lat: float | None = None
    lon: float | None = None


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _events(req: RoutineRequest, jwt: str, client):
    try:
        yield sse("stage", {"stage": "SKIN", "label": "피부 상태 확인 중"})

        # 화장대와 셀카 판독을 함께 시작한다. 셀카가 없으면 화장대만 기다린다
        vanity_task = asyncio.create_task(supa.fetch_vanity(jwt))
        skin_task = None
        if req.selfiePath:
            async def _skin():
                img = await supa.download("selfies", req.selfiePath, jwt)
                return await vision.read_skin(client, img)
            skin_task = asyncio.create_task(_skin())

        products = await vanity_task
        if not products:
            yield sse("error", {"code": "EMPTY_VANITY", "message": "화장대에 등록된 제품이 없습니다."})
            return

        skin = None
        if skin_task:
            try:
                skin = await skin_task
            except Exception as e:  # 셀카는 보조 신호다. 실패해도 계속 간다
                log.warning("셀카 처리 실패: %s", e)

        yield sse("stage", {"stage": "WEATHER", "label": "오늘 날씨 반영 중"})
        from daily_context import get_daily_context, nearest_sido
        lat = req.lat if req.lat is not None else SEOUL[0]
        lon = req.lon if req.lon is not None else SEOUL[1]
        try:
            weather = await get_daily_context(lat, lon)
        except Exception as e:
            log.warning("날씨 조회 실패: %s", e)
            weather = {"temp": None, "humidity": None, "pm10": None, "pm25": None}
        weather = {**weather, "summary": _weather_summary(weather),
                   "regionLabel": nearest_sido(lat, lon)}

        yield sse("context", {"weather": weather, "skin": skin})
        yield sse("stage", {"stage": "PICK", "label": "화장대에서 고르는 중"})

        by_product = {p["name"]: p["ingredients"] for p in products}
        badges = await conflicts.conflict_badges(by_product)
        raw = await conflicts.check_conflicts_by_product(by_product)
        avoid_ing = {n for c in raw if c["level"] == "AVOID" for n in c["ingredients"]}
        yield sse("conflict", {"pairs": badges})

        card = await routine.generate(client, weather, skin, products, badges, avoid_ing)

        by_name = {p["name"]: p["id"] for p in products}
        for a in card["apply"]:
            yield sse("item", {"type": "APPLY", "order": a["order"],
                               "productId": by_name.get(a["name"]),
                               "name": a["name"], "reason": a["reason"]})
        for s in card["skip"]:
            yield sse("item", {"type": "SKIP", "productId": by_name.get(s["name"]),
                               "name": s["name"], "reason": s["reason"]})

        # recordDraftId는 프론트가 기록 저장(API.md 9)에 붙여 보내는 식별자다.
        # FastAPI는 DB에 쓰지 않으므로(원칙 6) 서버에 저장하지 않는다
        yield sse("done", {"recordDraftId": str(uuid.uuid4())})

    except routine.RoutineTimeout as e:
        log.warning("루틴 생성 시간 초과: %s", e)
        yield sse("error", {"code": "AI_TIMEOUT", "message": "분석이 지연되고 있습니다. 다시 시도해 주세요."})
    except Exception as e:
        log.exception("루틴 생성 실패")
        yield sse("error", {"code": "EXTERNAL_API_ERROR", "message": "일시적인 오류가 발생했습니다."})


def _weather_summary(w: dict) -> str:
    h, p = w.get("humidity"), w.get("pm10")
    moisture = None if h is None else ("건조해요" if h < 40 else ("습해요" if h > 70 else "적당해요"))
    air = None if p is None else ("미세먼지 좋음" if p <= 30 else
                                  ("미세먼지 보통" if p <= 80 else "미세먼지 나쁨"))
    if moisture and air:
        return moisture.replace("요", "고 ") + air + "이에요"
    return (air + "이에요") if air else (("오늘 공기가 " + moisture) if moisture else "")


@router.post("/stream")
async def stream(req: RoutineRequest, request: Request, jwt: str = Depends(user_jwt)):
    client = request.app.state.openai
    return StreamingResponse(
        _events(req, jwt, client),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # nginx/Traefik 앞단이 버퍼링하면 스트리밍이 의미를 잃는다
            "X-Accel-Buffering": "no",
        },
    )
