"""익명 세션 격리 검증. 원칙 4(RLS)와 원칙 5(비공개 버킷)가 실제로 막히는지 확인한다.

익명 유저 두 명을 만들어서 A의 데이터를 B가 읽지 못하는지 실제로 때려본다.
"막았다고 생각했는데 안 막혀 있었다"가 이 구조에서 가장 비싼 사고라, 눈으로 확인하고 넘어간다.

    python verify_rls.py

필요 환경변수: SUPABASE_URL, SUPABASE_ANON_KEY   (service_role 키가 아니다 — 그건 RLS를 우회한다)
사전 조건: Dashboard > Authentication > Sign In / Providers > Anonymous sign-ins 활성화
"""

import os
import sys

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
ANON = os.environ.get("SUPABASE_ANON_KEY", "")

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")


def sign_in_anonymously(client: httpx.Client) -> tuple[str, str]:
    """익명 세션 생성 → (access_token, user_id)"""
    r = client.post(f"{URL}/auth/v1/signup", headers={"apikey": ANON}, json={})
    if r.is_error:
        raise RuntimeError(
            f"익명 로그인 실패 HTTP {r.status_code}: {r.text[:200]}\n"
            "  → Dashboard > Authentication > Sign In / Providers 에서 Anonymous sign-ins를 켰는지 확인"
        )
    d = r.json()
    return d["access_token"], d["user"]["id"]


def hdr(token: str, extra: dict | None = None) -> dict:
    return {"apikey": ANON, "Authorization": f"Bearer {token}", **(extra or {})}


def main() -> None:
    if not URL or not ANON:
        sys.exit("SUPABASE_URL / SUPABASE_ANON_KEY 환경변수가 없다. .env.example 참고")

    with httpx.Client(timeout=30) as c:
        print("익명 세션 2개 생성")
        a_token, a_uid = sign_in_anonymously(c)
        b_token, b_uid = sign_in_anonymously(c)
        check(a_uid != b_uid, f"서로 다른 익명 유저로 분리됨 (A={a_uid[:8]} B={b_uid[:8]})")

        print("\n[1] products — 유저 격리")
        r = c.post(f"{URL}/rest/v1/products",
                   headers=hdr(a_token, {"Content-Type": "application/json",
                                         "Prefer": "return=representation"}),
                   json={"user_id": a_uid, "name": "격리검증용 세럼"})
        check(not r.is_error, f"A가 자기 제품 등록 (HTTP {r.status_code})")
        if r.is_error:
            print(f"        {r.text[:200]}")
            return
        pid = r.json()[0]["id"]

        r = c.get(f"{URL}/rest/v1/products?id=eq.{pid}", headers=hdr(a_token))
        check(len(r.json()) == 1, "A가 자기 제품 조회됨")

        r = c.get(f"{URL}/rest/v1/products?id=eq.{pid}", headers=hdr(b_token))
        check(r.json() == [], "★ B는 A의 제품이 조회되지 않음")

        r = c.get(f"{URL}/rest/v1/products", headers=hdr(b_token))
        check(r.json() == [], "★ B가 전체 조회해도 빈 결과")

        r = c.patch(f"{URL}/rest/v1/products?id=eq.{pid}",
                    headers=hdr(b_token, {"Content-Type": "application/json",
                                          "Prefer": "return=representation"}),
                    json={"name": "탈취됨"})
        check(r.is_error or r.json() == [], "★ B가 A의 제품을 수정하지 못함")

        r = c.delete(f"{URL}/rest/v1/products?id=eq.{pid}",
                     headers=hdr(b_token, {"Prefer": "return=representation"}))
        check(r.is_error or r.json() == [], "★ B가 A의 제품을 삭제하지 못함")

        # user_id를 위조해서 남의 것으로 심는 것도 막혀야 한다 (with check 절)
        r = c.post(f"{URL}/rest/v1/products",
                   headers=hdr(b_token, {"Content-Type": "application/json"}),
                   json={"user_id": a_uid, "name": "위조 삽입"})
        check(r.is_error, f"★ B가 user_id를 A로 위조해 삽입하지 못함 (HTTP {r.status_code})")

        print("\n[2] daily_records — 유저 격리")
        r = c.post(f"{URL}/rest/v1/daily_records",
                   headers=hdr(a_token, {"Content-Type": "application/json",
                                         "Prefer": "return=representation"}),
                   json={"user_id": a_uid, "skin_context": {"dry": True}})
        check(not r.is_error, f"A가 기록 생성 (HTTP {r.status_code})")
        rec_id = r.json()[0]["id"] if not r.is_error else None

        if rec_id:
            r = c.get(f"{URL}/rest/v1/daily_records?id=eq.{rec_id}", headers=hdr(b_token))
            check(r.json() == [], "★ B는 A의 셀카 기록이 조회되지 않음")

        print("\n[3] ingredients — 참조 테이블은 전원 읽기 가능")
        r = c.get(f"{URL}/rest/v1/ingredients?std_name=eq.레티놀", headers=hdr(b_token))
        check(not r.is_error and len(r.json()) == 1, "B도 성분 사전 조회 가능 (표준명 완전일치)")

        r = c.post(f"{URL}/rest/v1/ingredients",
                   headers=hdr(b_token, {"Content-Type": "application/json"}),
                   json={"std_name": "가짜성분"})
        check(r.is_error, f"★ B가 성분 사전에 쓰지 못함 (HTTP {r.status_code})")

        print("\n[4] Storage — 얼굴 사진 비공개 (원칙 5)")
        obj = f"{a_uid}/verify.txt"
        r = c.post(f"{URL}/storage/v1/object/selfies/{obj}",
                   headers=hdr(a_token, {"Content-Type": "text/plain"}), content=b"test")
        check(not r.is_error, f"A가 자기 폴더에 업로드 (HTTP {r.status_code})")

        r = c.get(f"{URL}/storage/v1/object/selfies/{obj}", headers=hdr(b_token))
        check(r.is_error, f"★ B가 A의 셀카를 못 받음 (HTTP {r.status_code})")

        r = httpx.get(f"{URL}/storage/v1/object/public/selfies/{obj}", timeout=30)
        check(r.is_error, f"★ 인증 없는 공개 URL로도 못 받음 (HTTP {r.status_code})")

        r = c.post(f"{URL}/storage/v1/object/selfies/{b_uid}-sneak/x.txt",
                   headers=hdr(b_token, {"Content-Type": "text/plain"}), content=b"x")
        check(r.is_error, f"★ B가 남의 폴더명으로 업로드 못함 (HTTP {r.status_code})")

        print("\n정리 중")
        c.delete(f"{URL}/storage/v1/object/selfies/{obj}", headers=hdr(a_token))
        c.delete(f"{URL}/rest/v1/products?id=eq.{pid}", headers=hdr(a_token))
        if rec_id:
            c.delete(f"{URL}/rest/v1/daily_records?id=eq.{rec_id}", headers=hdr(a_token))

    failed = [label for ok, label in results if not ok]
    print(f"\n{'=' * 50}\n{len(results) - len(failed)}/{len(results)} 통과")
    if failed:
        print("\n실패:")
        for label in failed:
            print(f"  - {label}")
        sys.exit(1)
    print("격리 검증 통과. RLS·Storage 정책이 실제로 막고 있다.")


if __name__ == "__main__":
    main()
