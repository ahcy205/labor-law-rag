# labor-law-rag

한국 근로 제도(근로기준법 · 최저임금법 · 근로자퇴직급여 보장법 · 고용보험법 육아휴직 급여 등)에 관한 질문에 근거 조문 · 법령해석을 찾아 답하는 RAG 실험 프로젝트입니다. 평가 도구와 실험이 본체입니다. 설계는 `docs/superpowers/specs/2026-11-17-labor-law-rag-design.md`, 판단 기록은 `docs/decisions.md`에 있습니다.

> 이 README는 1주차(데이터 · 평가 세트 · 평가 도구) 재현 절차 초안입니다. 실험 결과와 보고서는 4주차에 채웁니다.

## 1주차 산출물

- 기준일 **2026-11-17** 말뭉치: 문서 1,581개(법률 5, 시행령 4, 별표 12, 최저임금 고시 1, 고용노동부 법령해석 1,559), 근거 단위 2,696개. 파일 해시는 `data/manifest.json`에 있습니다.
- 평가 세트 `data/eval/evalset.jsonl`: 186문항(dev 111 · test 75). 유형별 수는 `llr finalize` 출력과 `docs/decisions.md`에 있습니다.
- 평가 도구: recall@5 · all-hit@5 · MRR@10과 부트스트랩 95% 신뢰구간. oracle 실행은 1.0, random 실행은 0.0이 나옵니다(`results/sanity-*`).

## 환경 준비

1. [uv](https://docs.astral.sh/uv/)를 설치하고 의존성을 받습니다. Python 3.12를 씁니다.
   ```sh
   uv sync
   ```
2. `.env.example`을 `.env`로 복사하고 값을 채웁니다. `.env`는 커밋하지 않습니다.
   - `LAW_OC`: [국가법령정보 공동활용](https://open.law.go.kr)에서 OPEN API(법령, 행정규칙, 법령 별표 · 서식, 고용노동부 법령해석)를 신청하고 IP를 등록한 뒤 받는 아이디(가입 이메일의 @ 앞부분)입니다.
   - `OLLAMA_URL`: 기본값 `http://localhost:11434`.
3. 문항 초안을 다시 만들 때만 [Ollama](https://ollama.com)와 모델이 필요합니다.
   ```sh
   ollama pull qwen3:8b
   ```

Windows 콘솔에서 한글이 깨지면 `PYTHONUTF8=1`을 설정하고 실행합니다.

## 재현 명령

### 1. 수집과 말뭉치 (`data/raw/` 캐시가 있으면 네트워크 없이 같은 결과)

```sh
uv run llr collect laws             # 법률 · 시행령 · 최저임금 고시(첨부 PDF)
uv run llr collect annexes          # 별표
uv run llr collect interpretations  # 고용노동부 법령해석 (주제어로 거름, 요청 간격 1초)
uv run llr build-corpus --force     # 주제 필터 → 평가용 원문 40건 떼기 → 근접 중복 제외 → manifest
```

캐시로 처음부터 다시 만들면 `data/processed/`, `data/heldout/`의 모든 파일이 바이트 단위로 같고, `data/manifest.json`은 `created_at`만 다릅니다(2026-11-18 확인).

### 2. 평가 세트 (이미 확정되어 있으므로 다시 할 필요는 없음)

```sh
uv run llr draft law --n 50 --qtype fact      # 조문 기반 초안 (conditional, calculation도 같은 방식)
uv run llr draft heldout                      # 떼어 둔 법령해석 기반 초안
uv run llr import-drafts PATH --origin claude_code_draft
uv run llr review --port 7861                 # Gradio 검수 화면 (결정은 data/eval/review_log.jsonl에 추가만 됨)
uv run llr reopen-stale                       # 말뭉치를 다시 만든 뒤 근거가 사라진 문항을 다시 검수 대기로
uv run llr finalize                           # 검수 로그 적용 → dev/test 6:4 분할 (이미 있으면 --force와 판단 기록 필요)
```

### 3. 평가

```sh
uv run llr sanity-run --kind oracle   # results/sanity/run_oracle_dev.jsonl
uv run llr sanity-run --kind random
uv run llr evaluate --run results/sanity/run_oracle_dev.jsonl --experiment sanity-oracle
```

검색 실행 결과 파일은 한 줄에 `{"qid": ..., "chunks": [{"doc_id", "start", "end", "score"}]}`이고, 목록 순서가 곧 순위입니다 형식입니다. 근거 단위와 같은 문서에서 `겹침 / min(근거 길이, 청크 길이) >= 0.5`이면 찾은 것으로 칩니다. test 세트는 `--split test --final`로만 채점되고, 그때마다 `results/test_log.jsonl`에 기록됩니다.

### 테스트

```sh
uv run pytest -q
uv run ruff check src tests
```

## 데이터 출처와 이용 조건

- **법령 · 시행령 · 별표 · 최저임금 고시:** 법제처 국가법령정보센터 OPEN API(`law.go.kr/DRF`). 법령과 고시는 저작권법 제7조에 따라 보호받지 않는 저작물입니다.
- **고용노동부 법령해석:** 국가법령정보센터 OPEN API(`target=moelCgmExpc`)로 받았습니다. 이 저작물은 **공공누리 제1유형(출처표시)** 조건에 따라 고용노동부의 공공저작물을 이용하였으며, 해당 저작물은 국가법령정보센터(https://www.law.go.kr)에서 무료로 받을 수 있습니다.
- 원문 캐시(`data/raw/`)와 가공 파일(`data/processed/`, `data/heldout/`)은 저장소에 넣지 않습니다. 위 명령으로 다시 만들 수 있습니다.

## 알려진 한계 (1주차 기준)

- 평가 세트는 사용자가 모든 문항을 저장했지만, 195문항은 Claude의 1차 판정과 수정안을 보고 결정했습니다(판단이 194/195문항에서 같음). 근접 중복 제외로 다시 연 10문항 중 9문항은 사용자가 승인한 Claude 제안을 그대로 저장했습니다.
- 유형 비율이 설계와 다릅니다. 계산 3.8%, 문서 간 연결 6.5%, 답 없음 25%입니다. 계산 · 문서 간 연결은 표본이 작아 유형별 수치로 결론을 내지 않습니다.
- 기준일에는 "2026년 적용 최저임금 고시"만 시행 중이어서 2027년 최저임금은 말뭉치에 없습니다.
- 말뭉치 안에서 서로 중복인 법령해석은 남아 있습니다. 같은 doc_id만 정답으로 치므로, 중복 문서를 찾아도 놓친 것으로 채점됩니다.
