"""법령 본문 XML → Document 1개 + 조 · 항 단위 EvidenceUnit (설계 4.2).

텍스트 규칙:
- 조마다 조문내용 한 줄, 이어서 항내용 한 줄씩, 그 아래 호 · 목 내용을 한 줄씩.
- 항 번호가 있는 조는 항 단위로, 항 번호가 없으면 조 단위(조문 머리 "제N조(제목)" 뒤 본문부터 조 끝까지)로 근거를 만든다.
- 장 · 절 제목 줄(조문여부=전문)은 텍스트에만 넣는다.
- 삭제된 조 · 항은 텍스트와 근거 단위 모두에서 뺀다.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from lxml import etree

from labor_law_rag.models import Document, EvidenceUnit, SourceType
from labor_law_rag.spans import check_unit

_HEADER = re.compile(r"^제\s*\d+\s*조(?:\s*의\s*\d+)?(?:\s*\([^)]*\))?\s*")
_DELETED_ARTICLE = re.compile(r"^제\s*\d+\s*조(?:\s*의\s*\d+)?\s*삭제")
_DELETED_PARA = re.compile(r"^\S\s*삭제\s*(<|$)")


def _clean(s: str | None) -> str:
    return (s or "").strip()


def _para_number(symbol: str) -> int:
    symbol = symbol.strip()
    if symbol.isdecimal():  # "①".isdigit()는 True지만 int()로 바꿀 수 없다
        return int(symbol)
    return int(unicodedata.numeric(symbol[0]))


class _Builder:
    def __init__(self):
        self.lines: list[str] = []
        self.pos = 0

    def add(self, line: str) -> tuple[int, int]:
        start = self.pos
        self.lines.append(line)
        self.pos += len(line) + 1  # "\n"
        return start, start + len(line)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _item_lines(parent) -> list[str]:
    """항(또는 조) 아래의 호 · 목 줄."""
    out = []
    for ho in parent.findall("호"):
        if _clean(ho.findtext("호내용")):
            out.append(_clean(ho.findtext("호내용")))
        for mok in ho.findall("목"):
            for line in _clean(mok.findtext("목내용")).splitlines():
                if line.strip():
                    out.append(line.strip())
    return out


def parse_law(xml: bytes, *, source_type: SourceType, url: str) -> tuple[Document, list[EvidenceUnit]]:
    root = etree.fromstring(xml)
    info = root.find("기본정보")
    name = _clean(info.findtext("법령명_한글"))
    eff = _clean(info.findtext("시행일자"))
    doc_id = f"{source_type}:{name}"
    b = _Builder()
    spans: list[tuple[str, int, int]] = []

    for art in root.findall("조문/조문단위"):
        content = _clean(art.findtext("조문내용"))
        if art.findtext("조문여부") == "전문":
            if content:
                b.add(content)
            continue
        if _DELETED_ARTICLE.match(content):
            continue
        no = _clean(art.findtext("조문번호"))
        branch = _clean(art.findtext("조문가지번호"))
        art_id = f"{name} 제{no}조" + (f"의{branch}" if branch and branch != "0" else "")

        head_start, head_end = b.add(content)
        header = _HEADER.match(content)
        body_offset = header.end() if header else 0
        numbered = [p for p in art.findall("항") if _clean(p.findtext("항번호"))]

        if numbered:
            for p in art.findall("항"):
                p_text = _clean(p.findtext("항내용"))
                if p_text and _DELETED_PARA.match(p_text):
                    continue
                start = None
                end = None
                if p_text:
                    start, end = b.add(p_text)
                for line in _item_lines(p):
                    s, end = b.add(line)
                    start = s if start is None else start
                if start is not None and _clean(p.findtext("항번호")):
                    spans.append((f"{art_id} 제{_para_number(p.findtext('항번호'))}항", start, end))
        else:
            start = head_start + body_offset if head_start + body_offset < head_end else None
            end = head_end if start is not None else None
            for p in art.findall("항"):
                if _clean(p.findtext("항내용")):
                    s, end = b.add(_clean(p.findtext("항내용")))
                    start = s if start is None else start
                for line in _item_lines(p):
                    s, end = b.add(line)
                    start = s if start is None else start
            if start is not None:
                spans.append((art_id, start, end))

    text = b.text
    doc = Document(
        doc_id=doc_id, source_type=source_type, title=name, text=text,
        date=datetime.strptime(eff, "%Y%m%d").date() if eff else None, url=url, license="법령(저작권 보호 대상 아님)",
    )
    units = []
    for unit_id, start, end in spans:
        unit = EvidenceUnit(unit_id=unit_id, doc_id=doc_id, start=start, end=end)
        check_unit(doc, unit, text[start:end].strip())
        units.append(unit)
    return doc, units
