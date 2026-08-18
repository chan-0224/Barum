"""유저당 호출 빈도 제한. 루틴 생성은 1회에 GPT-4o를 두 번 부른다(약 $0.0055).

익명 로그인이라 계정을 얼마든지 만들 수 있으므로 이걸로 비용 공격을 완전히 막지는
못한다. 다만 실측에서 제품 1000개짜리 요청 하나가 분당 토큰 한도(TPM 30,000)를
넘겨 서비스 전체를 429로 만들었다 — 한 사람이 우연히든 고의로든 전체를 멈추는 걸
막는 것이 목적이다. 제품 수 상한(Spring)과 짝을 이룬다.

인메모리라 프로세스마다 따로 센다. 지금은 FastAPI가 한 컨테이너라 문제없고,
여러 대로 늘리면 Redis로 옮겨야 한다.
"""

import time
from collections import deque

# 분당 허용 횟수. 아침에 한 번 쓰는 서비스라 5회면 재시도까지 충분하다
LIMIT = 5
WINDOW = 60.0

# {user_id: 호출 시각 deque}. 오래된 항목은 조회할 때 흘려보낸다
_hits: dict[str, deque] = {}

# 죽은 유저의 키가 쌓이는 걸 막는다. 익명 계정이라 한 번 쓰고 사라지는 유저가 대부분이다
_MAX_KEYS = 10_000


def check(user_id: str, *, limit: int = LIMIT, window: float = WINDOW) -> float:
    """호출을 기록하고, 한도를 넘었으면 몇 초 뒤에 풀리는지 돌려준다. 여유가 있으면 0."""
    now = time.monotonic()
    q = _hits.setdefault(user_id, deque())
    while q and now - q[0] >= window:
        q.popleft()

    if len(q) >= limit:
        return max(0.0, window - (now - q[0]))

    q.append(now)
    if len(_hits) > _MAX_KEYS:
        _sweep(now, window)
    return 0.0


def _sweep(now: float, window: float) -> None:
    for k in [k for k, v in _hits.items() if not v or now - v[-1] >= window]:
        _hits.pop(k, None)


def reset() -> None:
    """테스트용."""
    _hits.clear()


if __name__ == "__main__":
    reset()
    assert all(check("u", limit=3, window=60) == 0 for _ in range(3))
    retry = check("u", limit=3, window=60)
    assert retry > 0, retry
    assert check("other", limit=3, window=60) == 0, "유저별로 따로 세야 한다"
    # 창이 지나면 풀린다
    reset()
    assert check("u", limit=1, window=0.05) == 0
    assert check("u", limit=1, window=0.05) > 0
    time.sleep(0.06)
    assert check("u", limit=1, window=0.05) == 0
    reset()
    print("ratelimit 자체검사 통과")
