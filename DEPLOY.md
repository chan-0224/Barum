# 배포

가비아 클라우드 (2vCPU / 4GB / Ubuntu). 프론트는 Vercel이라 여기 없다.

```
인터넷 → Traefik(80/443) ─┬─ /api/v1      → Spring   :8080
                          └─ /internal/v1 → FastAPI  :8000
                     ↑
              socket-proxy (컨테이너 목록 조회 전용)
```

## ⚠ 먼저 읽을 것 — 8/13 맥미니 리허설에서 잡은 함정 3개

서버에서 처음 만나면 시간을 버린다. 셋 다 **compose 파일에 이미 반영돼 있으니 건드리지 말 것.**

**1. Traefik은 v3.7 이상이어야 한다.** 그 아래 버전은 도커 API를 `/v1.24/`로 부르는데
Docker 29는 1.40 미만을 400으로 거부한다. 그러면 라우터가 하나도 등록되지 않아
**모든 요청이 404**가 되는데, 에러는 Traefik 로그에만 남고 응답은 평범한 404라
원인을 찾기 어렵다. `DOCKER_API_VERSION` 환경변수로는 안 고쳐진다(초기 version 호출에 반영되지 않음).
`get.docker.com`은 최신 Docker를 설치하므로 **서버에서도 그대로 재현된다.**

**2. 도커 소켓을 Traefik에 직접 물리지 않는다.** `socket-proxy`를 거친다.
Docker Desktop 29에서 직접 마운트가 400을 돌려준 것이 계기였지만, 보안상으로도 이쪽이 맞다 —
도커 소켓은 사실상 root 권한인데 컨테이너 목록만 읽으면 되는 Traefik에 전부 줄 이유가 없다.
읽기 계열만 열고 생성·삭제·재시작은 막아 뒀다.

**3. 호스트 포트는 `${HTTP_PORT:-80}`이다.** 서버에서는 그대로 80을 쓴다.
로컬에 이미 80을 점유한 스택이 있을 때만 `HTTP_PORT=8081`처럼 비켜간다.

## ⚠ 아키텍처 — 맥미니에서 빌드한 이미지는 서버에서 안 돈다

맥미니는 **arm64**, 가비아 클라우드는 **amd64**다. 맥에서 만든 이미지를 그대로 올리면
`exec format error`가 난다.

**서버에서 직접 빌드하는 걸 기본으로 한다.** 레지스트리도 필요 없고 아키텍처 문제도 사라진다.
2vCPU에서 Spring 빌드가 2~3분 걸리는데, 마감 전 며칠이면 그게 제일 싸다.

굳이 맥에서 만들어 올려야 하면 `docker buildx build --platform linux/amd64` 를 쓴다.

## 로컬 리허설 (맥미니, 8/18 전)

HTTP만 뜬다. 인증서는 도메인이 필요해서 서버에서만 붙는다.

```bash
cp .env.production.example .env.production   # 값 채우기
echo 'HTTP_PORT=8081' >> .env.production     # 로컬에 80을 쓰는 스택이 있을 때만
docker compose --env-file .env.production up -d --build
curl http://localhost/api/v1/health
curl "http://localhost/api/v1/catalog/products?size=3"
```

**`--env-file`을 빼면 안 된다.** `env_file:`은 변수를 컨테이너 안으로 넣어줄 뿐,
compose 자신의 `${DOMAIN}` 치환에는 쓰이지 않는다. 빼면 라우팅 규칙이 `Host(``)`가 되어
**아무 요청도 매칭되지 않는데 에러는 나지 않는다.**

리허설에서 확인할 것 — **서버에서 처음 겪으면 시간을 버린다**

- [x] Spring이 Supabase에 붙는가 (`/api/v1/health` 의 `db: UP`) — 확인
- [x] 익명 토큰으로 인증이 통과하는가 (ES256) — 타임라인·업로드 URL 200
- [x] 카탈로그 조회와 `keyIngredients` 뷰 — SERUM 38건, 검색 정상
- [x] 컨테이너 메모리 — spring 190MB/1.25GB, traefik 21MB/128MB (배정의 15%)
- [x] FastAPI 없이도 나머지가 도는가 — 날씨만 502, 그 외 정상

**8/13 리허설 결과: 빌드 41초 / 이미지 344MB.** FastAPI를 뺀 전 구간 통과.

## 서버 배포 (8/18~)

```bash
# 1. 도커 설치
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# 2. 코드 + 환경변수
git clone https://github.com/chan-0224/Barum.git && cd Barum
cp .env.production.example .env.production
vi .env.production          # DOMAIN, ACME_EMAIL 포함해 전부 채운다
#
# .env.production 은 커밋되지 않는다(Public 레포). 서버에서 직접 만들어야 한다.
# 값은 로컬 spring/.env 와 barum-be/.env 에 있다. 안전한 경로로 옮길 것 —
# Slack DM·메신저는 로그가 남는다. scp 를 쓰거나 화면 보고 직접 입력한다.
# JDBC URL은 & 때문에 반드시 따옴표로 감싼다.

# 3. 방화벽 — HTTP-01 챌린지가 80을 쓴다. 막혀 있으면 발급이 실패한다
sudo ufw allow 80,443/tcp

# 4. 올리기 전 치환 확인 — Host(``) 로 나오면 --env-file 이 빠진 것이다
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml config | grep routers.spring.rule

# 5. 기동
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

**DNS A 레코드를 먼저 걸고 전파를 확인한 뒤에 올릴 것.** 발급 실패를 반복하면
Let's Encrypt 레이트 리밋(주 5회/도메인)에 걸려 그 주 내내 인증서를 못 받는다.
자신 없으면 스테이징 CA로 먼저 시험한다 — `docker-compose.prod.yml` 상단 주석 참조.

## 메모리 배분 (4GB)

| 서비스 | 한도 | 실사용(리허설) | 비고 |
|---|---|---|---|
| traefik | 128m | 21m | |
| socket-proxy | 64m | 4m | 컨테이너 목록 조회만 중계 |
| spring | 1280m | 190m | 힙은 65%(~830m). 나머지는 메타스페이스·스레드 몫 |
| fastapi | 640m | — | 외부 API 대기가 대부분이라 여유 있다 |
| **합계** | **2112m** | | 나머지 ~1.9GB는 Ubuntu + 도커 데몬 |

JVM에 `-Xmx`를 직접 주지 않고 `MaxRAMPercentage`를 쓴다. 컨테이너 한도를 바꾸면
힙도 따라 움직인다. `-XX:+ExitOnOutOfMemoryError`라 힙이 터지면 좀비로 남지 않고
죽어서 재시작된다.

## 헬스체크

| 대상 | 경로 |
|---|---|
| Spring | `GET /api/v1/health` → `{status, db, time}` |
| FastAPI | `GET /health` (구교승 담당분에서 추가 필요) |
| 컨테이너 | `docker compose ps` 의 STATUS |

Spring 헬스체크는 **DB까지 확인한다.** 프로세스만 살아 있고 Supabase 연결이 끊긴 상태를
정상으로 보고하면 의미가 없다.

## 상태

| 항목 | |
|---|---|
| Spring | 준비됨 |
| Traefik + TLS | 준비됨 (도메인 대기) |
| **FastAPI** | **`main.py` 없음 — 컨테이너가 기동하지 않는다.** 구교승 담당분 |

FastAPI가 없으면 날씨(API.md 1)가 502로 떨어진다. Spring은 정상 동작하고
화면도 날씨 영역만 비운 채 돈다(SCREENS.md 화면 1의 예외 처리).

## 자주 나오는 문제

| 증상 | 원인 |
|---|---|
| `exec format error` | 맥에서 빌드한 arm64 이미지. 서버에서 다시 빌드 |
| 모든 요청 401 | JWT 알고리즘. Supabase는 ES256인데 Spring 기본값이 RS256이다 |
| `prepared statement already exists` | JDBC URL에 `prepareThreshold=0` 누락 |
| 인증서 발급 실패 | DNS 미전파 또는 80 포트 차단 |
| Spring OOM 재시작 반복 | `mem_limit`을 올리거나 `MaxRAMPercentage`를 낮춘다 |
| 404만 나오고 로그에 라우팅 없음 | `--env-file` 누락. `Host(``)`가 되어 매칭이 안 된다 |
| **모든 요청 404 + Traefik 로그에 `API returned a 400`** | **Traefik이 v3.7 미만.** 도커 API 버전 거부 |
| `Bind for 0.0.0.0:80 failed` | 80을 쓰는 다른 스택이 있다. `HTTP_PORT`로 비켜간다 |
