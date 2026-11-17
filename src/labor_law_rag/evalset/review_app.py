"""Gradio 검수 화면 (설계 4.3). 한 번에 한 문항, 왼쪽은 편집, 오른쪽은 근거 원문."""

from __future__ import annotations

import re

import gradio as gr

from labor_law_rag.corpus import UnitIndex
from labor_law_rag.evalset.review_store import ReviewStore
from labor_law_rag.models import Document, DraftItem

QTYPES = ["fact", "conditional", "multi_doc", "calculation", "no_answer", "amendment"]
NO_KIND = "없음"
KINDS = [NO_KIND, "out_of_scope", "in_scope_missing"]


def form_to_item(
    base: DraftItem,
    question: str,
    answer: str,
    numbers_text: str,
    qtype: str,
    no_answer_kind: str,
    evidence_text: str,
    notes: str,
) -> DraftItem:
    numbers = []
    for tok in re.split(r"[,\s]+", numbers_text.strip()):
        if not tok:
            continue
        try:
            numbers.append(float(tok))
        except ValueError as e:
            raise ValueError(f"숫자로 읽을 수 없습니다: {tok!r}") from e
    evidence = [line.strip() for line in evidence_text.splitlines() if line.strip()]
    kind = None if no_answer_kind in ("", NO_KIND, None) else no_answer_kind
    return base.model_copy(update={
        "question": question.strip(), "answer": answer.strip(), "answer_numbers": numbers,
        "qtype": qtype, "no_answer_kind": kind, "evidence": evidence, "notes": notes.strip(),
    })


def evidence_panel(evidence: list[str], index: UnitIndex) -> str:
    if not evidence:
        return "_근거 없음_"
    parts = []
    for uid in evidence:
        if uid in index:
            parts.append(f"#### {uid}\n\n{index.text(uid)}")
        else:
            parts.append(f"#### {uid}\n\n**⚠ 말뭉치에 없음**")
    return "\n\n---\n\n".join(parts)


VERDICTS = {"approve": "승인", "edit": "수정", "to_no_answer": "답 없음으로 전환", "delete": "삭제"}
CONFIDENCE = {"high": "높음", "medium": "중간", "low": "낮음"}


def _cell(v) -> str:
    if isinstance(v, list):
        v = ", ".join(f"{x:g}" if isinstance(x, float) else str(x) for x in v)
    return ("" if v is None else str(v)).replace("|", "\\|").replace("\n", " ")


def opinion_panel(op: dict | None) -> str:
    """Claude 1차 검수 의견. 참고용이고 결정은 검수자가 한다."""
    if not op:
        return "#### Claude 의견\n\n_의견 없음_"
    head = f"#### Claude 의견: {VERDICTS.get(op['verdict'], op['verdict'])} (확신 {CONFIDENCE.get(op['confidence'], op['confidence'])})"
    parts = [head]
    if op.get("dup_leak"):
        parts.append("**⚠ 중복 원문 누출:** 떼어 둔 법령해석과 거의 같은 문서를 근거로 씀. 처리 방침 결정 전까지 보류 권장")
    parts.append(f"**이유:** {op['reason']}")
    if op.get("changes"):
        rows = ["| 항목 | 바꾸기 전 | 바꾼 후 | 이유 |", "|---|---|---|---|"]
        rows += [f"| {c['field']} | {_cell(c['before'])} | {_cell(c['after'])} | {_cell(c['why'])} |"
                 for c in op["changes"]]
        parts.append("\n".join(rows))
    if op.get("proposed"):
        parts.append("_'Claude 수정안 넣기'를 누르면 왼쪽 칸에 채워진다. 확인 후 저장._")
    return "\n\n".join(parts)


def proposal_to_form(p: dict) -> tuple[str, str, str, str, str, str, str]:
    nums = ", ".join(f"{x:g}" for x in p.get("answer_numbers") or [])
    return (p["question"], p["answer"], nums, p["qtype"], p.get("no_answer_kind") or NO_KIND,
            "\n".join(p.get("evidence") or []), p.get("notes") or "")


def _source_panel(item: DraftItem, heldout: dict[str, Document]) -> str:
    src = heldout.get(item.origin_detail)
    if src is None:
        return f"_출처: {item.origin} {item.origin_detail}_"
    return f"#### 떼어 둔 원문: {src.title} ({src.date})\n\n{src.text}"


def build_app(
    store: ReviewStore, index: UnitIndex, heldout: dict[str, Document], opinions: dict[str, dict] | None = None
) -> gr.Blocks:
    opinions = opinions or {}
    drafts = {d.qid: d for d in store.drafts}
    order = [d.qid for d in store.drafts]

    def next_qid(after: str | None) -> str | None:
        pending = {d.qid for d in store.pending()}
        if not pending:
            return None
        start = order.index(after) + 1 if after in order else 0
        for qid in order[start:] + order[:start]:
            if qid in pending:
                return qid
        return None

    def show(qid: str | None, message: str = ""):
        done, total = store.progress()
        prog = f"**진행 {done} / {total}**"
        if not qid:
            return ("", prog, "모든 초안을 검수했습니다.", "", "", "", QTYPES[0], NO_KIND, "", "", False,
                    message, "", "", "")
        d = drafts[qid]
        nums = ", ".join(f"{x:g}" for x in d.answer_numbers)
        return (
            qid, prog, f"`{qid}` · 출처 {d.origin} {d.origin_detail}", d.question, d.answer, nums, d.qtype,
            d.no_answer_kind or NO_KIND, "\n".join(d.evidence), d.notes, False, message,
            evidence_panel(d.evidence, index), _source_panel(d, heldout), opinion_panel(opinions.get(qid)),
        )

    with gr.Blocks(title="평가 문항 검수") as demo:
        # gr.State는 API로 넘길 수 없어서 숨긴 Textbox로 현재 문항 qid를 들고 있는다.
        qid_state = gr.Textbox(visible=False)
        progress = gr.Markdown()
        header = gr.Markdown()
        with gr.Row():
            with gr.Column(scale=1):
                question = gr.Textbox(label="질문", lines=2)
                answer = gr.Textbox(label="정답", lines=3)
                numbers = gr.Textbox(label="숫자 정답 (쉼표로 구분)")
                with gr.Row():
                    qtype = gr.Dropdown(QTYPES, label="유형")
                    kind = gr.Dropdown(KINDS, label="답 없음 종류")
                evidence = gr.Textbox(label="근거 ID (한 줄에 하나)", lines=4)
                notes = gr.Textbox(label="메모")
                derivable = gr.Checkbox(label="근거 단위만으로 정답을 끌어낼 수 있다")
                with gr.Row():
                    approve_btn = gr.Button("승인 / 수정 저장", variant="primary")
                    delete_btn = gr.Button("삭제", variant="stop")
                    skip_btn = gr.Button("건너뛰기")
                apply_btn = gr.Button("Claude 수정안 넣기")
                message = gr.Markdown()
            with gr.Column(scale=1):
                op_panel = gr.Markdown()
                ev_panel = gr.Markdown()
                src_panel = gr.Markdown()

        outputs = [qid_state, progress, header, question, answer, numbers, qtype, kind, evidence, notes,
                   derivable, message, ev_panel, src_panel, op_panel]
        form = [qid_state, question, answer, numbers, qtype, kind, evidence, notes, derivable]

        def on_save(qid, q, a, n, t, k, ev, nt, der):
            if not qid:
                return show(None)
            try:
                item = form_to_item(drafts[qid], q, a, n, t, k, ev, nt)
                action = "approve" if item == drafts[qid] else "edit"
                store.record(qid, action, item, derivable=der)
            except ValueError as e:
                done, total = store.progress()
                # 입력값은 그대로 두고 오류만 보여 준다.
                return (qid, f"**진행 {done} / {total}**", gr.update(), q, a, n, t, k, ev, nt, der,
                        f"⚠ 저장 거부: {e}", evidence_panel([x for x in ev.splitlines() if x.strip()], index),
                        gr.update(), gr.update())
            return show(next_qid(qid), f"저장: {qid} ({action})")

        def on_delete(qid):
            if not qid:
                return show(None)
            store.record(qid, "delete")
            return show(next_qid(qid), f"삭제: {qid}")

        def on_apply(qid):
            op = opinions.get(qid) if qid else None
            if not op or not op.get("proposed"):
                verdict = VERDICTS.get(op["verdict"], "") if op else ""
                note = f"Claude 의견이 '{verdict}'이라 넣을 수정안이 없습니다." if op else "Claude 의견이 없습니다."
                return (*[gr.update()] * 7, note)
            return (*proposal_to_form(op["proposed"]), "Claude 수정안을 넣었습니다. 확인 후 저장하세요.")

        apply_btn.click(on_apply, [qid_state], [question, answer, numbers, qtype, kind, evidence, notes, message],
                        api_name="apply_proposal")
        approve_btn.click(on_save, form, outputs, api_name="save")
        delete_btn.click(on_delete, [qid_state], outputs, api_name="delete")
        skip_btn.click(lambda qid: show(next_qid(qid)), [qid_state], outputs, api_name="skip")
        evidence.change(lambda ev: evidence_panel([x.strip() for x in ev.splitlines() if x.strip()], index),
                        [evidence], [ev_panel])
        demo.load(lambda: show(next_qid(None)), None, outputs)
    return demo
