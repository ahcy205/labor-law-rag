"""글자 범위 검증과 근거 판정 (설계 4.2).

판정식: 같은 문서이고, 겹친 길이 / min(단위 길이, 청크 길이) >= 0.5 이면 찾은 것으로 본다.
"""

from __future__ import annotations

from labor_law_rag.models import Document, EvidenceUnit, RetrievedChunk


def check_unit(doc: Document, unit: EvidenceUnit, expected_text: str) -> None:
    actual = doc.text[unit.start : unit.end]
    if actual != expected_text:
        raise ValueError(
            f"{unit.unit_id}: 범위 [{unit.start}, {unit.end})의 원문이 기대와 다릅니다: "
            f"{actual[:30]!r} != {expected_text[:30]!r}"
        )


def coverage(chunk_start: int, chunk_end: int, unit_start: int, unit_end: int) -> float:
    overlap = max(0, min(chunk_end, unit_end) - max(chunk_start, unit_start))
    shorter = min(chunk_end - chunk_start, unit_end - unit_start)
    if shorter <= 0:
        return 0.0
    return overlap / shorter


def covers(chunk: RetrievedChunk, unit: EvidenceUnit, threshold: float = 0.5) -> bool:
    if chunk.doc_id != unit.doc_id:
        return False
    return coverage(chunk.start, chunk.end, unit.start, unit.end) >= threshold
