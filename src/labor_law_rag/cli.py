"""명령줄 도구 `llr`."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from labor_law_rag.config import load_corpus_config, load_topics

app = typer.Typer(help="labor-law-rag: 말뭉치 수집 · 평가 세트 · 평가 도구", no_args_is_help=True)

DATA = Path("data")
PROCESSED = DATA / "processed"
HELDOUT = DATA / "heldout" / "eval_sources.jsonl"
MANIFEST = DATA / "manifest.json"
DRAFTS = DATA / "eval" / "drafts.jsonl"
DRAFT_MODEL = "qwen3:8b"  # 채점(계획 2)과 다른 모델로 문항 초안을 만든다

draft_app = typer.Typer(help="평가 문항 초안 생성", no_args_is_help=True)
app.add_typer(draft_app, name="draft")


def _corpus_index():
    from labor_law_rag.corpus import UnitIndex

    return UnitIndex.from_files(PROCESSED / "corpus_documents.jsonl", PROCESSED / "corpus_units.jsonl")


def _llm():
    from labor_law_rag.config import load_settings
    from labor_law_rag.llm import OllamaClient

    return OllamaClient(load_settings().ollama_url)


def _report_drafts() -> None:
    from collections import Counter

    from labor_law_rag.io import read_jsonl

    c = Counter(d["qtype"] for d in read_jsonl(DRAFTS))
    typer.echo(f"초안 {sum(c.values())}개: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))


@draft_app.command("law")
def draft_law(n: int = 120, model: str = DRAFT_MODEL, seed: int | None = None) -> None:
    """조문 단위에서 LLM으로 질문 초안을 만든다."""
    from labor_law_rag.evalset.draft import append_drafts, draft_from_units

    items = draft_from_units(_llm(), _corpus_index(), model=model, n=n,
                             seed=load_corpus_config().seed if seed is None else seed)
    typer.echo(f"생성 {len(items)}개, 추가 {append_drafts(DRAFTS, items)}개")
    _report_drafts()


@draft_app.command("heldout")
def draft_heldout(model: str = DRAFT_MODEL) -> None:
    """떼어 둔 법령해석의 질의를 구어체 질문 초안으로 다듬는다."""
    from labor_law_rag.evalset.draft import append_drafts, draft_from_heldout
    from labor_law_rag.io import read_jsonl
    from labor_law_rag.models import Document

    items = draft_from_heldout(_llm(), read_jsonl(HELDOUT, Document), _corpus_index(), model=model)
    typer.echo(f"생성 {len(items)}개, 추가 {append_drafts(DRAFTS, items)}개")
    _report_drafts()


@app.command("import-drafts")
def import_drafts_cmd(path: Path, origin: str = typer.Option(..., help="manual 또는 claude_code_draft")) -> None:
    """직접 쓰거나 Claude Code로 쓴 문항 JSONL을 초안에 추가한다."""
    from labor_law_rag.evalset.draft import append_drafts, import_drafts

    if origin not in ("manual", "claude_code_draft"):
        raise typer.BadParameter("origin은 manual 또는 claude_code_draft")
    items = import_drafts(path, origin=origin)
    typer.echo(f"읽음 {len(items)}개, 추가 {append_drafts(DRAFTS, items)}개")
    _report_drafts()


@app.callback()
def main() -> None:
    """labor-law-rag 명령 모음."""


@app.command("build-corpus")
def build_corpus_cmd(force: bool = typer.Option(False, help="떼어 둔 원문이 이미 있어도 다시 만든다")) -> None:
    """주제 필터 → 평가용 원문 떼기 → 검색 말뭉치와 manifest 생성."""
    from labor_law_rag.corpus import build_corpus

    cfg = load_corpus_config()
    build = build_corpus(
        processed_dir=PROCESSED, heldout_path=HELDOUT, manifest_path=MANIFEST, topics=load_topics(),
        holdout_counts=cfg.holdout, seed=cfg.seed, base_date=cfg.base_date, force=force,
    )
    m = json.loads(build.manifest.read_text(encoding="utf-8"))
    typer.echo(json.dumps({k: m[k] for k in ("files", "corpus_by_source", "heldout_by_topic")},
                          ensure_ascii=False, indent=2))
