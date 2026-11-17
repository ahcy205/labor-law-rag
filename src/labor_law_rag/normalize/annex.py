"""법령 본문 XML 안의 별표 → Document (별표 1건 = 근거 단위 1개, 설계 4.2)."""

from __future__ import annotations

import re
from datetime import date

from lxml import etree
from pydantic import BaseModel

from labor_law_rag.models import Document

_BOX_ONLY = re.compile(r"^[\s┏┓┗┛┠┨┯┷┼━─┃│┣┫┳┻╋┌┐└┘├┤┬┴]*$")
_RELATED = re.compile(r"(제\d+조(?:의\d+)?)[^)]*?관련")


class AnnexResult(BaseModel):
    docs: list[Document]
    missing: list[dict]


def clean_table_text(raw: str) -> str:
    """상자 문자로 그린 표를 '칸 | 칸' 줄로 바꾼다. 칸 안에서 줄이 넘어간 글자는 앞 행에 이어 붙인다."""
    out: list[str] = []
    rows: list[list[str]] = []  # 현재 표의 행들

    def flush():
        out.extend(" | ".join(c for c in row if c) for row in rows)
        rows.clear()

    for line in raw.splitlines():
        if _BOX_ONLY.match(line):  # 빈 줄과 표 테두리 줄
            continue
        stripped = line.strip()
        if stripped.startswith("┃"):
            cells = [c.strip() for c in stripped.strip("┃┨┫").split("│")]
            if rows and not cells[0]:  # 첫 칸이 비면 앞 행의 이어지는 줄
                prev = rows[-1]
                for i, c in enumerate(cells):
                    if i < len(prev):
                        prev[i] = prev[i] + c
                    elif c:
                        prev.append(c)
            else:
                rows.append(cells)
            continue
        flush()
        out.append(" ".join(stripped.split()))
    flush()
    return "\n".join(line for line in out if line)


def annex_related_articles(title: str) -> list[str]:
    """'(제50조제1항 관련)' → ['제50조']."""
    return _RELATED.findall(title)


def _annex_no(no: str, branch: str) -> str:
    n = int(no or 0)
    b = int(branch or 0)
    if n == 0:
        return ""
    return f"{n}의{b}" if b else str(n)


def parse_annexes(law_xml: bytes, *, law_name: str, effective_date: date, url: str) -> AnnexResult:
    root = etree.fromstring(law_xml)
    docs, missing = [], []
    for b in root.findall("별표/별표단위"):
        if (b.findtext("별표구분") or "").strip() != "별표":
            continue  # 서식은 근거 문서가 아니다
        no = _annex_no(b.findtext("별표번호"), b.findtext("별표가지번호"))
        title = " ".join((b.findtext("별표제목") or "").split())
        label = f"{law_name} 별표" + (f" {no}" if no else "")
        text = clean_table_text(b.findtext("별표내용") or "")
        if not text:
            missing.append({"law": law_name, "annex_no": no, "title": title,
                            "file_url": (b.findtext("별표서식PDF파일링크") or "").strip()})
            continue
        docs.append(Document(
            doc_id=f"annex:{label}", source_type="annex", title=f"{label} {title}", text=text,
            date=effective_date, url=url, license="법령(저작권 보호 대상 아님)",
            meta={"related_articles": annex_related_articles(title)},
        ))
    return AnnexResult(docs=docs, missing=missing)
