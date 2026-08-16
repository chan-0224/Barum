"""바름 AI 서버 (FastAPI).

  GET  /health                          헬스체크
  GET  /internal/v1/context/daily       날씨 컨텍스트      ← Spring
  POST /internal/v1/ocr/ingredients     전성분표 OCR       ← Spring
  POST /internal/v1/routines/stream     루틴 카드 SSE      ← 프론트가 직접

원칙 6 — 이 서버는 DB에 쓰지 않는다. 읽고 결과만 반환한다.

실행
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import logging
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from starlette.exceptions import HTTPException as StarletteHTTPException

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from api import context, ocr, routines  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("barum")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 클라이언트를 요청마다 만들지 않는다. 커넥션 재사용이 지연에 그대로 반영된다
    app.state.openai = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    log.info("AI 서버 기동")
    yield
    await app.state.openai.close()


# /docs는 개발·통합용이라 기본은 꺼짐. 끄는 걸 잊는 쪽이 켜는 걸 잊는 쪽보다 비싸다.
# 켜려면 DOCS_ENABLED=true
_DOCS = os.environ.get("DOCS_ENABLED", "").lower() in ("1", "true", "yes")

app = FastAPI(
    title="바름 AI 서버",
    version="0.1.0",
    description="""Spring·프론트가 부르는 AI 엔드포인트. 명세 원본은 `docs/API.md` 3부.

- `/internal/v1/context/daily`, `/internal/v1/ocr/ingredients` — **Spring**이 부른다. `X-Internal-Key`
- `/internal/v1/routines/stream` — **프론트가 직접** 부른다. Supabase 익명 세션 JWT.
  SSE라 Swagger의 Try it out으로는 스트림이 제대로 안 보인다. curl이나 브라우저로 확인할 것

이 서버는 DB에 쓰지 않는다. 저장은 Spring이 한다.""",
    lifespan=lifespan,
    docs_url="/docs" if _DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _DOCS else None,
)

# 루틴 SSE만 프론트가 직접 부른다. 나머지는 Spring이 부르므로 브라우저를 타지 않는다.
#
# Spring과 같은 환경변수를 쓴다. * 가 들어간 항목은 정규식으로 바꿔 넘긴다 —
# 개발 중에는 프론트 포트가 바뀌고(Vite 5173 등), localhost와 127.0.0.1도 다른 오리진이라
# 하나씩 적다 보면 프리플라이트 403으로 시간을 버린다.
_origins = [o.strip() for o in
            os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
_exact = [o for o in _origins if "*" not in o]
_patterns = [re.escape(o).replace(r"\*", r"[^/]*") for o in _origins if "*" in o]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_exact,
    allow_origin_regex="|".join(f"^{p}$" for p in _patterns) if _patterns else None,
    allow_methods=["GET", "POST", "OPTIONS"],
    # Spring과 같은 이유로 "*". 목록으로 두면 Accept 같은 헤더 하나 빠졌을 때 프리플라이트가 깨진다
    allow_headers=["*"],
    max_age=3600,
)

app.include_router(context.router)
app.include_router(ocr.router)
app.include_router(routines.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai",
            "openai": bool(os.environ.get("OPENAI_API_KEY"))}


# FastAPI 기본 오류는 {"detail": ...}인데 프론트는 {code, message} 하나로 처리한다.
# 형식이 둘이면 화면마다 분기가 생긴다(docs/API.md 공통 에러)
_STATUS_CODE = {
    400: "VALIDATION_ERROR", 401: "UNAUTHORIZED", 404: "PRODUCT_NOT_FOUND",
    409: "EMPTY_VANITY", 422: "OCR_NO_TEXT", 502: "EXTERNAL_API_ERROR", 504: "AI_TIMEOUT",
}


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": _STATUS_CODE.get(exc.status_code, "EXTERNAL_API_ERROR"),
                 "message": str(detail)})


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc: RequestValidationError):
    return JSONResponse(status_code=400,
                        content={"code": "VALIDATION_ERROR", "message": "요청 값을 확인해 주세요."})


@app.exception_handler(Exception)
async def unexpected(request, exc):
    # 예외 메시지를 그대로 흘리면 내부 경로나 키가 노출된다
    log.exception("처리되지 않은 예외")
    return JSONResponse(status_code=500,
                        content={"code": "EXTERNAL_API_ERROR", "message": "일시적인 오류가 발생했습니다."})
