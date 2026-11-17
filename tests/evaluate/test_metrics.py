from datetime import date

import pytest

from labor_law_rag.corpus import UnitIndex
from labor_law_rag.evaluate.metrics import bootstrap_ci, item_scores, paired_bootstrap_diff, score_run
from labor_law_rag.evaluate.runner import make_sanity_run
from labor_law_rag.models import Document, EvalItem, EvidenceUnit, RetrievedChunk


def _doc(doc_id, n, source_type="law"):
    return Document(doc_id=doc_id, source_type=source_type, title=doc_id, text="가" * n, date=date(2025, 1, 1),
                    url="", license="")


@pytest.fixture
def index2():
    units = [EvidenceUnit(unit_id="A", doc_id="d", start=0, end=100),
             EvidenceUnit(unit_id="B", doc_id="d", start=200, end=300)]
    return UnitIndex([_doc("d", 400), _doc("x", 50)], units)


@pytest.fixture
def index_with_long_interp():
    return UnitIndex([_doc("interp:9", 2000, "interpretation")],
                     [EvidenceUnit(unit_id="interp:9", doc_id="interp:9", start=0, end=2000)])


def chunk(doc, s, e, score=1.0):
    return RetrievedChunk(doc_id=doc, start=s, end=e, score=score)


def make_item(qid="q1", evidence=("A",), qtype="fact", no_answer_kind=None):
    return EvalItem(qid=qid, question="q", answer="a", qtype=qtype, origin="manual", evidence=list(evidence),
                    no_answer_kind=no_answer_kind)


def test_recall_is_fraction_of_evidence(index2):
    s = item_scores(make_item(evidence=["A", "B"]), [chunk("d", 0, 100), chunk("x", 0, 9)], index2)
    assert s["recall@1"] == 0.5 and s["all_hit@1"] == 0.0 and s["mrr"] == 1.0


def test_all_hit_and_mrr_rank(index2):
    s = item_scores(make_item(evidence=["A", "B"]),
                    [chunk("x", 0, 9), chunk("d", 200, 300), chunk("d", 0, 100)], index2)
    assert s["mrr"] == 0.5 and s["recall@1"] == 0.0 and s["all_hit@5"] == 1.0 and s["recall@10"] == 1.0


def test_mrr_zero_beyond_10(index2):
    chunks = [chunk("x", 0, 9)] * 10 + [chunk("d", 0, 100)]
    assert item_scores(make_item(), chunks, index2)["mrr"] == 0.0


def test_duplicate_chunks_do_not_double_count(index2):
    s = item_scores(make_item(evidence=["A", "B"]), [chunk("d", 0, 100), chunk("d", 0, 100)], index2)
    assert s["recall@5"] == 0.5


def test_long_interpretation_unit_found_by_inner_chunk(index_with_long_interp):
    item = make_item(evidence=["interp:9"])
    assert item_scores(item, [chunk("interp:9", 100, 600)], index_with_long_interp)["recall@1"] == 1.0


def test_missing_qid_scores_zero_and_no_answer_excluded(index2):
    items = [make_item(qid="q1", evidence=["A"]), make_item(qid="q2", evidence=["B"]),
             make_item(qid="q3", qtype="no_answer", evidence=[], no_answer_kind="out_of_scope")]
    r = score_run(items, {"q1": [chunk("d", 0, 100)]}, index2)
    assert r.n_items == 2 and r.missing_qids == ["q2"] and r.overall["recall@5"].mean == 0.5
    assert r.n_by_qtype == {"fact": 2}
    assert r.by_qtype["fact"]["recall@5"].mean == 0.5


def test_avg_chunk_chars_counts_distinct_chunks(index2):
    r = score_run([make_item()], {"q1": [chunk("d", 0, 100), chunk("d", 0, 100), chunk("x", 0, 50)]}, index2)
    assert r.avg_chunk_chars == 75.0


def test_bootstrap_ci_brackets_mean_and_is_deterministic():
    v = [1.0] * 30 + [0.0] * 30
    lo, hi = bootstrap_ci(v, seed=3)
    assert lo < 0.5 < hi and (lo, hi) == bootstrap_ci(v, seed=3)
    assert bootstrap_ci([1.0] * 10) == (1.0, 1.0)


def test_paired_diff_requires_same_qids():
    d = paired_bootstrap_diff({"q1": 0.0, "q2": 1.0}, {"q1": 1.0, "q2": 1.0}, seed=1)
    assert d.mean == 0.5 and d.ci_low <= 0.5 <= d.ci_high
    with pytest.raises(ValueError):
        paired_bootstrap_diff({"q1": 0.0}, {"q2": 1.0})


def test_oracle_run_scores_perfect(law_index):
    items = [make_item(qid="q1", evidence=["근로기준법 제60조 제1항", "근로기준법 제60조 제2항"]),
             make_item(qid="q2", evidence=["근로기준법 제76조의2"]),
             make_item(qid="q3", qtype="no_answer", evidence=[], no_answer_kind="in_scope_missing")]
    run = {r.qid: r.chunks for r in make_sanity_run("oracle", items, law_index, seed=1)}
    s = score_run(items, run, law_index)
    assert s.overall["all_hit@10"].mean == 1.0 and s.overall["mrr"].mean == 1.0


def test_random_run_has_ten_chunks(law_index):
    rows = make_sanity_run("random", [make_item(qid="q1", evidence=["근로기준법 제76조의2"])], law_index, seed=1)
    assert len(rows) == 1 and len(rows[0].chunks) == min(10, len(law_index.all_units()))
