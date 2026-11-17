import json
from datetime import date

import pytest

from labor_law_rag.corpus import UnitIndex, build_corpus, select_holdout, tag_topics
from labor_law_rag.io import read_jsonl, write_jsonl
from labor_law_rag.models import Document, EvidenceUnit

TOPICS = {"연차휴가": ["연차"], "퇴직금": ["퇴직금"], "주휴수당": ["주휴"]}


def _interp(i: int, text: str) -> Document:
    return Document(doc_id=f"interp:{i}", source_type="interpretation", title=f"안건 {i}", text=text,
                    date=date(2020, 1, 1), url="", license="공공누리 제1유형")


def make_docs(interp: int) -> list[Document]:
    texts = ["연차 질의", "퇴직금 질의", "주휴 질의"]
    return [tag_topics(_interp(i, texts[i % 3]), TOPICS) for i in range(interp)]


def test_tag_topics_matches_title_and_text():
    d = tag_topics(_interp(1, "퇴직금과 연차에 관한 질의"), TOPICS)
    assert d.topics == ["연차휴가", "퇴직금"]  # topics.yaml 순서
    assert tag_topics(_interp(2, "산업안전 질의"), TOPICS).topics == []


def test_title_topic_comes_first():
    d = Document(doc_id="interp:5", source_type="interpretation", title="연차휴가 사용촉진 여부",
                 text="근로계약상 임금과 퇴직금에 관한 내용", date=None, url="", license="")
    topics = {"근로계약": ["근로계약"], "임금": ["임금"], "연차휴가": ["연차"], "퇴직금": ["퇴직금"]}
    assert tag_topics(d, topics).topics == ["연차휴가", "근로계약", "임금", "퇴직금"]


def test_exclude_phrases_do_not_trigger_topics():
    topics = {"근로시간": ["근로시간"], "해고": ["해고"]}
    d = Document(doc_id="interp:6", source_type="interpretation", title="근로시간면제자의 휴일 활동",
                 text="근로시간면제 한도 내 활동", date=None, url="", license="")
    assert tag_topics(d, topics, exclude=["근로시간면제"]).topics == []
    d2 = d.model_copy(update={"text": "근로시간면제와 무관하게 근로시간 단축"})
    assert tag_topics(d2, topics, exclude=["근로시간면제"]).topics == ["근로시간"]


def test_holdout_is_deterministic_and_sized():
    docs = make_docs(interp=120)
    a = select_holdout(docs, {"interpretation": 40}, seed=1)
    assert a == select_holdout(docs, {"interpretation": 40}, seed=1)
    assert len(a) == 40 and all(i.startswith("interp:") for i in a)


def test_holdout_keeps_topic_proportions():
    docs = make_docs(interp=120)  # 주제 3개가 40건씩
    a = select_holdout(docs, {"interpretation": 30}, seed=5)
    by_topic = {}
    for d in docs:
        if d.doc_id in a:
            by_topic[d.topics[0]] = by_topic.get(d.topics[0], 0) + 1
    assert by_topic == {"연차휴가": 10, "퇴직금": 10, "주휴수당": 10}


def test_holdout_more_than_available_fails():
    with pytest.raises(ValueError):
        select_holdout(make_docs(interp=5), {"interpretation": 10}, seed=1)


def _write_processed(tmp_path):
    p = tmp_path / "processed"
    law = Document(doc_id="law:근로기준법", source_type="law", title="근로기준법", text="제1조(목적) 이 법은 ...",
                   date=date(2025, 10, 23), url="", license="법령")
    write_jsonl(p / "law_documents.jsonl", [law])
    write_jsonl(p / "law_units.jsonl", [EvidenceUnit(unit_id="근로기준법 제1조", doc_id="law:근로기준법",
                                                     start=8, end=len(law.text))])
    interps = [_interp(i, ["연차 질의", "퇴직금 질의"][i % 2]) for i in range(10)]
    interps.append(_interp(99, "산업안전 질의"))  # 주제 없음 → 제외
    write_jsonl(p / "interp_documents.jsonl", interps)
    write_jsonl(p / "interp_units.jsonl",
                [EvidenceUnit(unit_id=d.doc_id, doc_id=d.doc_id, start=0, end=len(d.text)) for d in interps])
    return p


def run_build(tmp_path, force=False):
    p = tmp_path / "processed" if (tmp_path / "processed").exists() else _write_processed(tmp_path)
    return build_corpus(
        processed_dir=p, heldout_path=tmp_path / "heldout" / "eval_sources.jsonl",
        manifest_path=tmp_path / "manifest.json", topics=TOPICS, holdout_counts={"interpretation": 4},
        seed=1, base_date=date(2026, 11, 17), force=force,
    )


def test_heldout_docs_not_in_corpus(tmp_path):
    build = run_build(tmp_path)
    corpus_ids = {d.doc_id for d in read_jsonl(build.corpus_documents, Document)}
    held_ids = {d.doc_id for d in read_jsonl(build.heldout, Document)}
    assert corpus_ids.isdisjoint(held_ids) and len(held_ids) == 4
    unit_docs = {u.doc_id for u in read_jsonl(build.corpus_units, EvidenceUnit)}
    assert unit_docs <= corpus_ids


def test_off_topic_interpretation_is_excluded_but_laws_kept(tmp_path):
    build = run_build(tmp_path)
    corpus_ids = {d.doc_id for d in read_jsonl(build.corpus_documents, Document)}
    assert "law:근로기준법" in corpus_ids  # 주제 키워드가 없어도 법령은 유지
    assert "interp:99" not in corpus_ids


def test_manifest_records_hashes_and_counts(tmp_path):
    build = run_build(tmp_path)
    m = json.loads(build.manifest.read_text(encoding="utf-8"))
    assert m["base_date"] == "2026-11-17"
    assert m["files"]["corpus_documents.jsonl"]["count"] == 7  # 법령 1 + 주제 있는 해석 10 - 떼어 둔 4
    assert len(m["files"]["corpus_documents.jsonl"]["sha256"]) == 64


LONG = [
    "연차휴가를 사용하지 않고 퇴직한 경우 미사용 연차휴가수당을 지급해야 하는지 질의합니다 회답 지급해야 합니다",
    "퇴직금 산정 시 평균임금에 정기상여금을 포함하는지 질의합니다 회답 지급된 상여금의 12분의 3을 포함합니다",
    "주휴수당은 1주 소정근로일을 개근한 경우에만 발생하는지 질의합니다 회답 개근하면 유급휴일을 줍니다",
]


def test_near_duplicates_finds_rewordings_only():
    from labor_law_rag.corpus import near_duplicates

    held = [_interp(1, LONG[0])]
    twin = _interp(2, LONG[0].replace("질의합니다", "묻습니다"))
    other = _interp(3, LONG[1])
    law = Document(doc_id="law:x", source_type="law", title="x", text=LONG[0], date=None, url="", license="")
    found = near_duplicates(held, [twin, other, law], threshold=0.75)
    assert set(found) == {"interp:2"}
    assert found["interp:2"][0] == "interp:1" and 0.75 <= found["interp:2"][1] < 1.0


def test_build_removes_near_duplicates_of_heldout(tmp_path):
    p = tmp_path / "processed"
    p.mkdir()
    interps = [_interp(i, LONG[i] + f" 사례 {i}") for i in range(3)]
    interps += [_interp(100 + i, LONG[i] + f" 사례 {i} 참고") for i in range(3)]  # 각 해석의 쌍둥이
    write_jsonl(p / "interp_documents.jsonl", interps)
    write_jsonl(p / "interp_units.jsonl",
                [EvidenceUnit(unit_id=d.doc_id, doc_id=d.doc_id, start=0, end=len(d.text)) for d in interps])
    build = build_corpus(
        processed_dir=p, heldout_path=tmp_path / "held.jsonl", manifest_path=tmp_path / "m.json",
        topics=TOPICS, holdout_counts={"interpretation": 1}, seed=1, base_date=date(2026, 11, 17),
        near_dup_threshold=0.75,
    )
    held = {d.doc_id for d in read_jsonl(build.heldout, Document)}
    corpus = {d.doc_id for d in read_jsonl(build.corpus_documents, Document)}
    twin = {f"interp:{i}": f"interp:{(i + 100) % 200}" for i in [*range(3), *range(100, 103)]}
    assert all(twin[h] not in corpus for h in held)
    m = json.loads(build.manifest.read_text(encoding="utf-8"))
    removed = m["near_duplicates_removed"]
    assert {twin[h] for h in held} - held <= set(removed)
    assert all(v["heldout"] in held and v["score"] >= 0.75 for v in removed.values())
    assert not {u.doc_id for u in read_jsonl(build.corpus_units, EvidenceUnit)} & set(removed)


def test_rebuild_refused_without_force(tmp_path):
    run_build(tmp_path)
    with pytest.raises(FileExistsError):
        run_build(tmp_path)
    run_build(tmp_path, force=True)


def test_unit_index_text_and_lookup(tmp_path):
    build = run_build(tmp_path)
    idx = UnitIndex.from_files(build.corpus_documents, build.corpus_units)
    assert "근로기준법 제1조" in idx and "없는 단위" not in idx
    assert idx.text("근로기준법 제1조") == "이 법은 ..."
    assert [u.unit_id for u in idx.units_of("law:근로기준법")] == ["근로기준법 제1조"]
    assert idx.get("근로기준법 제1조").doc_id == "law:근로기준법"
