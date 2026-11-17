"""질의 · 회답형 문서와 별표처럼 문서 1건이 근거 단위 1개인 경우."""

from __future__ import annotations

from labor_law_rag.models import Document, EvidenceUnit


def whole_doc_unit(doc: Document) -> EvidenceUnit:
    """문서 전체를 근거 단위 하나로. 별표는 unit_id에서 'annex:'를 뗀다(예: '근로기준법 시행령 별표 1')."""
    unit_id = doc.doc_id.removeprefix("annex:") if doc.source_type == "annex" else doc.doc_id
    return EvidenceUnit(unit_id=unit_id, doc_id=doc.doc_id, start=0, end=len(doc.text))
