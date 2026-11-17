import json

import httpx
import pytest
from pydantic import BaseModel

from labor_law_rag.llm import FakeLLM, LLMOutputError, OllamaClient, generate_json


class Q(BaseModel):
    question: str


def test_generate_json_retries_then_succeeds():
    llm = FakeLLM(["not json", '{"question": "연차는?"}'])
    assert generate_json(llm, "p", model="qwen3:8b", schema=Q).question == "연차는?"
    assert len(llm.calls) == 2
    assert "not json" in llm.calls[1]["prompt"] or "오류" in llm.calls[1]["prompt"]


def test_generate_json_gives_up_after_retries():
    llm = FakeLLM(["x", "y", "z", '{"question": "늦음"}'])
    with pytest.raises(LLMOutputError) as e:
        generate_json(llm, "p", model="m", schema=Q, max_retries=2)
    assert len(llm.calls) == 3
    assert e.value.raw == "z"


def test_generate_json_passes_schema_and_system():
    llm = FakeLLM(['{"question": "a"}'])
    generate_json(llm, "p", model="m", schema=Q, system="sys")
    assert llm.calls[0]["json_schema"]["type"] == "object" and llm.calls[0]["system"] == "sys"


def test_ollama_request_shape():
    seen = {}

    def handler(r):
        seen["url"] = str(r.url)
        seen.update(json.loads(r.content))
        return httpx.Response(200, json={"response": '{"question":"a"}'})

    c = OllamaClient("http://localhost:11434", client=httpx.Client(transport=httpx.MockTransport(handler)))
    out = c.generate("p", model="qwen3:8b", system="s", json_schema=Q.model_json_schema())
    assert out == '{"question":"a"}'
    assert seen["url"] == "http://127.0.0.1:11434/api/generate"  # localhost는 IPv6 대기로 2초 지연
    assert seen["model"] == "qwen3:8b" and seen["stream"] is False and seen["format"]["type"] == "object"
    assert seen["think"] is False and seen["options"]["temperature"] == 0.0 and seen["system"] == "s"
    assert seen["options"]["num_predict"] == 1024  # 상한이 없으면 qwen3가 JSON 문자열을 끝없이 이어 씀


def test_ollama_token_cap_is_configurable():
    seen = {}

    def handler(r):
        seen.update(json.loads(r.content))
        return httpx.Response(200, json={"response": "{}"})

    c = OllamaClient("http://h", client=httpx.Client(transport=httpx.MockTransport(handler)), max_tokens=256)
    c.generate("p", model="m")
    assert seen["options"]["num_predict"] == 256


def test_ollama_http_error_raises():
    c = OllamaClient("http://h", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    with pytest.raises(httpx.HTTPStatusError):
        c.generate("p", model="m")
