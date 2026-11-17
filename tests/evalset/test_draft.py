import json

from labor_law_rag.evalset.draft import (
    append_drafts,
    draft_from_heldout,
    draft_from_units,
    import_drafts,
    make_qid,
)
from labor_law_rag.io import read_jsonl
from labor_law_rag.llm import FakeLLM
from labor_law_rag.models import Document, DraftItem


def _src(text):
    return Document(doc_id="interp:2024-1", source_type="interpretation", title="연차", url="",
                    license="공공누리 제1유형", date=None, text=text)


def _out(q="q", a="a", nums=(), qtype="fact"):
    return json.dumps({"question": q, "answer": a, "answer_numbers": list(nums), "qtype": qtype},
                      ensure_ascii=False)


def test_heldout_draft_never_cites_itself(law_index):
    src = _src("질의\n입사 8개월 연차는?\n\n회답\n근로기준법 제60조제2항에 따라 ...")
    llm = FakeLLM([_out("8개월 일했는데 연차 몇 개?", "최대 8일", [8], "conditional")])
    [item] = draft_from_heldout(llm, [src], law_index, model="qwen3:8b")
    assert item.evidence == ["근로기준법 제60조 제2항"]
    assert item.origin == "interpretation_adapted" and item.origin_detail == "interp:2024-1"
    assert item.qtype == "conditional" and item.answer_numbers == [8]
    assert "<document>" in llm.calls[0]["prompt"] and "입사 8개월" in llm.calls[0]["prompt"]


def test_heldout_with_two_citations_is_multi_doc(law_index):
    src = _src("질의\n...\n\n회답\n근로기준법 제60조제2항 및 같은 법 시행령 제33조제1항에 따라")
    [item] = draft_from_heldout(FakeLLM([_out(qtype="fact")]), [src], law_index, model="m")
    assert item.qtype == "multi_doc" and len(item.evidence) == 2


def test_heldout_without_citation_is_kept_with_note(law_index):
    [item] = draft_from_heldout(FakeLLM([_out()]), [_src("질의\n...\n\n회답\n인용 없음")], law_index, model="m")
    assert item.evidence == [] and item.notes == "근거 미지정"


def test_unit_drafts_cite_source_unit(law_index):
    llm = FakeLLM([_out("연차 15일 조건?", "80% 이상 출근", [15], "fact")] * 2)
    items = draft_from_units(llm, law_index, model="qwen3:8b", n=2, seed=1)
    assert len(items) == 2
    for it in items:
        assert len(it.evidence) == 1 and it.evidence[0] in law_index
        assert it.origin == "llm_draft" and it.origin_detail == "qwen3:8b"
        assert law_index.text(it.evidence[0])[:20] in llm.calls[items.index(it)]["prompt"]


def test_failed_llm_output_is_skipped_not_fatal(law_index):
    llm = FakeLLM(["bad"] * 3 + [_out()])
    items = draft_from_units(llm, law_index, model="m", n=2, seed=1)
    assert len(items) == 1


def test_unit_draft_sampling_is_deterministic(law_index):
    a = draft_from_units(FakeLLM([_out()] * 3), law_index, model="m", n=3, seed=7)
    b = draft_from_units(FakeLLM([_out()] * 3), law_index, model="m", n=3, seed=7)
    assert [i.evidence for i in a] == [i.evidence for i in b]


def test_target_qtype_is_forced_and_in_prompt(law_index):
    llm = FakeLLM([_out(qtype="fact")] * 2)
    items = draft_from_units(llm, law_index, model="m", n=2, seed=1, qtype="conditional")
    assert [i.qtype for i in items] == ["conditional", "conditional"]
    assert "반드시 conditional" in llm.calls[0]["prompt"]


def test_calculation_target_prefers_units_with_numbers(law_index):
    llm = FakeLLM([_out()] * 4)
    items = draft_from_units(llm, law_index, model="m", n=4, seed=1, qtype="calculation")
    # 숫자(일 · 퍼센트)가 있는 단위는 제60조 ①②뿐이므로 그 둘만 뽑힌다
    assert sorted(i.evidence[0] for i in items) == ["근로기준법 제60조 제1항", "근로기준법 제60조 제2항"]


def test_calculation_prompt_demands_premises(law_index):
    llm = FakeLLM([_out()])
    draft_from_units(llm, law_index, model="m", n=1, seed=1)
    assert "전제" in llm.calls[0]["prompt"]


def test_import_and_append_skip_duplicate_questions(tmp_path):
    src = tmp_path / "manual.jsonl"
    src.write_text(
        '{"question": "산재 보상은?", "answer": "자료에 없음", "qtype": "no_answer", "no_answer_kind": "out_of_scope"}\n'
        '{"question": "2025년 최저임금은?", "answer": "10,030원", "answer_numbers": [10030], "qtype": "amendment",'
        ' "evidence": ["최저임금 고시"]}\n',
        encoding="utf-8",
    )
    items = import_drafts(src, origin="claude_code_draft")
    assert [i.origin for i in items] == ["claude_code_draft"] * 2
    assert items[0].qid == make_qid("claude_code_draft", "산재 보상은?") and items[0].qid.startswith("cc-")
    drafts = tmp_path / "drafts.jsonl"
    assert append_drafts(drafts, items) == 2
    assert append_drafts(drafts, items) == 0
    assert len(read_jsonl(drafts, DraftItem)) == 2
