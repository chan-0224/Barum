"""GET /internal/v1/context/daily — 날씨 컨텍스트.

daily_context.py를 그대로 감싼다. 격자 변환·시도 판정·캐싱이 이미 거기 있고
실측 검증까지 끝났다(docs/DATA.md).
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import internal_key
from daily_context import get_daily_context, nearest_sido

router = APIRouter(prefix="/internal/v1/context", tags=["context"])

SEOUL = (37.5665, 126.9780)


@router.get("/daily", dependencies=[Depends(internal_key)])
async def daily(lat: float = Query(default=SEOUL[0]), lon: float = Query(default=SEOUL[1])):
    ctx = await get_daily_context(lat, lon)
    if ctx.get("temp") is None and ctx.get("pm10") is None:
        # 둘 다 실패면 보여줄 게 없다. 화면은 날씨 영역만 비운다(docs/SCREENS.md 화면 1)
        raise HTTPException(502, "날씨 정보를 불러오지 못했습니다.")
    return {**ctx, "regionLabel": nearest_sido(lat, lon)}
