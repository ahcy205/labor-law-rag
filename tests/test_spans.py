import pytest

from labor_law_rag.models import Document, EvidenceUnit, RetrievedChunk
from labor_law_rag.spans import check_unit, coverage, covers


def _chunk(doc, s, e):
    return RetrievedChunk(doc_id=doc, start=s, end=e, score=1.0)


def _unit(doc, s, e):
    return EvidenceUnit(unit_id="u", doc_id=doc, start=s, end=e)


def test_coverage_half_counts():
    assert coverage(0, 50, 0, 100) == 1.0  # 청크 전체가 단위 안
    assert coverage(50, 250, 0, 100) == 0.5  # 단위의 절반을 덮음 (min = 단위 100)
    assert covers(_chunk("d", 50, 250), _unit("d", 0, 100))


def test_sliver_overlap_does_not_count():
    assert not covers(_chunk("d", 95, 300), _unit("d", 0, 100))


def test_chunk_inside_long_unit_counts():
    assert covers(_chunk("d", 100, 600), _unit("d", 0, 2000))


def test_no_overlap_is_zero():
    assert coverage(200, 300, 0, 100) == 0.0


def test_other_doc_never_counts():
    assert not covers(_chunk("e", 0, 100), _unit("d", 0, 100))


def test_check_unit_detects_offset_drift():
    d = Document(doc_id="d", source_type="law", title="t", text="가나다라마", date=None, url="", license="")
    check_unit(d, EvidenceUnit(unit_id="u", doc_id="d", start=1, end=3), "나다")
    with pytest.raises(ValueError):
        check_unit(d, EvidenceUnit(unit_id="u", doc_id="d", start=1, end=3), "다라")
