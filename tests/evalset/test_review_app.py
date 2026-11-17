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


OPINION = {
    "qid": "llm-1", "verdict": "edit", "confidence": "low", "dup_leak": True,
    "reason": "제60조 제1항 '15일' 확인",
    "proposed": {"question": "연차 며칠?", "answer": "15일", "answer_numbers": [15.0],
                 "evidence": ["근로기준법 제60조 제1항"], "qtype": "fact", "no_answer_kind": None, "notes": "n"},
    "changes": [{"field": "question", "before": "q", "after": "연차 며칠?", "why": "구어체로"}],
}


def test_opinion_panel_shows_verdict_reason_and_changes():
    from labor_law_rag.evalset.review_app import opinion_panel

    md = opinion_panel(OPINION)
    assert "수정" in md and "확신 낮음" in md and "중복 원문" in md
    assert "15일" in md and "구어체로" in md and "연차 며칠?" in md


def test_opinion_panel_without_opinion():
    from labor_law_rag.evalset.review_app import opinion_panel

    assert "의견 없음" in opinion_panel(None)


def test_proposal_to_form_values():
    from labor_law_rag.evalset.review_app import NO_KIND, proposal_to_form

    q, a, n, t, k, ev, nt = proposal_to_form(OPINION["proposed"])
    assert (q, a, n, t, k, ev, nt) == ("연차 며칠?", "15일", "15", "fact", NO_KIND, "근로기준법 제60조 제1항", "n")


def test_build_app_with_opinions(tmp_path, law_index):
    from labor_law_rag.evalset.review_store import ReviewStore
    from labor_law_rag.io import write_jsonl

    write_jsonl(tmp_path / "d.jsonl", [BASE])
    store = ReviewStore(tmp_path / "d.jsonl", tmp_path / "log.jsonl", law_index, heldout_ids=set())
    assert isinstance(build_app(store, law_index, heldout={}, opinions={"llm-1": OPINION}), gr.Blocks)
