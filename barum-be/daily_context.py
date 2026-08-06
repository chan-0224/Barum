"""오늘의 날씨 컨텍스트 — 기상청 단기예보 + 에어코리아를 함수 하나로 추상화.

사용:
    cp .env.example .env  후 DATA_GO_KR_KEY 채우고
    pip install httpx python-dotenv
    python daily_context.py            # 자체검증 + 실제 호출 테스트

주의: httpx가 파라미터를 자동 인코딩하므로 data.go.kr **Decoding 키**를 넣을 것.
발급 직후 ~1시간은 SERVICE_KEY_IS_NOT_REGISTERED_ERROR가 정상이다.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from math import cos, log, pi, sin, tan

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

KST = timezone(timedelta(hours=9))
KMA_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
AIR_URL = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getCtprvnRltmMesureDnsty"


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """위경도 → 기상청 격자좌표(nx, ny). Lambert Conformal Conic, 기상청 공식 파라미터."""
    RE, GRID, SLAT1, SLAT2, OLON, OLAT, XO, YO = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    DEGRAD = pi / 180.0
    re, slat1, slat2 = RE / GRID, SLAT1 * DEGRAD, SLAT2 * DEGRAD
    olon, olat = OLON * DEGRAD, OLAT * DEGRAD

    sn = log(cos(slat1) / cos(slat2)) / log(tan(pi * 0.25 + slat2 * 0.5) / tan(pi * 0.25 + slat1 * 0.5))
    sf = tan(pi * 0.25 + slat1 * 0.5) ** sn * cos(slat1) / sn
    ro = re * sf / tan(pi * 0.25 + olat * 0.5) ** sn

    ra = re * sf / tan(pi * 0.25 + lat * DEGRAD * 0.5) ** sn
    theta = lon * DEGRAD - olon
    if theta > pi:
        theta -= 2.0 * pi
    if theta < -pi:
        theta += 2.0 * pi
    theta *= sn
    return int(ra * sin(theta) + XO + 0.5), int(ro - ra * cos(theta) + YO + 0.5)


# 광역시도 17개 행정중심 좌표 → 에어코리아 sidoName. 좌표만 있으면 되므로 API 콜 0.
_SIDO = {
    "서울": (37.5665, 126.9780), "부산": (35.1796, 129.0756), "대구": (35.8714, 128.6014),
    "인천": (37.4563, 126.7052), "광주": (35.1595, 126.8526), "대전": (36.3504, 127.3845),
    "울산": (35.5384, 129.3114), "세종": (36.4800, 127.2890), "경기": (37.4138, 127.5183),
    "강원": (37.8228, 128.1555), "충북": (36.8000, 127.7000), "충남": (36.5184, 126.8000),
    "전북": (35.7175, 127.1530), "전남": (34.8679, 126.9910), "경북": (36.4919, 128.8889),
    "경남": (35.4606, 128.2132), "제주": (33.4996, 126.5312),
}


def nearest_sido(lat: float, lon: float) -> str:
    """위경도 → 가장 가까운 광역시도명.

    ponytail: 경계 폴리곤이 아니라 중심점 최근접이라, 경기 남부가 서울로 붙는 식의 오차가 있다.
    미세먼지는 어차피 시도 평균값이라 인접 시도로 붙어도 수치 차이가 작아 감수한다.
    정밀도가 필요해지면 에어코리아 근접측정소 API(2콜 추가)로 교체.
    """
    # 위도 37.5도 기준 경도 1도의 실거리 보정계수(cos 37.5 ≈ 0.79)
    return min(_SIDO, key=lambda s: (lat - _SIDO[s][0]) ** 2 + ((lon - _SIDO[s][1]) * 0.79) ** 2)


_SLOTS = (2, 5, 8, 11, 14, 17, 20, 23)


def _base_datetime(now: datetime) -> tuple[str, str]:
    """직전 발표시각. 발표 +10분 후 제공되므로 45분 여유를 두고 고른다."""
    t = now - timedelta(minutes=45)
    for h in reversed(_SLOTS):
        if t.hour >= h:
            return t.strftime("%Y%m%d"), f"{h:02d}00"
    return (t - timedelta(days=1)).strftime("%Y%m%d"), "2300"


# ponytail: 프로세스 로컬 dict 캐시. 키에 시간 버킷이 들어있어 TTL 로직이 필요없다.
# 인스턴스가 2대 이상 되거나 동시 miss가 문제되면 Redis로 교체.
_cache: dict = {}


async def _cached(key, fn):
    if key in _cache:
        return _cache[key]
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = await fn()
    return _cache[key]


async def _get(client: httpx.AsyncClient, url: str, params: dict, timeout: float = 10) -> dict:
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        raise RuntimeError("DATA_GO_KR_KEY 환경변수가 없다. .env.example 참고")
    r = await client.get(url, params={**params, "serviceKey": key}, timeout=timeout)
    name = url.rsplit("/", 1)[-1]
    if r.is_error:
        # raise_for_status()는 URL을 통째로 찍어 serviceKey가 로그에 남는다. 본문만 노출한다.
        raise RuntimeError(f"{name} HTTP {r.status_code}: {r.text[:300]}")
    try:
        body = r.json()["response"]
    except (ValueError, KeyError):
        # 키 오류·미등록은 JSON을 요청해도 XML로 돌아온다
        raise RuntimeError(f"응답 파싱 실패 (Decoding 키인지 확인): {r.text[:300]}")
    header = body.get("header", {})
    if header.get("resultCode") not in ("00", "0"):
        raise RuntimeError(f"공공데이터 오류 {header.get('resultCode')}: {header.get('resultMsg')}")
    return body["body"]


async def _weather(client, nx, ny, base_date, base_time) -> dict:
    body = await _get(client, KMA_URL, {
        "pageNo": 1, "numOfRows": 1000, "dataType": "JSON",
        "base_date": base_date, "base_time": base_time, "nx": nx, "ny": ny,
    })
    latest = {}
    for item in body["items"]["item"]:
        latest.setdefault(item["category"], item["fcstValue"])  # fcstTime 오름차순 → 첫 등장이 가장 가까운 예보
    return {"temp": float(latest["TMP"]), "humidity": float(latest["REH"])}


async def _air(client, sido: str) -> dict:
    # 에어코리아는 첫 응답이 20초를 넘기기도 한다. 시간당 1회만 나가므로 넉넉히 준다.
    body = await _get(client, AIR_URL, {
        "returnType": "json", "numOfRows": 100, "pageNo": 1, "sidoName": sido, "ver": "1.0",
    }, timeout=40)

    def avg(field):  # 결측치는 "-" 또는 빈 문자열로 온다
        vals = [float(i[field]) for i in body["items"]
                if str(i.get(field) or "").replace(".", "", 1).isdigit()]
        return round(sum(vals) / len(vals)) if vals else None

    return {"pm10": avg("pm10Value"), "pm25": avg("pm25Value")}


async def get_daily_context(lat: float = 37.5665, lon: float = 126.9780, sido: str | None = None) -> dict:
    """오늘의 외부 컨텍스트. 소스 교체·캐싱은 이 함수 안에서만 일어난다.

    sido를 넘기지 않으면 위경도로 자동 판정한다. 매핑이 틀렸을 때만 직접 넘기면 된다.
    한쪽 API가 죽어도 나머지는 살린다 — 루틴 생성이 날씨 때문에 막히면 안 되므로.
    """
    sido = sido or nearest_sido(lat, lon)
    nx, ny = latlon_to_grid(lat, lon)
    now = datetime.now(KST)
    base_date, base_time = _base_datetime(now)

    ctx = {"temp": None, "humidity": None, "pm10": None, "pm25": None}

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            _cached(("kma", nx, ny, base_date, base_time),
                    lambda: _weather(client, nx, ny, base_date, base_time)),
            _cached(("air", sido, now.strftime("%Y%m%d%H")),
                    lambda: _air(client, sido)),
            return_exceptions=True,
        )
    for r in results:
        if isinstance(r, Exception):
            print(f"[daily_context] {type(r).__name__}: {r}", file=sys.stderr)
        else:
            ctx.update(r)
    return ctx


def _selfcheck():
    assert latlon_to_grid(37.5665, 126.9780) == (60, 127), "서울시청 격자"
    assert latlon_to_grid(35.1796, 129.0756) == (98, 76), "부산시청 격자"
    assert latlon_to_grid(33.4996, 126.5312) == (53, 38), "제주시청 격자"

    assert nearest_sido(37.5665, 126.9780) == "서울"
    assert nearest_sido(35.1631, 129.1637) == "부산", "해운대"
    assert nearest_sido(33.4996, 126.5312) == "제주"
    assert nearest_sido(37.7519, 128.8761) == "강원", "강릉"
    assert nearest_sido(35.8242, 127.1480) == "전북", "전주"

    d = datetime(2026, 8, 5, 9, 0, tzinfo=KST)
    assert _base_datetime(d) == ("20260805", "0800"), "09:00 → 08시 발표"
    assert _base_datetime(d.replace(hour=8, minute=30)) == ("20260805", "0500"), "08:30은 아직 05시 발표"
    assert _base_datetime(d.replace(hour=0, minute=30)) == ("20260804", "2300"), "자정 직후는 전날 23시"
    print("selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
    print(asyncio.run(get_daily_context()))
