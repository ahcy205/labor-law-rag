"""검수 결과 확정과 dev/test 분할 (설계 4.4)."""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal, Protocol

from labor_law_rag.io import read_jsonl, write_jsonl
from labor_law_rag.models import EvalItem


class _HasCurrent(Protocol):
    def current(self) -> dict[str, EvalItem]: ...


def _stratum(item: EvalItem) -> str:
    return f"no_answer/{item.no_answer_kind}" if item.qtype == "no_answer" else item.qtype


def assign_splits(items: list[EvalItem], *, dev_ratio: float = 0.6, seed: int) -> list[EvalItem]:
    """층(유형, 답 없음은 종류까지)마다 반올림한 dev_ratio만큼 dev로 보낸다. 입력 순서와 무관하다."""
    rng = random.Random(seed)
    strata: dict[str, list[EvalItem]] = defaultdict(list)
    for it in items:
        strata[_stratum(it)].append(it)
    split_of: dict[str, str] = {}
    for name in sorted(strata):
        group = sorted(strata[name], key=lambda i: i.qid)
        rng.shuffle(group)
        n_dev = int(len(group) * dev_ratio + 0.5)  # 0.5는 올림(파이썬 round는 짝수 쪽으로 반올림)
        for k, it in enumerate(group):
            split_of[it.qid] = "dev" if k < n_dev else "test"
    return [it.model_copy(update={"split": split_of[it.qid]}) for it in items]


def split_table(items: list[EvalItem]) -> str:
    c = Counter((_stratum(i), i.split) for i in items)
    rows = ["유형 | dev | test | 합계", "---|---|---|---"]
    for name in sorted({s for s, _ in c}):
        d, t = c[(name, "dev")], c[(name, "test")]
        rows.append(f"{name} | {d} | {t} | {d + t}")
    d, t = sum(v for (_, s), v in c.items() if s == "dev"), sum(v for (_, s), v in c.items() if s == "test")
    rows.append(f"합계 | {d} | {t} | {d + t}")
    return "\n".join(rows)


def finalize(
    store: _HasCurrent, out_path: Path = Path("data/eval/evalset.jsonl"), *, seed: int, force: bool = False
) -> Path:
    out_path = Path(out_path)
    if out_path.exists() and not force:
        raise FileExistsError(f"{out_path}가 이미 있습니다. 분할을 다시 하면 docs/decisions.md에 이유를 남기고 --force")
    items = sorted(store.current().values(), key=lambda i: i.qid)
    if out_path.exists():
        # 다시 확정할 때는 이미 나눈 문항의 분할을 그대로 둔다. dev로 조정에 쓴 문항이 test로 넘어가면
        # test 잠금(설계 4.4)이 깨진다. 새 문항만 층마다 dev_ratio에 가깝게 채운다.
        prev = {i.qid: i.split for i in read_jsonl(out_path, EvalItem) if i.split}
        items = _top_up(items, prev, seed=seed)
    else:
        items = assign_splits(items, seed=seed)
    write_jsonl(out_path, items)
    return out_path


def _top_up(items: list[EvalItem], prev: dict[str, str], *, seed: int, dev_ratio: float = 0.6) -> list[EvalItem]:
    split_of = {i.qid: prev[i.qid] for i in items if i.qid in prev}
    strata: dict[str, list[EvalItem]] = defaultdict(list)
    for it in items:
        strata[_stratum(it)].append(it)
    for name in sorted(strata):
        group = strata[name]
        new = sorted((i for i in group if i.qid not in split_of), key=lambda i: i.qid)
        if not new:
            continue
        random.Random(f"{seed}:{name}").shuffle(new)
        have_dev = sum(split_of.get(i.qid) == "dev" for i in group)
        n_dev = min(max(int(len(group) * dev_ratio + 0.5) - have_dev, 0), len(new))
        for k, it in enumerate(new):
            split_of[it.qid] = "dev" if k < n_dev else "test"
    return [it.model_copy(update={"split": split_of[it.qid]}) for it in items]


def load_evalset(path: Path, split: Literal["dev", "test", "all"]) -> list[EvalItem]:
    items = read_jsonl(path, EvalItem)
    return items if split == "all" else [i for i in items if i.split == split]
