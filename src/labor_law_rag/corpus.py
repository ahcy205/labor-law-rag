"""주제 필터, 평가용 원문 떼기, 말뭉치 확정 (설계 3.2, 4.3)."""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel

from labor_law_rag.io import read_jsonl, write_jsonl
from labor_law_rag.models import Document, EvidenceUnit

# 주제 필터를 거는 출처. 법령 · 시행령 · 고시 · 별표는 모두 남긴다.
TOPIC_FILTERED = {"interpretation"}


def tag_topics(doc: Document, topics: dict[str, list[str]], exclude: list[str] | tuple = ()) -> Document:
    """제목에 맞는 주제를 앞에, 본문에만 맞는 주제를 뒤에 둔다. topics[0]은 층화의 기준이 된다.

    exclude의 말(예: "근로시간면제")은 매칭 전에 지운다.
    """
    title, text = doc.title, doc.text
    for phrase in exclude:
        title, text = title.replace(phrase, " "), text.replace(phrase, " ")
    in_title = [name for name, kws in topics.items() if any(kw in title for kw in kws)]
    in_text = [name for name, kws in topics.items()
               if name not in in_title and any(kw in text for kw in kws)]
    return doc.model_copy(update={"topics": in_title + in_text})


def _allocate(group_sizes: dict[str, int], total: int) -> dict[str, int]:
    """그룹 크기에 비례해 total을 나눈다(최대 나머지 방식). 그룹 크기를 넘지 않는다."""
    n = sum(group_sizes.values())
    quotas = {g: total * s / n for g, s in group_sizes.items()}
    alloc = {g: min(int(q), group_sizes[g]) for g, q in quotas.items()}
    remaining = total - sum(alloc.values())
    for g in sorted(quotas, key=lambda g: (-(quotas[g] - int(quotas[g])), g)):
        if remaining == 0:
            break
        if alloc[g] < group_sizes[g]:
            alloc[g] += 1
            remaining -= 1
    return alloc


def select_holdout(docs: list[Document], counts: dict[str, int], seed: int) -> set[str]:
    rng = random.Random(seed)
    chosen: set[str] = set()
    for source_type, count in sorted(counts.items()):
        pool = sorted((d for d in docs if d.source_type == source_type), key=lambda d: d.doc_id)
        if count > len(pool):
            raise ValueError(f"{source_type}: 떼어 둘 {count}건이 전체 {len(pool)}건보다 많습니다")
        groups: dict[str, list[Document]] = defaultdict(list)
        for d in pool:
            groups[d.topics[0] if d.topics else ""].append(d)
        alloc = _allocate({g: len(v) for g, v in groups.items()}, count)
        for g in sorted(groups):
            chosen.update(d.doc_id for d in rng.sample(groups[g], alloc[g]))
    return chosen


class CorpusBuild(BaseModel):
    corpus_documents: Path
    corpus_units: Path
    heldout: Path
    manifest: Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_corpus(
    *,
    processed_dir: Path,
    heldout_path: Path,
    manifest_path: Path,
    topics: dict[str, list[str]],
    exclude: list[str] | tuple = (),
    holdout_counts: dict[str, int],
    seed: int,
    base_date: date,
    force: bool = False,
) -> CorpusBuild:
    processed_dir = Path(processed_dir)
    if Path(heldout_path).exists() and not force:
        raise FileExistsError(
            f"{heldout_path}가 이미 있습니다. 문항 초안을 만든 뒤 떼어 둔 원문이 바뀌면 안 되므로 "
            "다시 만들려면 --force를 쓰세요"
        )

    docs: list[Document] = []
    units: list[EvidenceUnit] = []
    for p in sorted(processed_dir.glob("*_documents.jsonl")):
        if p.name.startswith("corpus_"):
            continue
        docs.extend(read_jsonl(p, Document))
        units_path = p.with_name(p.name.replace("_documents.jsonl", "_units.jsonl"))
        units.extend(read_jsonl(units_path, EvidenceUnit))

    tagged = [tag_topics(d, topics, exclude) for d in docs]
    kept = [d for d in tagged if d.source_type not in TOPIC_FILTERED or d.topics]
    held_ids = select_holdout(kept, holdout_counts, seed)

    corpus = sorted((d for d in kept if d.doc_id not in held_ids), key=lambda d: d.doc_id)
    heldout = sorted((d for d in kept if d.doc_id in held_ids), key=lambda d: d.doc_id)
    corpus_ids = {d.doc_id for d in corpus}
    corpus_units = sorted((u for u in units if u.doc_id in corpus_ids), key=lambda u: (u.doc_id, u.start))

    out = CorpusBuild(
        corpus_documents=processed_dir / "corpus_documents.jsonl",
        corpus_units=processed_dir / "corpus_units.jsonl",
        heldout=Path(heldout_path),
        manifest=Path(manifest_path),
    )
    counts = {
        "corpus_documents.jsonl": write_jsonl(out.corpus_documents, corpus),
        "corpus_units.jsonl": write_jsonl(out.corpus_units, corpus_units),
        "eval_sources.jsonl": write_jsonl(out.heldout, heldout),
    }
    paths = {
        "corpus_documents.jsonl": out.corpus_documents,
        "corpus_units.jsonl": out.corpus_units,
        "eval_sources.jsonl": out.heldout,
    }
    by_topic: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    for d in corpus:
        by_source[d.source_type] += 1
        for t in d.topics:
            by_topic[t] += 1
    manifest = {
        "base_date": base_date.isoformat(),
        "created_at": datetime.now(UTC).isoformat(),
        "files": {name: {"count": counts[name], "sha256": _sha256(paths[name])} for name in paths},
        "corpus_by_source": dict(sorted(by_source.items())),
        "corpus_by_topic": dict(sorted(by_topic.items())),
        "heldout_by_topic": dict(sorted(_first_topic_counts(heldout).items())),
    }
    out.manifest.parent.mkdir(parents=True, exist_ok=True)
    out.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                            newline="\n")
    return out


def _first_topic_counts(docs: list[Document]) -> dict[str, int]:
    c: dict[str, int] = defaultdict(int)
    for d in docs:
        c[d.topics[0] if d.topics else ""] += 1
    return c


class UnitIndex:
    """unit_id로 근거 단위와 그 원문 조각을 찾는다."""

    def __init__(self, documents: list[Document], units: list[EvidenceUnit]):
        self._docs = {d.doc_id: d for d in documents}
        self._units = {u.unit_id: u for u in units}
        self._by_doc: dict[str, list[EvidenceUnit]] = defaultdict(list)
        for u in sorted(units, key=lambda u: u.start):
            self._by_doc[u.doc_id].append(u)

    @classmethod
    def from_files(cls, docs_path: Path, units_path: Path) -> UnitIndex:
        return cls(read_jsonl(docs_path, Document), read_jsonl(units_path, EvidenceUnit))

    def __contains__(self, unit_id: object) -> bool:
        return unit_id in self._units

    def get(self, unit_id: str) -> EvidenceUnit:
        return self._units[unit_id]

    def text(self, unit_id: str) -> str:
        u = self._units[unit_id]
        return self._docs[u.doc_id].text[u.start : u.end]

    def units_of(self, doc_id: str) -> list[EvidenceUnit]:
        return list(self._by_doc.get(doc_id, []))

    def document(self, doc_id: str) -> Document:
        return self._docs[doc_id]

    def all_units(self) -> list[EvidenceUnit]:
        return list(self._units.values())
