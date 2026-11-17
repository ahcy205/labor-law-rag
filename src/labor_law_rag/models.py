"""데이터 모델: 검색 대상 원문, 정답 근거 단위, 평가 문항, 검색된 청크."""

from __future__ import annotations

from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SourceType = Literal["law", "decree", "notice", "annex", "interpretation"]
QType = Literal["fact", "conditional", "multi_doc", "calculation", "no_answer", "amendment"]
Origin = Literal["manual", "llm_draft", "claude_code_draft", "interpretation_adapted"]
NoAnswerKind = Literal["out_of_scope", "in_scope_missing"]
Split = Literal["dev", "test"]


class Document(BaseModel):
    doc_id: str
    source_type: SourceType
    title: str
    text: str
    date: Date | None
    url: str
    license: str
    topics: list[str] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


class EvidenceUnit(BaseModel):
    """정답 근거 단위. 원문 doc.text 안의 [start, end) 반열린 구간."""

    unit_id: str
    doc_id: str
    start: int = Field(ge=0)
    end: int

    @model_validator(mode="after")
    def _end_after_start(self):
        if self.end <= self.start:
            raise ValueError(f"{self.unit_id}: end({self.end})가 start({self.start})보다 커야 합니다")
        return self


class _ItemFields(BaseModel):
    qid: str
    question: str
    answer: str
    answer_numbers: list[float] = Field(default_factory=list)
    number_rel_tol: float = 0.01
    evidence: list[str] = Field(default_factory=list)
    qtype: QType
    origin: Origin
    origin_detail: str = ""
    no_answer_kind: NoAnswerKind | None = None
    split: Split | None = None
    notes: str = ""


class DraftItem(_ItemFields):
    """검수 전 문항 초안. 근거가 비어 있을 수 있어 검증이 느슨하다."""


class EvalItem(_ItemFields):
    """검수를 통과한 평가 문항. 답 없음 여부와 근거가 서로 맞아야 한다."""

    @model_validator(mode="after")
    def _evidence_matches_type(self):
        if self.qtype == "no_answer":
            if self.evidence:
                raise ValueError(f"{self.qid}: 답 없음 문항은 근거가 없어야 합니다")
            if self.no_answer_kind is None:
                raise ValueError(f"{self.qid}: 답 없음 문항은 no_answer_kind가 필요합니다")
        else:
            if not self.evidence:
                raise ValueError(f"{self.qid}: 답이 있는 문항은 근거가 1개 이상 필요합니다")
            if self.no_answer_kind is not None:
                raise ValueError(f"{self.qid}: 답이 있는 문항에는 no_answer_kind를 쓰지 않습니다")
        return self


class RetrievedChunk(BaseModel):
    doc_id: str
    start: int
    end: int
    score: float
