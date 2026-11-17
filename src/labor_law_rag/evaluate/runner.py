"""평가 실행: 결과 저장, test 잠금(설계 4.4), sanity run."""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from labor_law_rag.corpus import UnitIndex
from labor_law_rag.evalset.split import load_evalset
from labor_law_rag.evaluate.metrics import per_item_rows, score_run
from labor_law_rag.io import append_jsonl, read_jsonl, write_jsonl
from labor_law_rag.models import EvalItem, RetrievedChunk

DATA = Path("data")


class SplitLockedError(Exception):
    pass


class RunRow(BaseModel):
    qid: str
    chunks: list[RetrievedChunk]


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def evaluate(
    run_path: Path,
    *,
    experiment: str,
    split: Literal["dev", "test"],
    final: bool = False,
    evalset_path: Path = DATA / "eval" / "evalset.jsonl",
    results_dir: Path = Path("results"),
    docs_path: Path = DATA / "processed" / "corpus_documents.jsonl",
    units_path: Path = DATA / "processed" / "corpus_units.jsonl",
    manifest_path: Path = DATA / "manifest.json",
) -> Path:
    if split == "test" and not final:
        raise SplitLockedError(
            "테스트 세트는 잠겨 있습니다. 실험의 최종 설정을 확정한 뒤 --final로만 측정합니다(설계 4.4)"
        )
    items = load_evalset(evalset_path, split)
    index = UnitIndex.from_files(docs_path, units_path)
    run = {r.qid: r.chunks for r in read_jsonl(run_path, RunRow)}
    scores = score_run(items, run, index)

    now = datetime.now().astimezone()
    out = Path(results_dir) / experiment / f"{now:%Y%m%d-%H%M%S}-{split}"
    out.mkdir(parents=True, exist_ok=False)
    (out / "metrics.json").write_text(scores.model_dump_json(indent=2) + "\n", encoding="utf-8")
    write_jsonl(out / "per_item.jsonl", per_item_rows(items, run, index))
    commit = _git("rev-parse", "HEAD")
    meta = {
        "experiment": experiment,
        "git_commit": commit,
        "git_dirty": bool(_git("status", "--porcelain")),
        "ts": now.isoformat(),
        "split": split,
        "final": final,
        "evalset_sha256": _sha256(evalset_path),
        "corpus_manifest_sha256": _sha256(manifest_path) if Path(manifest_path).exists() else "",
        "run_path": str(run_path),
        "run_sha256": _sha256(run_path),
    }
    (out / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if split == "test":
        append_jsonl(Path(results_dir) / "test_log.jsonl",
                     {"experiment": experiment, "run_path": str(run_path), "ts": meta["ts"], "git_commit": commit})
    return out


def make_sanity_run(
    kind: Literal["oracle", "random"], items: list[EvalItem], index: UnitIndex, *, seed: int
) -> list[RunRow]:
    """평가 도구 점검용. oracle은 정답 단위 범위를 그대로 청크로, random은 아무 단위 10개."""
    rng = random.Random(seed)
    all_units = sorted(index.all_units(), key=lambda u: u.unit_id)
    rows = []
    for it in items:
        if kind == "oracle":
            units = [index.get(uid) for uid in it.evidence]
        else:
            units = rng.sample(all_units, min(10, len(all_units)))
        chunks = [RetrievedChunk(doc_id=u.doc_id, start=u.start, end=u.end, score=1.0 - i / 100)
                  for i, u in enumerate(units)]
        rows.append(RunRow(qid=it.qid, chunks=chunks))
    return rows
