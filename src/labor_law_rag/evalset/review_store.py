"""검수 로그. 결정은 한 줄씩 추가만 하고, 현재 상태는 로그를 처음부터 다시 적용해 만든다."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from labor_law_rag.corpus import UnitIndex
from labor_law_rag.io import append_jsonl, read_jsonl
from labor_law_rag.models import DraftItem, EvalItem

ReviewAction = Literal["approve", "edit", "delete"]


class ReviewStore:
    def __init__(self, drafts_path: Path, log_path: Path, index: UnitIndex, heldout_ids: set[str]):
        self.drafts_path = Path(drafts_path)
        self.log_path = Path(log_path)
        self.index = index
        self.heldout_ids = set(heldout_ids)
        self.drafts: list[DraftItem] = read_jsonl(self.drafts_path, DraftItem)
        self._draft_ids = {d.qid for d in self.drafts}

    def _log(self) -> list[dict]:
        return read_jsonl(self.log_path) if self.log_path.exists() else []

    def _last_rows(self) -> dict[str, dict]:
        return {row["qid"]: row for row in self._log()}

    def decided(self) -> set[str]:
        """마지막 줄이 reopen(다시 검수)이 아닌 문항."""
        return {q for q, row in self._last_rows().items() if row["action"] != "reopen"}

    def reopen(self, qid: str, reason: str) -> None:
        """결정한 문항을 다시 검수 대기로 돌린다(예: 근거 문서가 말뭉치에서 빠짐). 로그에 한 줄 추가한다."""
        if qid not in self.decided():
            raise ValueError(f"{qid}: 결정한 적이 없는 문항은 다시 열 수 없습니다")
        append_jsonl(self.log_path, {"qid": qid, "action": "reopen", "reason": reason,
                                     "ts": datetime.now(UTC).isoformat()})

    def reopen_reason(self, qid: str) -> str | None:
        row = self._last_rows().get(qid)
        return row["reason"] if row and row["action"] == "reopen" else None

    def latest(self, qid: str) -> DraftItem | None:
        """마지막으로 저장한 승인 · 수정 내용. 다시 연 문항을 그 내용에서 이어 검수하는 데 쓴다."""
        item = None
        for row in self._log():
            if row["qid"] == qid and row["action"] in ("approve", "edit"):
                item = row["item"]
        return DraftItem.model_validate({k: v for k, v in item.items() if k != "split"}) if item else None

    def stale(self) -> dict[str, list[str]]:
        """확정 상태 문항 중 근거 ID가 지금 말뭉치에 없는 것. 말뭉치를 다시 만든 뒤 확인한다."""
        out = {}
        for qid, it in self.current().items():
            missing = [u for u in it.evidence if u not in self.index]
            if missing:
                out[qid] = missing
        return out

    def pending(self) -> list[DraftItem]:
        done = self.decided()
        return [d for d in self.drafts if d.qid not in done]

    def _validate(self, qid: str, item: DraftItem | None, derivable: bool) -> EvalItem:
        if item is None:
            raise ValueError(f"{qid}: 승인 · 수정에는 문항 내용이 필요합니다")
        if item.qid != qid:
            raise ValueError(f"qid가 다릅니다: {qid} != {item.qid}")
        for uid in item.evidence:
            if uid in self.heldout_ids:
                raise ValueError(f"{uid}: 떼어 둔 원문은 근거로 쓸 수 없습니다")
            if uid not in self.index:
                raise ValueError(f"{uid}: 말뭉치에 없는 근거 ID입니다")
        try:
            evaluated = EvalItem.model_validate(item.model_dump())
        except ValidationError as e:
            raise ValueError(f"{qid}: 문항 형식 오류: {e.errors()[0]['msg']}") from e
        if evaluated.qtype != "no_answer" and not derivable:
            raise ValueError(f"{qid}: '근거 단위만으로 정답을 끌어낼 수 있다'를 확인해야 승인할 수 있습니다")
        return evaluated

    def record(
        self, qid: str, action: ReviewAction, item: DraftItem | None = None, *, derivable: bool = False
    ) -> None:
        if qid not in self._draft_ids:
            raise ValueError(f"{qid}: 초안에 없는 문항입니다")
        row: dict = {"qid": qid, "action": action, "ts": datetime.now(UTC).isoformat()}
        if action in ("approve", "edit"):
            row["item"] = self._validate(qid, item, derivable).model_dump(mode="json")
        elif action != "delete":
            raise ValueError(f"알 수 없는 결정: {action}")
        append_jsonl(self.log_path, row)

    def current(self) -> dict[str, EvalItem]:
        state: dict[str, EvalItem] = {}
        for row in self._log():
            if row["action"] in ("delete", "reopen"):
                state.pop(row["qid"], None)
            else:
                state[row["qid"]] = EvalItem.model_validate(row["item"])
        return state

    def progress(self) -> tuple[int, int]:
        return len(self.decided() & self._draft_ids), len(self.drafts)
