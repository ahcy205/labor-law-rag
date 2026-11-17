"""로컬 LLM(Ollama) 클라이언트와 JSON 검증 재시도 (설계 8절).

시스템 코드의 LLM 호출은 모두 이 모듈을 거친다. 테스트는 FakeLLM으로 바꿔 끼운다.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    def generate(
        self,
        prompt: str,
        *,
        model: str,
        system: str | None = None,
        json_schema: dict | None = None,
        temperature: float = 0.0,
    ) -> str: ...


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        client: httpx.Client | None = None,
        timeout_s: float = 300.0,
        max_tokens: int = 1024,
    ):
        # Windows에서 localhost는 IPv6를 먼저 시도해 요청마다 약 2초가 더 걸린다.
        self.base_url = base_url.rstrip("/").replace("//localhost", "//127.0.0.1")
        self.client = client or httpx.Client(timeout=timeout_s)
        # 상한이 없으면 qwen3가 JSON 문자열 값을 끝없이 이어 쓴다(2026-11-17 확인).
        self.max_tokens = max_tokens

    def generate(self, prompt, *, model, system=None, json_schema=None, temperature=0.0) -> str:
        body: dict = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_predict": self.max_tokens},
        }
        if system is not None:
            body["system"] = system
        if json_schema is not None:
            body["format"] = json_schema
        resp = self.client.post(f"{self.base_url}/api/generate", json=body)
        resp.raise_for_status()
        return resp.json()["response"]


class FakeLLM:
    """정해 둔 응답을 차례로 돌려주고, 받은 요청을 기록한다."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, prompt, *, model, system=None, json_schema=None, temperature=0.0) -> str:
        self.calls.append(
            {"prompt": prompt, "model": model, "system": system, "json_schema": json_schema,
             "temperature": temperature}
        )
        if not self._responses:
            raise RuntimeError("FakeLLM: 준비된 응답이 없습니다")
        return self._responses.pop(0)


class LLMOutputError(Exception):
    def __init__(self, message: str, raw: str):
        super().__init__(message)
        self.raw = raw


def generate_json(
    llm: LLMClient,
    prompt: str,
    *,
    model: str,
    schema: type[T],
    system: str | None = None,
    max_retries: int = 2,
) -> T:
    json_schema = schema.model_json_schema()
    current = prompt
    raw = ""
    for _ in range(1 + max_retries):
        raw = llm.generate(current, model=model, system=system, json_schema=json_schema)
        try:
            return schema.model_validate_json(raw)
        except ValidationError as e:
            current = (
                f"{prompt}\n\n이전 응답이 형식 오류로 거부됐습니다. 오류: {e.errors()[:3]}\n"
                f"이전 응답: {raw[:500]}\n지정한 JSON 형식으로만 다시 답하세요."
            )
    raise LLMOutputError(f"{model}: {1 + max_retries}회 시도 후에도 JSON 형식이 맞지 않습니다", raw)
