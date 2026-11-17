from datetime import date
from pathlib import Path

from labor_law_rag.collect.law import notice_pdf_link, select_notice
from labor_law_rag.models import Document, EvidenceUnit
from labor_law_rag.normalize.law_xml import parse_law
from labor_law_rag.normalize.scope import delegated_articles, filter_articles, parse_notice

FIX = Path(__file__).parent.parent / "fixtures" / "law"


def read_fixture(name: str) -> bytes:
    return (FIX / name).read_bytes()


def test_parse_law_records_article_spans():
    doc, _ = parse_law(read_fixture("synthetic.xml"), source_type="law", url="u")
    keys = [a[0] for a in doc.meta["articles"]]
    assert keys == ["제2조", "제3조", "제5조의2", "제7조"]
    start, end = next((s, e) for k, s, e in doc.meta["articles"] if k == "제5조의2")
    assert doc.text[start:end] == "제5조의2(괴롭힘의 금지) 누구든지 직장에서 괴롭힘을 하여서는 아니 된다."


def test_filter_articles_rebuilds_offsets():
    doc, units = parse_law(read_fixture("synthetic.xml"), source_type="law", url="u")
    d2, u2 = filter_articles(doc, units, ["제2조", "제5조의2"])
    assert {u.unit_id for u in u2} == {"테스트법 제2조 제1항", "테스트법 제2조 제2항", "테스트법 제5조의2"}
    for u in u2:
        orig = next(o for o in units if o.unit_id == u.unit_id)
        assert d2.text[u.start:u.end] == doc.text[orig.start:orig.end]
    assert "제3조" not in d2.text and "제1장" not in d2.text
    assert d2.doc_id == doc.doc_id and [a[0] for a in d2.meta["articles"]] == ["제2조", "제5조의2"]


def test_filter_articles_unknown_article_raises():
    import pytest

    doc, units = parse_law(read_fixture("synthetic.xml"), source_type="law", url="u")
    with pytest.raises(ValueError, match="제99조"):
        filter_articles(doc, units, ["제2조", "제99조"])


def test_delegated_articles_matches_parent_reference():
    d = Document(doc_id="decree:x", source_type="decree", title="t", url="", license="", date=None,
                 text="제95조(육아휴직 급여) 법 제70조제1항에 따른 ...\n제99조(다른 것) 법 제40조에 따라 ...")
    units = [EvidenceUnit(unit_id="x 제95조", doc_id="decree:x", start=0, end=30),
             EvidenceUnit(unit_id="x 제99조", doc_id="decree:x", start=31, end=len(d.text))]
    assert delegated_articles(d, units, ["제70조", "제75조"]) == ["제95조"]


def test_delegated_articles_branch_article():
    d = Document(doc_id="decree:x", source_type="decree", title="t", url="", license="", date=None,
                 text="제104조의2(급여) 법 제73조의2제1항에 따라\n제105조(기타) 법 제73조에 따라")
    units = [EvidenceUnit(unit_id="x 제104조의2", doc_id="decree:x", start=0, end=30),
             EvidenceUnit(unit_id="x 제105조", doc_id="decree:x", start=31, end=len(d.text))]
    assert delegated_articles(d, units, ["제73조의2"]) == ["제104조의2"]


def test_select_notice_picks_effective_moel_wage_notice():
    n = select_notice(read_fixture("admrul_search_최저임금.xml"), date(2026, 11, 17))
    assert n.name == "2026년 적용 최저임금 고시" and n.rule_id == "2100000262710"
    assert n.effective_date == date(2026, 1, 1)


def test_notice_pdf_link_skips_reason_document():
    assert notice_pdf_link(read_fixture("admrul_최저임금고시_2026.xml")).endswith("flSeq=155278071")


def test_notice_is_single_unit():
    doc, units = parse_notice(read_fixture("최저임금고시_2026.pdf"), title="2026년 적용 최저임금 고시",
                              effective_date=date(2026, 1, 1), url="u")
    assert [u.unit_id for u in units] == ["최저임금 고시"]
    assert (units[0].start, units[0].end) == (0, len(doc.text))
    assert doc.doc_id == "notice:최저임금 고시" and doc.source_type == "notice"
    assert "10,320원" in doc.text and "2,156,880원" in doc.text
