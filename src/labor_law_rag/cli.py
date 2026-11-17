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
