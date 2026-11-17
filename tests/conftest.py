from datetime import date

import pytest

from labor_law_rag.corpus import UnitIndex
from labor_law_rag.models import Document, EvidenceUnit


def make_law_index() -> UnitIndex:
    """근로기준법 제60조 ①②, 제76조의2(항 없음), 근로기준법 시행령 제33조로 된 작은 색인."""
    p1 = "① 사용자는 1년간 80퍼센트 이상 출근한 근로자에게 15일의 유급휴가를 주어야 한다."
    p2 = "② 사용자는 계속하여 근로한 기간이 1년 미만인 근로자에게 1개월 개근 시 1일의 유급휴가를 주어야 한다."
    a76 = "사용자 또는 근로자는 직장에서의 지위 또는 관계 등의 우위를 이용하여 ... 하여서는 아니 된다."
    head60, head76 = "제60조(연차 유급휴가)\n", "\n제76조의2(직장 내 괴롭힘의 금지) "
    text = head60 + p1 + "\n" + p2 + head76 + a76
    law = Document(doc_id="law:근로기준법", source_type="law", title="근로기준법", text=text,
                   date=date(2025, 10, 23), url="", license="법령", topics=["연차휴가"])
    s1 = len(head60)
    s2 = s1 + len(p1) + 1
    s76 = s2 + len(p2) + len(head76)
    dec_text = "제33조(임금대장의 기재사항) ① 사용자는 임금대장에 ..."
    dec = Document(doc_id="decree:근로기준법 시행령", source_type="decree", title="근로기준법 시행령",
                   text=dec_text, date=date(2025, 10, 23), url="", license="법령", topics=["임금"])
    units = [
        EvidenceUnit(unit_id="근로기준법 제60조 제1항", doc_id=law.doc_id, start=s1, end=s1 + len(p1)),
        EvidenceUnit(unit_id="근로기준법 제60조 제2항", doc_id=law.doc_id, start=s2, end=s2 + len(p2)),
        EvidenceUnit(unit_id="근로기준법 제76조의2", doc_id=law.doc_id, start=s76, end=s76 + len(a76)),
        EvidenceUnit(unit_id="근로기준법 시행령 제33조 제1항", doc_id=dec.doc_id, start=17, end=len(dec_text)),
    ]
    return UnitIndex([law, dec], units)


@pytest.fixture
def law_index() -> UnitIndex:
    return make_law_index()
