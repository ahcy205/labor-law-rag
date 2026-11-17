import pytest
from pydantic import ValidationError

from labor_law_rag.models import EvalItem, EvidenceUnit


def test_no_answer_item_must_have_kind_and_no_evidence():
    with pytest.raises(ValidationError):
        EvalItem(qid="q1", question="산재 보상은?", answer="자료에 없음", qtype="no_answer", origin="manual")
    with pytest.raises(ValidationError):
        EvalItem(
            qid="q1", question="산재 보상은?", answer="자료에 없음", qtype="no_answer", origin="manual",
            no_answer_kind="out_of_scope", evidence=["근로기준법 제60조 제1항"],
        )
    ok = EvalItem(qid="q1", question="산재 보상은?", answer="자료에 없음", qtype="no_answer",
                  origin="manual", no_answer_kind="out_of_scope")
    assert ok.evidence == []


def test_answerable_item_needs_evidence_and_no_kind():
    with pytest.raises(ValidationError):
        EvalItem(qid="q2", question="연차?", answer="15일", qtype="fact", origin="manual", evidence=[])
    with pytest.raises(ValidationError):
        EvalItem(qid="q2", question="연차?", answer="15일", qtype="fact", origin="manual",
                 evidence=["근로기준법 제60조 제1항"], no_answer_kind="out_of_scope")


def test_number_tolerance_default():
    item = EvalItem(qid="q3", question="퇴직금?", answer="750만 원", answer_numbers=[7500000],
                    qtype="calculation", origin="manual", evidence=["x"])
    assert item.number_rel_tol == 0.01


def test_unit_end_must_exceed_start():
    with pytest.raises(ValidationError):
        EvidenceUnit(unit_id="u", doc_id="d", start=5, end=5)
