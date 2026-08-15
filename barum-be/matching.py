"""전성분 문자열 → 식약처 표준명 매칭.

카탈로그 일괄 정규화(scripts/match_catalog_ingredients.py)와 OCR 결과 매칭이 같은 규칙을
써야 한다. 한쪽만 고치면 같은 성분이 화면에 따라 다르게 잡힌다.
"""

import re

# 구분자. 숫자 사이 쉼표는 성분명의 일부다 — 1,2-헥산다이올은 국내 화장품에 대단히 흔하고
# 쪼개면 "1"과 "2-헥산다이올" 둘 다 쓰레기가 된다. ■ 는 수집본에서 제품을 잇는 데 쓰인다.
_SEP = re.compile(r"[\n·•;■|]|,(?![0-9])|(?<![0-9]),")

# 유기농·원산지 표시로 붙는 별표(오렌지껍질오일**), 대괄호 잔재
_MARK = re.compile(r"[*※\[\]]+")
# 함량·규격 표기. "나이아신아마이드 2%", "레티놀 1,000IU/g"
_AMOUNT = re.compile(r"\s*\d+(,\d{3})*(\.\d+)?\s*(%|IU/?g?|ppm|mg|㎎)\s*$", re.I)
_PAREN = re.compile(r"\s*[\(（][^)）]*[\)）]")


def split_ingredients(raw: str) -> list[str]:
    """전성분 원문 → 성분명 목록. 괄호는 여기서 떼지 않는다 — match()가 판단한다."""
    out = []
    for token in _SEP.split(raw or ""):
        name = _MARK.sub("", token or "").strip().strip(".·-")
        name = re.sub(r"\s+", " ", name)
        # 숫자 조각이나 한 글자는 성분명이 아니다. 이런 게 이명 인덱스에 우연히 걸리면
        # 없는 성분이 제품에 등록되고 충돌 판정까지 오염된다(원칙 1).
        if len(name) >= 2 and not name.isdigit():
            out.append(name)
    return out


def candidates(name: str) -> list[str]:
    """매칭 후보를 좁은 것부터.

    괄호를 무조건 떼면 안 된다. `살리실릭애씨드(0.5%)`는 떼야 맞고,
    `하이드로제네이티드폴리(C6-14올레핀)`은 괄호까지가 표준명이다. 둘 다 시도한다.
    """
    seen, out = set(), []
    for c in (name,
              _AMOUNT.sub("", name),
              _PAREN.sub("", name).strip(),
              _PAREN.sub("", _AMOUNT.sub("", name)).strip()):
        c = c.strip(" ,.")
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out + [c.replace(" ", "") for c in out]


def build_index(rows: list[dict]) -> tuple[dict, dict]:
    """(표준명 → id, 이명 → id). 이명은 같은 규칙으로 분해해 완전일치로만 쓴다.

    단순 split(",")을 쓰면 "1,10-데칸디올"이 "1"과 "10-데칸디올"로 쪼개져 by_syn["1"]이
    생기고, 전성분에서 떨어져 나온 숫자 조각이 여기 걸려 엉뚱한 성분으로 매칭된다.
    부분일치(ilike)도 쓰지 않는다 — "가지추출물"이 "잔가지추출물"에 걸린다.
    """
    by_std = {r["std_name"]: r["id"] for r in rows}
    by_syn = {}
    for r in rows:
        for syn in split_ingredients(r.get("synonym") or ""):
            if syn not in by_std:  # 표준명이 우선한다
                by_syn.setdefault(syn, r["id"])
    return by_std, by_syn


def match(name: str, by_std: dict, by_syn: dict) -> int | None:
    """후보 형태를 순서대로 표준명 → 이명 완전일치로 대조한다."""
    for c in candidates(name):
        if c in by_std:
            return by_std[c]
        if c in by_syn:
            return by_syn[c]
    return None


def match_name(name: str, by_std: dict, by_syn: dict, id_to_std: dict) -> str | None:
    """매칭된 표준명 자체를 돌려준다. OCR 응답은 id가 아니라 표준명을 쓴다."""
    iid = match(name, by_std, by_syn)
    return id_to_std.get(iid) if iid else None


def _selfcheck() -> None:
    assert split_ingredients("글리세린, 1,2-헥산다이올, 판테놀") == ["글리세린", "1,2-헥산다이올", "판테놀"]
    assert split_ingredients("오렌지껍질오일**, 아시아티코사이드*") == ["오렌지껍질오일", "아시아티코사이드"]
    assert split_ingredients("리모넨 ■ 우르오스 정제수")[0] == "리모넨"
    assert "하이드로제네이티드폴리(C6-14올레핀)" in candidates("하이드로제네이티드폴리(C6-14올레핀)")
    assert "살리실릭애씨드" in candidates("살리실릭애씨드(0.5%)")
    assert "레티놀" in candidates("레티놀 1,000IU/g")

    rows = [{"id": 1, "std_name": "하이알루로닉애씨드", "synonym": "히알루론산"},
            {"id": 4, "std_name": "1,10-데칸다이올", "synonym": "1,10-데칸디올"}]
    by_std, by_syn = build_index(rows)
    assert match("히알루론산", by_std, by_syn) == 1
    assert "1" not in by_syn and match("1", by_std, by_syn) is None
    print("matching selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
