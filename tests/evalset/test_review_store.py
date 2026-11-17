import pytest

from labor_law_rag.evalset.review_store import ReviewStore
from labor_law_rag.io import write_jsonl
from labor_law_rag.models import DraftItem


@pytest.fixture
def store_factory(tmp_path, law_index):
    drafts = tmp_path / "drafts.jsonl"
    write_jsonl(drafts, [
        DraftItem(qid="llm-1", question="연차 몇 개?", answer="15일", answer_numbers=[15], qtype="fact",
                  origin="llm_draft", evidence=["근로기준법 제60조 제1항"]),
        DraftItem(qid="interp-2", question="8개월 연차?", answer="최대 8일", qtype="conditional",
                  origin="interpretation_adapted", origin_detail="interp:2024-1", evidence=[], notes="근거 미지정"),
        DraftItem(qid="cc-3", question="산재 보상은?", answer="자료에 없음", qtype="no_answer",
                  origin="claude_code_draft", no_answer_kind="out_of_scope"),
    ])
    log = tmp_path / "review_log.jsonl"
    return lambda: ReviewStore(drafts, log, law_index, heldout_ids={"interp:2024-1"})


def test_decisions_survive_restart(store_factory):
    s = store_factory()
    first = s.pending()[0]
    s.record(first.qid, "approve", first, derivable=True)
    s2 = store_factory()
    assert first.qid not in {d.qid for d in s2.pending()}
    assert first.qid in s2.current()
    assert s2.progress() == (1, 3)


def test_unknown_evidence_rejected_and_not_logged(store_factory):
    s = store_factory()
    d = s.pending()[0]
    bad = d.model_copy(update={"evidence": ["근로기준법 제999조"]})
    with pytest.raises(ValueError, match="제999조"):
        s.record(d.qid, "edit", bad, derivable=True)
    assert s.progress()[0] == 0


def test_heldout_doc_cannot_be_evidence(store_factory):
    s = store_factory()
    d = s.pending()[1]
    bad = d.model_copy(update={"evidence": ["interp:2024-1"]})
    with pytest.raises(ValueError, match="떼어 둔"):
        s.record(d.qid, "edit", bad, derivable=True)


def test_draft_without_evidence_cannot_be_approved_as_is(store_factory):
    s = store_factory()
    d = s.pending()[1]
    with pytest.raises(ValueError):
        s.record(d.qid, "approve", d, derivable=True)
    fixed = d.model_copy(update={"evidence": ["근로기준법 제60조 제2항"], "notes": ""})
    s.record(d.qid, "edit", fixed, derivable=True)
    assert s.current()["interp-2"].evidence == ["근로기준법 제60조 제2항"]


def test_approve_requires_derivable_check(store_factory):
    s = store_factory()
    d = s.pending()[0]
    with pytest.raises(ValueError, match="근거"):
        s.record(d.qid, "approve", d)
    assert s.progress()[0] == 0


def test_no_answer_item_does_not_need_derivable(store_factory):
    s = store_factory()
    d = s.pending()[2]
    s.record(d.qid, "approve", d)
    assert s.current()["cc-3"].qtype == "no_answer"


def test_qid_mismatch_rejected(store_factory):
    s = store_factory()
    d = s.pending()[0]
    with pytest.raises(ValueError):
        s.record("other", "approve", d, derivable=True)


def test_last_decision_wins_and_delete_removes(store_factory):
    s = store_factory()
    d = s.pending()[0]
    s.record(d.qid, "approve", d, derivable=True)
    s.record(d.qid, "delete")
    assert d.qid not in s.current()
    assert s.progress() == (1, 3)


def test_reopen_returns_item_to_pending_and_keeps_last_edit(store_factory):
    s = store_factory()
    d = s.pending()[0]
    edited = d.model_copy(update={"question": "연차는 며칠?"})
    s.record(d.qid, "edit", edited, derivable=True)
    s.reopen(d.qid, "근거 문서가 말뭉치에서 빠짐")
    s2 = store_factory()
    assert d.qid in {x.qid for x in s2.pending()} and d.qid not in s2.current()
    assert s2.progress() == (0, 3)
    assert s2.latest(d.qid).question == "연차는 며칠?"
    assert s2.reopen_reason(d.qid) == "근거 문서가 말뭉치에서 빠짐"
    s2.record(d.qid, "approve", s2.latest(d.qid), derivable=True)
    assert s2.current()[d.qid].question == "연차는 며칠?" and s2.reopen_reason(d.qid) is None


def test_reopen_unknown_or_undecided_rejected(store_factory):
    s = store_factory()
    with pytest.raises(ValueError):
        s.reopen("nope", "x")
    with pytest.raises(ValueError):
        s.reopen(s.pending()[0].qid, "x")


def test_stale_lists_evidence_missing_from_index(store_factory, tmp_path):
    s = store_factory()
    d = s.pending()[0]
    s.record(d.qid, "approve", d, derivable=True)
    assert s.stale() == {}
    log = tmp_path / "review_log.jsonl"
    log.write_text(log.read_text(encoding="utf-8").replace("제60조 제1항", "제60조 제9항"), encoding="utf-8")
    assert s.stale() == {"llm-1": ["근로기준법 제60조 제9항"]}
