"""본문의 법령 인용("근로기준법 제60조제2항", "같은 법 제60조")을 근거 단위 ID로 바꾼다."""

from __future__ import annotations

import re

from labor_law_rag.corpus import UnitIndex

_SAME_LAW = ("같은 법", "동법", "같은법")


def _name_pattern(name: str) -> str:
    return r"\s*".join(re.escape(part) for part in name.split())


def _build_regex(law_names: list[str]) -> re.Pattern:
    names = sorted(law_names, key=len, reverse=True)  # "근로기준법 시행령"을 "근로기준법"보다 먼저
    alts = "|".join(_name_pattern(n) for n in names)
    same = "|".join(_name_pattern(s) for s in _SAME_LAW)
    return re.compile(
        rf"(?P<law>{alts})|(?P<same>{same})(?P<decree>\s*시행령)?"
        rf"|(?P<article>제\s*(?P<no>\d+)\s*조(?:\s*의\s*(?P<branch>\d+))?(?:\s*제\s*(?P<para>\d+)\s*항)?)"
    )


def _normalize(matched: str, law_names: list[str]) -> str:
    compact = re.sub(r"\s+", "", matched)
    for n in law_names:
        if re.sub(r"\s+", "", n) == compact:
            return n
    return matched


def _resolve(law: str, no: str, branch: str | None, para: str | None, index: UnitIndex) -> list[str]:
    base = f"{law} 제{no}조" + (f"의{branch}" if branch else "")
    if para:
        pid = f"{base} 제{para}항"
        if pid in index:
            return [pid]
    if base in index:
        return [base]
    prefix = base + " 제"
    return [u.unit_id for u in sorted(index.all_units(), key=lambda u: u.start) if u.unit_id.startswith(prefix)]


def extract_citations(text: str, law_names: list[str], index: UnitIndex) -> list[str]:
    """처음 나온 순서로, 중복 없이, index에 있는 unit_id만 돌려준다.

    법령명(또는 "같은 법")이 바로 앞에 붙은 조문만 인용으로 본다.
    """
    pattern = _build_regex(law_names)
    result: list[str] = []
    last_law: str | None = None
    pending_law: str | None = None
    prev_end = 0
    for m in pattern.finditer(text):
        if m.group("law"):
            last_law = pending_law = _normalize(m.group("law"), law_names)
        elif m.group("same"):
            if last_law is None:
                pending_law = None
                continue
            base_law = last_law.removesuffix(" 시행령")
            pending_law = f"{base_law} 시행령" if m.group("decree") else last_law
        elif m.group("article"):
            if pending_law is None:
                continue
            # 법령명과 조문 사이에 다른 글자가 끼면(예: "근로기준법에 따라 ... 제5조") 인용으로 보지 않는다.
            between = text[prev_end:m.start()]
            if between.strip():
                pending_law = None
                continue
            for uid in _resolve(pending_law, m.group("no"), m.group("branch"), m.group("para"), index):
                if uid not in result:
                    result.append(uid)
            pending_law = None
        prev_end = m.end()
    return result
