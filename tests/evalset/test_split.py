import pytest

from labor_law_rag.evalset.split import assign_splits, finalize, load_evalset
from labor_law_rag.models import EvalItem


def make_items(spec: dict[str, int]) -> list[EvalItem]:
    items = []
    for qtype, n in spec.items():
        for i in range(n):
            if qtype == "no_answer":
                kind = "out_of_scope" if i % 2 == 0 else "in_scope_missing"
                items.append(EvalItem(qid=f"{qtype}-{i}", question="q", answer="a", qtype=qtype,
                                      origin="manual", no_answer_kind=kind))
            else:
                items.append(EvalItem(qid=f"{qtype}-{i}", question="q", answer="a", qtype=qtype,
                                      origin="manual", evidence=["u"]))
    return items


def test_split_ratio_per_type_and_deterministic():
    items = make_items({"fact": 45, "conditional": 30, "no_answer": 22})
    a = assign_splits(items, seed=7)
    assert a == assign_splits(items, seed=7)
    assert sum(1 for i in a if i.qtype == "fact" and i.split == "dev") == 27
    assert sum(1 for i in a if i.qtype == "conditional" and i.split == "dev") == 18
    for kind in ("out_of_scope", "in_scope_missing"):
        k = [i for i in a if i.no_answer_kind == kind]
        assert {i.split for i in k} == {"dev", "test"}
        assert sum(i.split == "dev" for i in k) == 7  # round(11 * 0.6) = 7


def test_split_order_independent_of_input_order():
    items = make_items({"fact": 10})
    a = {i.qid: i.split for i in assign_splits(items, seed=1)}
    b = {i.qid: i.split for i in assign_splits(list(reversed(items)), seed=1)}
    assert a == b


class _FakeStore:
    def __init__(self, items):
        self._items = items

    def current(self):
        return {i.qid: i for i in self._items}


def test_force_refinalize_keeps_existing_splits(tmp_path):
    out = tmp_path / "evalset.jsonl"
    finalize(_FakeStore(make_items({"calculation": 5, "fact": 20, "no_answer": 10})), out, seed=1)
    before = {i.qid: i.split for i in load_evalset(out, "all")}
    more = make_items({"calculation": 10, "fact": 20, "no_answer": 10})  # calculation 5개 추가
    finalize(_FakeStore(more), out, seed=1, force=True)
    after = {i.qid: i.split for i in load_evalset(out, "all")}
    assert all(after[q] == s for q, s in before.items())
    assert sum(after[f"calculation-{i}"] == "dev" for i in range(10)) == 6


def test_force_refinalize_drops_removed_items(tmp_path):
    out = tmp_path / "evalset.jsonl"
    finalize(_FakeStore(make_items({"fact": 10})), out, seed=1)
    finalize(_FakeStore(make_items({"fact": 8})), out, seed=1, force=True)
    assert len(load_evalset(out, "all")) == 8


def test_finalize_writes_and_refuses_overwrite(tmp_path):
    out = tmp_path / "evalset.jsonl"
    store = _FakeStore(make_items({"fact": 5, "no_answer": 4}))
    finalize(store, out, seed=1)
    loaded = load_evalset(out, "all")
    assert len(loaded) == 9 and all(i.split in ("dev", "test") for i in loaded)
    assert len(load_evalset(out, "dev")) + len(load_evalset(out, "test")) == 9
    with pytest.raises(FileExistsError):
        finalize(store, out, seed=1)
    finalize(store, out, seed=1, force=True)
