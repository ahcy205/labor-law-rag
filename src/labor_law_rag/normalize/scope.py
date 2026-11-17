"""수집 범위 적용 (설계 3.2): 고용보험법 일부 조문, 위임 시행령 조문, 최저임금 고시."""

from __future__ import annotations

import io
import re
from collections import defaultdict
from datetime import date

from pypdf import PdfReader

from labor_law_rag.models import Document, EvidenceUnit
from labor_law_rag.spans import check_unit

_ART_KEY = re.compile(r"(제\d+조(?:의\d+)?)")
_PARENT_REF = re.compile(r"법\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")


def filter_articles(
    doc: Document, units: list[EvidenceUnit], articles: list[str]
) -> tuple[Document, list[EvidenceUnit]]:
    """지정한 조만 남긴 새 Document와 근거 단위. 텍스트를 다시 이어 붙이고 범위도 다시 계산한다."""
    spans = {k: (s, e) for k, s, e in doc.meta["articles"]}
    missing = [a for a in articles if a not in spans]
    if missing:
        raise ValueError(f"{doc.title}: 본문에 없는 조문: {missing}")
    keep = [k for k, _, _ in doc.meta["articles"] if k in set(articles)]  # 원문 순서 유지
    parts: list[str] = []
    shift: dict[str, int] = {}
    new_articles = []
    pos = 0
    for k in keep:
        s, e = spans[k]
        shift[k] = pos - s
        parts.append(doc.text[s:e])
        new_articles.append([k, pos, pos + (e - s)])
        pos += (e - s) + 1
    text = "\n".join(parts)
    new_doc = doc.model_copy(update={"text": text, "meta": {**doc.meta, "articles": new_articles}})
    new_units = []
    for u in units:
        k = _unit_article(u, doc)
        if k in shift:
            nu = u.model_copy(update={"start": u.start + shift[k], "end": u.end + shift[k]})
            check_unit(new_doc, nu, doc.text[u.start:u.end])
            new_units.append(nu)
    return new_doc, new_units


def _unit_article(unit: EvidenceUnit, doc: Document) -> str:
    """unit_id에서 조 키를 꺼낸다. 법령명에 숫자가 섞여도 되도록 법령명 뒤 부분만 본다."""
    rest = unit.unit_id[len(doc.title):] if unit.unit_id.startswith(doc.title) else unit.unit_id
    return _ART_KEY.search(rest).group(1)


def delegated_articles(decree_doc: Document, decree_units: list[EvidenceUnit], parent_articles: list[str]) -> list[str]:
    """시행령 조문 중 상위 법의 대상 조문("법 제70조", "법 제73조의2제1항")을 인용하는 조 키 목록."""
    targets = set(parent_articles)
    texts: dict[str, list[str]] = defaultdict(list)
    order: list[str] = []
    for u in sorted(decree_units, key=lambda u: u.start):
        k = _unit_article(u, decree_doc)
        if k not in texts:
            order.append(k)
        texts[k].append(decree_doc.text[u.start:u.end])
    result = []
    for k in order:
        refs = {f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
                for m in _PARENT_REF.finditer("\n".join(texts[k]))}
        if refs & targets:
            result.append(k)
    return result


def parse_notice(
    pdf: bytes, *, title: str, effective_date: date, url: str
) -> tuple[Document, list[EvidenceUnit]]:
    """최저임금 고시 PDF → Document 1개, 근거 단위 1개("최저임금 고시")."""
    reader = PdfReader(io.BytesIO(pdf))
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    lines = [" ".join(line.split()) for line in raw.splitlines()]
    text = "\n".join(line for line in lines if line)
    doc = Document(doc_id="notice:최저임금 고시", source_type="notice", title=title, text=text,
                   date=effective_date, url=url, license="법령(저작권 보호 대상 아님)")
    return doc, [EvidenceUnit(unit_id="최저임금 고시", doc_id=doc.doc_id, start=0, end=len(text))]
