from datetime import date
from pathlib import Path

from labor_law_rag.normalize.law_xml import parse_law

FIX = Path(__file__).parent.parent / "fixtures" / "law"


def read_fixture(name: str) -> bytes:
    return (FIX / name).read_bytes()


def _parse(name, source_type="law"):
    return parse_law(read_fixture(name), source_type=source_type, url="u")


def test_real_fixture_article_60():
    doc, units = _parse("근로기준법.xml")
    by_id = {u.unit_id: u for u in units}
    u = by_id["근로기준법 제60조 제2항"]
    assert doc.doc_id == "law:근로기준법" and doc.title == "근로기준법"
    assert doc.date == date(2026, 10, 8)
    assert doc.text[u.start:u.end].startswith("② 사용자는 계속하여 근로한 기간이 1년 미만인 근로자")
    assert "근로기준법 제76조의2" in by_id  # 가지조 · 항 없음 → 조 단위
    assert "근로기준법 제60조 제3항" not in by_id  # 삭제된 항
    assert "근로기준법 제35조" not in by_id  # 삭제된 조


def test_real_fixture_article_with_items_but_no_paragraph_number():
    doc, units = _parse("근로기준법.xml")
    u = next(u for u in units if u.unit_id == "근로기준법 제26조")
    t = doc.text[u.start:u.end]
    assert t.startswith("사용자는 근로자를 해고") and "1. 근로자가 계속 근로한 기간이 3개월 미만인 경우" in t


def test_every_unit_slice_is_exact():
    doc, units = _parse("근로기준법.xml")
    assert len(units) > 200
    assert len({u.unit_id for u in units}) == len(units)
    for u in units:
        s = doc.text[u.start:u.end]
        assert s == s.strip() and s


def test_synthetic_edge_cases():
    doc, units = _parse("synthetic.xml")
    ids = [u.unit_id for u in units]
    assert ids == ["테스트법 제2조 제1항", "테스트법 제2조 제2항", "테스트법 제3조", "테스트법 제5조의2", "테스트법 제7조"]
    text = {u.unit_id: doc.text[u.start:u.end] for u in units}
    assert text["테스트법 제2조 제2항"] == "② 다음 각 호는 임금으로 본다. <개정 2020.1.1>\n1. 기본급\n2. 수당\n가. 연장근로수당"
    assert text["테스트법 제3조"].startswith("사용자는 30일 전에") and text["테스트법 제3조"].endswith("천재ㆍ사변의 경우")
    assert text["테스트법 제5조의2"] == "누구든지 직장에서 괴롭힘을 하여서는 아니 된다."
    assert text["테스트법 제7조"] == "1. 호만 있는 조"
    assert "제1장 총칙" in doc.text  # 장 제목은 텍스트에는 남는다
    assert "삭제" not in doc.text  # 삭제 조 · 항은 텍스트에서도 뺀다


def test_decree_doc_id():
    doc, _ = parse_law(read_fixture("synthetic.xml"), source_type="decree", url="u")
    assert doc.doc_id == "decree:테스트법" and doc.source_type == "decree"
