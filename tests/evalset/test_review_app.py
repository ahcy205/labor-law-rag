import gradio as gr

from labor_law_rag.evalset.review_app import build_app, evidence_panel, form_to_item
from labor_law_rag.models import DraftItem

BASE = DraftItem(qid="llm-1", question="q", answer="a", qtype="fact", origin="llm_draft",
                 evidence=["근로기준법 제60조 제1항"])


def test_form_to_item_parses_numbers_and_evidence_lines():
    it = form_to_item(BASE, "연차 몇 개?", "15일", "15, 1.5", "conditional", "",
                      " 근로기준법 제60조 제1항 \n\n근로기준법 제60조 제2항\n", "메모")
    assert it.qid == "llm-1" and it.origin == "llm_draft"
    assert it.answer_numbers == [15.0, 1.5]
    assert it.evidence == ["근로기준법 제60조 제1항", "근로기준법 제60조 제2항"]
    assert it.qtype == "conditional" and it.no_answer_kind is None and it.notes == "메모"


def test_form_to_item_no_answer_kind():
    it = form_to_item(BASE, "q", "a", "", "no_answer", "in_scope_missing", "", "")
    assert it.no_answer_kind == "in_scope_missing" and it.evidence == [] and it.answer_numbers == []


def test_bad_number_raises_value_error():
    import pytest

    with pytest.raises(ValueError):
        form_to_item(BASE, "q", "a", "열다섯", "fact", "", "x", "")


def test_evidence_panel_shows_text_and_flags_unknown(law_index):
    md = evidence_panel(["근로기준법 제60조 제1항", "근로기준법 제999조"], law_index)
    assert "15일의 유급휴가" in md and "말뭉치에 없음" in md


def test_build_app_returns_blocks(tmp_path, law_index):
    from labor_law_rag.evalset.review_store import ReviewStore
    from labor_law_rag.io import write_jsonl

    write_jsonl(tmp_path / "d.jsonl", [BASE])
    store = ReviewStore(tmp_path / "d.jsonl", tmp_path / "log.jsonl", law_index, heldout_ids=set())
    assert isinstance(build_app(store, law_index, heldout={}), gr.Blocks)
