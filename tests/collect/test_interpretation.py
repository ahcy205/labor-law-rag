from datetime import date
from pathlib import Path

from labor_law_rag.collect.interpretation import (
    InterpRef,
    match_topics,
    parse_interp_list,
    parse_interpretation,
)
from labor_law_rag.normalize.qa import whole_doc_unit

FIX = Path(__file__).parent.parent / "fixtures" / "interp"


def read_fixture(name: str) -> bytes:
    return (FIX / name).read_bytes()


def test_parse_list_page():
    refs, total = parse_interp_list(read_fixture("list_p1.xml"))
    assert total > 9000 and len(refs) == 100
    assert all(isinstance(r, InterpRef) and r.serial and r.title for r in refs)


def test_parse_interpretation_body():
    d = parse_interpretation(read_fixture("body_15234.xml"), url="u")
    assert d.doc_id == "interp:15234" and d.source_type == "interpretation"
    assert d.title == "1년간 8할미만 출근자 연차유급휴가 사용촉진의 대상 여부"
    assert d.date == date(2015, 7, 13)
    assert d.text.startswith("질의\n「근로기준법」 제60조제2항에 따라") and "\n\n회답\n" in d.text
    assert "이유" not in d.text.split("\n")  # 비어 있는 이유는 생략
    assert d.meta["case_no"] == "근로기준정책과-3084"
    assert d.license == "공공누리 제1유형"


def test_whole_doc_unit_spans_text():
    d = parse_interpretation(read_fixture("body_15234.xml"), url="u")
    u = whole_doc_unit(d)
    assert (u.unit_id, u.start, u.end) == (d.doc_id, 0, len(d.text))


def test_match_topics_on_title():
    topics = {"연차휴가": ["연차"], "퇴직금": ["퇴직금"]}
    assert match_topics("연차유급휴가 사용촉진", topics) and not match_topics("산재보험 적용", topics)


def test_list_dedupes_serials():
    refs, _ = parse_interp_list(read_fixture("list_p1.xml") )
    assert len({r.serial for r in refs}) == len(refs)
