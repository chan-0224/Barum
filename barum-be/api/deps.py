"""인증. 호출자가 둘이라 방식도 둘이다.

  Spring → FastAPI   X-Internal-Key (날씨·OCR)
  프론트 → FastAPI   Supabase 익명 세션 JWT (루틴 SSE만. docs/API.md 8)

루틴만 프론트가 직접 부르는 이유는 SSE 버퍼링을 피하기 위해서다.
"""

import os

from fastapi import Header, HTTPException


def internal_key(x_internal_key: str = Header(default="")) -> None:
    """Spring이 부르는 내부 엔드포인트."""
    expected = os.environ.get("AI_INTERNAL_KEY", "")
    if not expected:
        raise HTTPException(503, "AI_INTERNAL_KEY가 설정되지 않았습니다.")
    if x_internal_key != expected:
        raise HTTPException(401, "내부 인증에 실패했습니다.")


def user_jwt(authorization: str = Header(default="")) -> str:
    """프론트가 직접 부르는 엔드포인트. 토큰을 그대로 Supabase에 넘겨 RLS를 태운다.

    여기서 서명을 검증하지 않는다. 잘못된 토큰이면 Supabase가 거부하므로
    남의 데이터가 새지 않는다. 검증을 두 곳에 두면 JWKS 캐시가 어긋날 때 원인을 찾기 어렵다.
    """
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "인증 토큰이 필요합니다.")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "인증 토큰이 필요합니다.")
    return token
