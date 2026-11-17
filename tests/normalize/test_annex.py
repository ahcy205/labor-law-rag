from datetime import date
from pathlib import Path

from labor_law_rag.normalize.annex import annex_related_articles, clean_table_text, parse_annexes
from labor_law_rag.normalize.qa import whole_doc_unit

FIX = Path(__file__).parent.parent / "fixtures" / "law"


def _parse():
    return parse_annexes((FIX / "근로기준법시행령.xml").read_bytes(), law_name="근로기준법 시행령",
                         effective_date=date(2025, 10, 23), url="u")


def test_annex_1_of_lsa_decree():
    r = _parse()
    assert len(r.docs) == 7 and r.missing == []
    d = next(d for d in r.docs if d.doc_id == "annex:근로기준법 시행령 별표 1")
    assert d.source_type == "annex" and d.date == date(2025, 10, 23)
    assert "상시 4명 이하" in d.title
    assert "제2장 근로계약 | 제15조, 제17조, 제18조, 제19조제1항, 제20조부터 제22조까지의 규정" in d.text
    assert "제4장 근로시간과 휴식 | 제54조, 제55조제1항, 제63조" in d.text
    assert not any(ch in d.text for ch in "┏┃│┠━─")
    u = whole_doc_unit(d)
    assert u.unit_id == "근로기준법 시행령 별표 1" and (u.start, u.end) == (0, len(d.text))


def test_annex_without_text_goes_to_missing():
    xml = """<?xml version="1.0" encoding="UTF-8"?><법령><기본정보><법령명_한글>테스트법</법령명_한글></기본정보>
    <별표><별표단위><별표번호>0002</별표번호><별표가지번호>01</별표가지번호><별표구분>별표</별표구분>
    <별표제목>서식(제3조 관련)</별표제목><별표서식PDF파일링크>/LSW/x.pdf</별표서식PDF파일링크><별표내용></별표내용></별표단위>
    <별표단위><별표번호>0003</별표번호><별표가지번호>00</별표가지번호><별표구분>서식</별표구분>
    <별표제목>신청서</별표제목><별표내용>x</별표내용></별표단위></별표></법령>""".encode()
    r = parse_annexes(xml, law_name="테스트법", effective_date=date(2025, 1, 1), url="u")
    assert r.docs == []  # 서식은 별표가 아니므로 제외
    assert r.missing == [{"law": "테스트법", "annex_no": "2의1", "title": "서식(제3조 관련)", "file_url": "/LSW/x.pdf"}]


def test_annex_number_zero_means_single_annex():
    from lxml import etree  # noqa: F401

    xml = """<?xml version="1.0" encoding="UTF-8"?><법령><별표><별표단위><별표번호>0000</별표번호>
    <별표가지번호>00</별표가지번호><별표구분>별표</별표구분><별표제목>보상표(제80조 관련)</별표제목>
    <별표내용>■ 근로기준법 [별표]\n\n  내용  </별표내용></별표단위></별표></법령>""".encode()
    r = parse_annexes(xml, law_name="근로기준법", effective_date=date(2026, 10, 8), url="u")
    assert r.docs[0].doc_id == "annex:근로기준법 별표"


def test_clean_table_text_merges_wrapped_cells():
    raw = ("┏━━┯━━┓\n\n┃구분 │적용법규정 ┃\n\n┠──┼──┨\n\n┃제2장 근로계약 │제15조, 제20조부 ┃\n\n"
           "┃ │터 제22조까지 ┃\n\n┗━━┷━━┛\n\n  비고: 끝  ")
    assert clean_table_text(raw) == "구분 | 적용법규정\n제2장 근로계약 | 제15조, 제20조부터 제22조까지\n비고: 끝"


def test_annex_related_articles():
    assert annex_related_articles("구직급여의 소정급여일수(제50조제1항 관련)") == ["제50조"]
    assert annex_related_articles("자영업자(제69조의6 관련)") == ["제69조의6"]
    assert annex_related_articles("상시 4명 이하 ... 법 규정") == []
