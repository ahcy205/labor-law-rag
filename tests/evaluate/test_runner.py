import json
from datetime import date

import pytest

from labor_law_rag.evaluate.runner import RunRow, SplitLockedError, evaluate
from labor_law_rag.io import read_jsonl, write_jsonl
from labor_law_rag.models import Document, EvalItem, EvidenceUnit, RetrievedChunk


@pytest.fixture
def setup(tmp_path):
    doc = Document(doc_id="d", source_type="law", title="d", text="가" * 300, date=date(2025, 1, 1), url="",
                   license="")
    write_jsonl(tmp_path / "docs.jsonl", [doc])
    write_jsonl(tmp_path / "units.jsonl", [EvidenceUnit(unit_id="A", doc_id="d", start=0, end=100)])
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    items = [EvalItem(qid=f"q{i}", question="q", answer="a", qtype="fact", origin="manual", evidence=["A"],
                      split="dev" if i < 3 else "test") for i in range(5)]
    write_jsonl(tmp_path / "evalset.jsonl", items)
    run = tmp_path / "run.jsonl"
    write_jsonl(run, [RunRow(qid=f"q{i}", chunks=[RetrievedChunk(doc_id="d", start=0, end=100, score=1.0)])
                      for i in range(5)])
    kw = dict(evalset_path=tmp_path / "evalset.jsonl", results_dir=tmp_path / "results",
              docs_path=tmp_path / "docs.jsonl", units_path=tmp_path / "units.jsonl",
              manifest_path=tmp_path / "manifest.json")
    return run, kw, tmp_path


def test_test_split_requires_final(setup):
    run, kw, tmp = setup
    with pytest.raises(SplitLockedError):
        evaluate(run, experiment="E0", split="test", **kw)
    assert not (tmp / "results").exists()


def test_results_dir_has_meta(setup):
    run, kw, _ = setup
    out = evaluate(run, experiment="E0", split="dev", **kw)
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["n_items"] == 3 and metrics["overall"]["recall@5"]["mean"] == 1.0
    assert len(read_jsonl(out / "per_item.jsonl")) == 3
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    for key in ("git_commit", "git_dirty", "ts", "split", "evalset_sha256", "corpus_manifest_sha256",
                "run_path", "run_sha256"):
        assert key in meta
    assert out.parent.name == "E0" and out.name.endswith("-dev")


def test_final_test_run_is_logged(setup):
    run, kw, tmp = setup
    evaluate(run, experiment="E0", split="test", final=True, **kw)
    log = read_jsonl(tmp / "results" / "test_log.jsonl")
    assert len(log) == 1 and log[0]["experiment"] == "E0" and "git_commit" in log[0]
