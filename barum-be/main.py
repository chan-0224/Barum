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
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI

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


app = FastAPI(title="barum AI", version="0.1.0", lifespan=lifespan)

# 루틴 SSE만 프론트가 직접 부른다. 나머지는 Spring이 부르므로 브라우저를 타지 않는다
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in
                   os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
                   if o.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Internal-Key"],
    max_age=3600,
)

app.include_router(context.router)
app.include_router(ocr.router)
app.include_router(routines.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai",
            "openai": bool(os.environ.get("OPENAI_API_KEY"))}


@app.exception_handler(Exception)
async def unexpected(request, exc):
    # 예외 메시지를 그대로 흘리면 내부 경로나 키가 노출된다
    log.exception("처리되지 않은 예외")
    return JSONResponse(status_code=500,
                        content={"code": "EXTERNAL_API_ERROR", "message": "일시적인 오류가 발생했습니다."})
