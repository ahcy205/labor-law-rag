"""평가 문항 초안 생성과 가져오기 (설계 4.3)."""

from __future__ import annotations

import hashlib
import logging
import random
import re
from collections import defaultdict
from importlib import resources
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from labor_law_rag.citations import extract_citations
from labor_law_rag.corpus import UnitIndex
from labor_law_rag.io import append_jsonl, read_jsonl
from labor_law_rag.llm import LLMClient, LLMOutputError, generate_json
from labor_law_rag.models import Document, DraftItem, Origin

log = logging.getLogger(__name__)

STATUTE_TYPES = {"law", "decree", "notice", "annex"}
_ORIGIN_ABBR = {
    "manual": "man",
    "llm_draft": "llm",
    "claude_code_draft": "cc",
    "interpretation_adapted": "interp",
}


class DraftOut(BaseModel):
    question: str
    answer: str
    answer_numbers: list[float]
    qtype: Literal["fact", "conditional", "calculation"]


def make_qid(origin: str, question: str) -> str:
    return f"{_ORIGIN_ABBR[origin]}-{hashlib.sha1(question.encode('utf-8')).hexdigest()[:8]}"


def _prompt(name: str) -> str:
    return resources.files("labor_law_rag.evalset").joinpath(f"prompts/{name}.txt").read_text(encoding="utf-8")


# 유형을 정해서 만들 때, 그 유형의 질문을 만들 수 있는 단위만 고른다.
_UNIT_FILTERS = {
    "calculation": re.compile(r"\d+\s*(?:일|원|시간|퍼센트|분의|개월|년|주|세)"),
    "conditional": re.compile(r"경우|이상|미만|이하|초과"),
}
_QTYPE_GUIDE = {
    "fact": "조문에 적힌 사실 하나를 묻는 질문",
    "conditional": "근무 기간 · 출근율 · 사업장 규모 같은 조건이 질문에 들어 있고, 그 조건에 따라 답이 정해지는 질문",
    "calculation": "구체적인 숫자(임금 · 기간 · 시간)를 주고 계산한 값을 묻는 질문. 답을 바꾸는 전제를 질문에 모두 적는다",
}


def _sample_units(index: UnitIndex, n: int, seed: int, pattern: re.Pattern | None = None) -> list[str]:
    """법령 · 시행령 · 고시 · 별표 단위를 주제별로 돌아가며 n개 고른다."""
    groups: dict[str, list[str]] = defaultdict(list)
    for u in sorted(index.all_units(), key=lambda u: u.unit_id):
        doc = index.document(u.doc_id)
        if doc.source_type in STATUTE_TYPES and (pattern is None or pattern.search(index.text(u.unit_id))):
            groups[doc.topics[0] if doc.topics else ""].append(u.unit_id)
    rng = random.Random(seed)
    for g in sorted(groups):
        rng.shuffle(groups[g])
    picked: list[str] = []
    while len(picked) < n and any(groups.values()):
        for g in sorted(groups):
            if groups[g] and len(picked) < n:
                picked.append(groups[g].pop())
    return picked


def draft_from_units(
    llm: LLMClient,
    index: UnitIndex,
    *,
    model: str,
    n: int,
    seed: int,
    qtype: Literal["fact", "conditional", "calculation"] | None = None,
) -> list[DraftItem]:
    """qtype을 주면 그 유형으로 만들 수 있는 단위만 고르고, 프롬프트로 유형을 강제한다."""
    template = _prompt("from_unit")
    target = ""
    if qtype:
        target = f"\n이번 질문의 qtype은 반드시 {qtype}입니다: {_QTYPE_GUIDE[qtype]}.\n"
    items: list[DraftItem] = []
    for unit_id in _sample_units(index, n, seed, _UNIT_FILTERS.get(qtype or "")):
        prompt = template.format(unit_id=unit_id, text=index.text(unit_id)) + target
        try:
            out = generate_json(llm, prompt, model=model, schema=DraftOut)
        except LLMOutputError as e:
            log.warning("초안 생성 실패 %s: %s", unit_id, e)
            continue
        items.append(DraftItem(
            qid=make_qid("llm_draft", out.question), question=out.question, answer=out.answer,
            answer_numbers=out.answer_numbers, qtype=qtype or out.qtype, evidence=[unit_id],
            origin="llm_draft", origin_detail=model,
        ))
    return items


def _law_names(index: UnitIndex) -> list[str]:
    return sorted({index.document(u.doc_id).title for u in index.all_units()
                   if index.document(u.doc_id).source_type in {"law", "decree"}})


def draft_from_heldout(
    llm: LLMClient, sources: list[Document], index: UnitIndex, *, model: str
) -> list[DraftItem]:
    template = _prompt("from_heldout")
    law_names = _law_names(index)
    items: list[DraftItem] = []
    for src in sources:
        try:
            out = generate_json(llm, template.format(text=src.text), model=model, schema=DraftOut)
        except LLMOutputError as e:
            log.warning("초안 생성 실패 %s: %s", src.doc_id, e)
            continue
        evidence = [u for u in extract_citations(src.text, law_names, index) if u != src.doc_id]
        items.append(DraftItem(
            qid=make_qid("interpretation_adapted", out.question), question=out.question, answer=out.answer,
            answer_numbers=out.answer_numbers,
            qtype="multi_doc" if len(evidence) >= 2 else out.qtype,
            evidence=evidence, origin="interpretation_adapted", origin_detail=src.doc_id,
            notes="" if evidence else "근거 미지정",
        ))
    return items


def import_drafts(path: Path, *, origin: Origin) -> list[DraftItem]:
    """직접 쓰거나 Claude Code로 쓴 문항 JSONL을 가져온다. qid · origin은 여기서 붙인다."""
    items = []
    for row in read_jsonl(path):
        row = {**row, "origin": origin, "qid": make_qid(origin, row["question"])}
        items.append(DraftItem.model_validate(row))
    return items


def append_drafts(drafts_path: Path, items: list[DraftItem]) -> int:
    """drafts.jsonl에 추가한다. 같은 qid(같은 질문)는 덮지 않고 건너뛴다. 추가한 수를 돌려준다."""
    existing = {d["qid"] for d in read_jsonl(drafts_path)} if Path(drafts_path).exists() else set()
    added = 0
    for it in items:
        if it.qid in existing:
            continue
        append_jsonl(drafts_path, it)
        existing.add(it.qid)
        added += 1
    return added
