from labor_law_rag.io import append_jsonl, read_jsonl, write_jsonl


def test_jsonl_roundtrip_keeps_korean(tmp_path):
    p = tmp_path / "a" / "x.jsonl"
    assert write_jsonl(p, [{"q": "연차 몇 개?"}, {"q": "주휴수당"}]) == 2
    assert read_jsonl(p) == [{"q": "연차 몇 개?"}, {"q": "주휴수당"}]
    assert "연차" in p.read_text(encoding="utf-8")


def test_append_jsonl_adds_line(tmp_path):
    p = tmp_path / "log.jsonl"
    append_jsonl(p, {"a": 1})
    append_jsonl(p, {"a": 2})
    assert read_jsonl(p) == [{"a": 1}, {"a": 2}]
