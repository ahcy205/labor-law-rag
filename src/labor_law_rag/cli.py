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

RAW = DATA / "raw"

draft_app = typer.Typer(help="평가 문항 초안 생성", no_args_is_help=True)
app.add_typer(draft_app, name="draft")
collect_app = typer.Typer(help="원본 수집과 정규화", no_args_is_help=True)
app.add_typer(collect_app, name="collect")


def _law_fetcher():
    from labor_law_rag.config import load_settings, require
    from labor_law_rag.fetch import CachedFetcher

    return CachedFetcher(RAW), require(load_settings(), "law_oc")


@collect_app.command("laws")
def collect_laws() -> None:
    """기준일에 시행 중인 법령 · 시행령 본문을 받아 조 · 항 단위로 정규화한다."""
    from labor_law_rag.collect.law import collect_law
    from labor_law_rag.io import write_jsonl
    from labor_law_rag.normalize.law_xml import parse_law

    cfg = load_corpus_config()
    fetcher, oc = _law_fetcher()
    docs, units = [], []
    for spec in cfg.laws:
        if spec.kind not in ("law", "decree"):
            continue
        path = collect_law(fetcher, oc, spec, cfg.base_date)
        doc, us = parse_law(path.read_bytes(), source_type=spec.kind,
                            url=f"https://www.law.go.kr/법령/{spec.name.replace(' ', '')}")
        docs.append(doc)
        units.extend(us)
        typer.echo(f"{doc.title}: 시행 {doc.date}, 근거 단위 {len(us)}개, {len(doc.text):,}자")
    write_jsonl(PROCESSED / "law_documents.jsonl", docs)
    write_jsonl(PROCESSED / "law_units.jsonl", units)


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


REVIEW_LOG = DATA / "eval" / "review_log.jsonl"


@app.command("review")
def review_cmd(
    port: int = 7861,
    drafts: Path = DRAFTS,
    log: Path = REVIEW_LOG,
    docs: Path = PROCESSED / "corpus_documents.jsonl",
    units: Path = PROCESSED / "corpus_units.jsonl",
    heldout: Path = HELDOUT,
) -> None:
    """Gradio 검수 화면을 띄운다. 결정은 review_log.jsonl에 한 줄씩 쌓인다."""
    from labor_law_rag.corpus import UnitIndex
    from labor_law_rag.evalset.review_app import build_app
    from labor_law_rag.evalset.review_store import ReviewStore
    from labor_law_rag.io import read_jsonl
    from labor_law_rag.models import Document

    index = UnitIndex.from_files(docs, units)
    held = {d.doc_id: d for d in read_jsonl(heldout, Document)} if heldout.exists() else {}
    store = ReviewStore(drafts, log, index, heldout_ids=set(held))
    build_app(store, index, held).launch(server_name="127.0.0.1", server_port=port)


EVALSET = DATA / "eval" / "evalset.jsonl"


@app.command("finalize")
def finalize_cmd(force: bool = typer.Option(False, help="이미 있는 평가 세트를 덮어쓴다(판단 기록 필요)")) -> None:
    """검수 로그를 적용해 평가 세트를 확정하고 dev/test 6:4로 나눈다."""
    from labor_law_rag.corpus import UnitIndex
    from labor_law_rag.evalset.review_store import ReviewStore
    from labor_law_rag.evalset.split import finalize, load_evalset, split_table
    from labor_law_rag.io import read_jsonl
    from labor_law_rag.models import Document

    index = UnitIndex.from_files(PROCESSED / "corpus_documents.jsonl", PROCESSED / "corpus_units.jsonl")
    held = {d.doc_id for d in read_jsonl(HELDOUT, Document)} if HELDOUT.exists() else set()
    store = ReviewStore(DRAFTS, REVIEW_LOG, index, heldout_ids=held)
    done, total = store.progress()
    if done < total:
        typer.echo(f"경고: 검수하지 않은 초안이 {total - done}개 있습니다(검수 {done}/{total}).")
    if force:
        typer.echo("경고: 평가 세트를 다시 나눕니다. docs/decisions.md에 이유를 남기세요.")
    out = finalize(store, EVALSET, seed=load_corpus_config().seed, force=force)
    typer.echo(split_table(load_evalset(out, "all")))


def _fmt(v) -> str:
    return f"{v.mean:.3f} [{v.ci_low:.3f}, {v.ci_high:.3f}]"


@app.command("evaluate")
def evaluate_cmd(
    run: Path = typer.Option(..., help="실행 결과 JSONL ({qid, chunks})"),
    experiment: str = typer.Option(..., help="실험 이름 (예: E0)"),
    split: str = typer.Option("dev", help="dev 또는 test"),
    final: bool = typer.Option(False, help="테스트 세트 최종 측정 (설계 4.4)"),
) -> None:
    """검색 실행 결과를 평가 세트로 채점하고 results/에 남긴다."""
    from labor_law_rag.evaluate.metrics import RunScores
    from labor_law_rag.evaluate.runner import SplitLockedError, evaluate

    if split not in ("dev", "test"):
        raise typer.BadParameter("split은 dev 또는 test")
    try:
        out = evaluate(run, experiment=experiment, split=split, final=final)
    except SplitLockedError as e:
        typer.echo(str(e))
        raise typer.Exit(2) from e
    s = RunScores.model_validate_json((out / "metrics.json").read_text(encoding="utf-8"))
    typer.echo(f"결과: {out}  (문항 {s.n_items}, 평균 청크 길이 {s.avg_chunk_chars:.0f}자)")
    if s.missing_qids:
        typer.echo(f"경고: 결과 파일에 없는 문항 {len(s.missing_qids)}개는 0점으로 계산했습니다")
    typer.echo("구분 | n | recall@5 [95% CI] | all-hit@5 [95% CI] | MRR@10 [95% CI]")
    typer.echo(f"전체 | {s.n_items} | {_fmt(s.overall['recall@5'])} | {_fmt(s.overall['all_hit@5'])} | "
               f"{_fmt(s.overall['mrr'])}")
    for q, m in s.by_qtype.items():
        typer.echo(f"{q} | {s.n_by_qtype[q]} | {_fmt(m['recall@5'])} | {_fmt(m['all_hit@5'])} | {_fmt(m['mrr'])}")


@app.command("sanity-run")
def sanity_run_cmd(
    kind: str = typer.Option(..., help="oracle 또는 random"),
    split: str = "dev",
    out: Path | None = None,
) -> None:
    """평가 도구 점검용 실행 결과를 만든다. oracle은 만점, random은 0에 가까워야 한다."""
    from labor_law_rag.corpus import UnitIndex
    from labor_law_rag.evalset.split import load_evalset
    from labor_law_rag.evaluate.runner import make_sanity_run
    from labor_law_rag.io import write_jsonl

    if kind not in ("oracle", "random"):
        raise typer.BadParameter("kind는 oracle 또는 random")
    index = UnitIndex.from_files(PROCESSED / "corpus_documents.jsonl", PROCESSED / "corpus_units.jsonl")
    rows = make_sanity_run(kind, load_evalset(EVALSET, split), index, seed=load_corpus_config().seed)
    out = out or Path("results") / "sanity" / f"run_{kind}_{split}.jsonl"
    write_jsonl(out, rows)
    typer.echo(f"{out} ({len(rows)}문항)")


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
