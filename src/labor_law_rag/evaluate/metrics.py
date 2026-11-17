"""검색 지표: recall@k, all-hit@k, MRR@10, 부트스트랩 신뢰구간."""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from pydantic import BaseModel

from labor_law_rag.corpus import UnitIndex
from labor_law_rag.models import EvalItem, RetrievedChunk
from labor_law_rag.spans import covers

KS = (1, 5, 10)
MRR_CUTOFF = 10


class MetricValue(BaseModel):
    mean: float
    ci_low: float
    ci_high: float


class RunScores(BaseModel):
    overall: dict[str, MetricValue]
    by_qtype: dict[str, dict[str, MetricValue]]
    n_by_qtype: dict[str, int]
    n_items: int
    missing_qids: list[str]
    avg_chunk_chars: float


def item_scores(
    item: EvalItem, chunks: list[RetrievedChunk], index: UnitIndex, ks: tuple[int, ...] = KS
) -> dict[str, float]:
    units = [index.get(uid) for uid in item.evidence]
    # 청크 순위별로 덮은 정답 단위 집합
    hits_at = [{u.unit_id for u in units if covers(c, u)} for c in chunks]
    scores: dict[str, float] = {}
    for k in ks:
        found = set().union(*hits_at[:k]) if hits_at[:k] else set()
        scores[f"recall@{k}"] = len(found) / len(units)
        scores[f"all_hit@{k}"] = 1.0 if len(found) == len(units) else 0.0
    scores["mrr"] = 0.0
    for rank, hits in enumerate(hits_at[:MRR_CUTOFF], start=1):
        if hits:
            scores["mrr"] = 1.0 / rank
            break
    return scores


def bootstrap_ci(
    values: list[float], *, n_boot: int = 1000, seed: int = 0, alpha: float = 0.05
) -> tuple[float, float]:
    """문항 단위로 복원 추출한 평균의 (alpha/2, 1-alpha/2) 분위수."""
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    means = arr[rng.integers(0, arr.size, size=(n_boot, arr.size))].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return (float(lo), float(hi))


def _metric(values: list[float], n_boot: int, seed: int) -> MetricValue:
    lo, hi = bootstrap_ci(values, n_boot=n_boot, seed=seed)
    return MetricValue(mean=float(np.mean(values)) if values else 0.0, ci_low=lo, ci_high=hi)


def paired_bootstrap_diff(
    a: dict[str, float], b: dict[str, float], *, n_boot: int = 1000, seed: int = 0
) -> MetricValue:
    """같은 qid끼리 짝지은 b - a 의 평균과 신뢰구간 (설계 5.5)."""
    if set(a) != set(b):
        raise ValueError("두 실험의 문항(qid) 집합이 다릅니다")
    qids = sorted(a)
    return _metric([b[q] - a[q] for q in qids], n_boot, seed)


def score_run(
    items: list[EvalItem],
    run: dict[str, list[RetrievedChunk]],
    index: UnitIndex,
    *,
    n_boot: int = 1000,
    seed: int = 0,
) -> RunScores:
    scored = [it for it in items if it.qtype != "no_answer"]
    per_item: list[tuple[EvalItem, dict[str, float]]] = []
    missing: list[str] = []
    distinct: set[tuple[str, int, int]] = set()
    for it in scored:
        chunks = run.get(it.qid)
        if chunks is None:
            missing.append(it.qid)
            chunks = []
        distinct.update((c.doc_id, c.start, c.end) for c in chunks[:MRR_CUTOFF])
        per_item.append((it, item_scores(it, chunks, index)))

    names = list(per_item[0][1]) if per_item else []
    overall = {m: _metric([s[m] for _, s in per_item], n_boot, seed) for m in names}
    groups: dict[str, list[dict[str, float]]] = defaultdict(list)
    for it, s in per_item:
        groups[it.qtype].append(s)
    by_qtype = {q: {m: _metric([s[m] for s in g], n_boot, seed) for m in names} for q, g in sorted(groups.items())}
    avg = float(np.mean([e - s for _, s, e in distinct])) if distinct else 0.0
    return RunScores(
        overall=overall, by_qtype=by_qtype, n_by_qtype={q: len(g) for q, g in sorted(groups.items())},
        n_items=len(per_item), missing_qids=missing, avg_chunk_chars=avg,
    )


def per_item_rows(items: list[EvalItem], run: dict[str, list[RetrievedChunk]], index: UnitIndex) -> list[dict]:
    rows = []
    for it in items:
        if it.qtype == "no_answer":
            continue
        rows.append({"qid": it.qid, "qtype": it.qtype, **item_scores(it, run.get(it.qid, []), index)})
    return rows
