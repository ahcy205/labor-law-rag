"""JSONL 입출력. Windows 기본 인코딩(cp949)을 피하려고 항상 utf-8을 쓴다."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar, overload

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def _to_dict(row: BaseModel | dict) -> dict:
    return row.model_dump(mode="json") if isinstance(row, BaseModel) else row


def _dumps(row: BaseModel | dict) -> str:
    return json.dumps(_to_dict(row), ensure_ascii=False)


@overload
def read_jsonl(path: Path, model: None = None) -> list[dict]: ...
@overload
def read_jsonl(path: Path, model: type[T]) -> list[T]: ...
def read_jsonl(path, model=None):
    rows = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            rows.append(model.model_validate(data) if model else data)
    return rows


def write_jsonl(path: Path, rows: Iterable[BaseModel | dict]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(_dumps(row) + "\n")
            n += 1
    return n


def append_jsonl(path: Path, row: BaseModel | dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(_dumps(row) + "\n")
