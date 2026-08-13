# FastAPI AI 서버.
#
# ※ 앱 진입점(main.py)은 구교승님 작업분이다. 이 Dockerfile은 자리만 잡아둔 것으로,
#   main.py가 없으면 컨테이너가 기동하지 않는다(빌드는 된다).
#   최소 요구사항: `app = FastAPI()` 를 노출하는 main.py + GET /health
#
# 붙어야 할 엔드포인트 (docs/API.md 3부)
#   GET  /internal/v1/context/daily   날씨 — daily_context.get_daily_context() 래핑
#   POST /internal/v1/ocr/ingredients 전성분표 OCR
#   POST /internal/v1/routines/stream 루틴 SSE (프론트가 직접 호출한다)

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Seoul

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m app && chown -R app:app /app
USER app

EXPOSE 8000

# 2vCPU라 워커를 늘리지 않는다. 외부 API 대기가 대부분이라 async 한 프로세스로 충분하고,
# 워커를 늘리면 daily_context의 프로세스 로컬 캐시가 워커 수만큼 쪼개진다
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
