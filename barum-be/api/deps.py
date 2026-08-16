"""인증. 호출자가 둘이라 방식도 둘이다.

  Spring → FastAPI   X-Internal-Key (날씨·OCR)
  프론트 → FastAPI   Supabase 익명 세션 JWT (루틴 SSE만. docs/API.md 8)

루틴만 프론트가 직접 부르는 이유는 SSE 버퍼링을 피하기 위해서다.

Header(...) 대신 fastapi.security 클래스를 쓴다. 그래야 /docs에 Authorize 버튼이 생겨
영규형이 토큰을 넣고 눌러 볼 수 있다. auto_error=False로 두고 오류는 우리가 만든다 —
기본값은 403에 {"detail": ...} 형식이라 다른 응답과 어긋난다.
"""

import os

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="익명 세션 JWT",
    description="Supabase signInAnonymously()로 받은 access_token. Bearer 접두사는 빼고 값만.",
)
_internal = APIKeyHeader(
    name="X-Internal-Key",
    auto_error=False,
    scheme_name="내부 호출 키",
    description="Spring이 AI 서버를 부를 때 쓰는 공유 키. 프론트는 쓰지 않는다.",
)


def internal_key(key: str | None = Depends(_internal)) -> None:
    """Spring이 부르는 내부 엔드포인트."""
    expected = os.environ.get("AI_INTERNAL_KEY", "")
    if not expected:
        raise HTTPException(503, "AI_INTERNAL_KEY가 설정되지 않았습니다.")
    if key != expected:
        raise HTTPException(401, "내부 인증에 실패했습니다.")


def user_jwt(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """프론트가 직접 부르는 엔드포인트. 토큰을 그대로 Supabase에 넘겨 RLS를 태운다.

    여기서 서명을 검증하지 않는다. 잘못된 토큰이면 Supabase가 거부하므로
    남의 데이터가 새지 않는다. 검증을 두 곳에 두면 JWKS 캐시가 어긋날 때 원인을 찾기 어렵다.
    """
    if cred is None or not (cred.credentials or "").strip():
        raise HTTPException(401, "인증 토큰이 필요합니다.")
    return cred.credentials.strip()
