import json

import httpx
import pytest

from labor_law_rag.fetch import CachedFetcher, FetchError, safe_key


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok(body: bytes = "본문".encode()):
    return _client(lambda r: httpx.Response(200, content=body))


def test_second_get_uses_cache(tmp_path):
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(200, content="본문".encode())

    f = CachedFetcher(tmp_path, client=_client(handler), sleep=lambda s: None)
    assert f.get("https://x/a", cache_key="a") == "본문".encode()
    assert f.get("https://x/a", cache_key="a") == "본문".encode()
    assert len(calls) == 1
    meta = json.loads((tmp_path / "a.meta.json").read_text(encoding="utf-8"))
    assert meta["url"] == "https://x/a" and "fetched_at" in meta and meta["status"] == 200


def test_cache_survives_new_fetcher(tmp_path):
    CachedFetcher(tmp_path, client=_ok(), sleep=lambda s: None).get("https://x/a", cache_key="a")

    def boom(r):
        raise AssertionError("네트워크를 쓰면 안 됨")

    assert CachedFetcher(tmp_path, client=_client(boom)).get("https://x/a", cache_key="a") == "본문".encode()


def test_invalid_body_is_not_cached(tmp_path):
    def validate(b):
        if b"<error>" in b:
            raise ValueError("api error")

    f = CachedFetcher(tmp_path, client=_ok(b"<error>bad OC</error>"), sleep=lambda s: None)
    with pytest.raises(FetchError):
        f.get("https://x/a", cache_key="a", validate=validate)
    assert not (tmp_path / "a.bin").exists()


def test_http_error_is_not_cached(tmp_path):
    f = CachedFetcher(tmp_path, client=_client(lambda r: httpx.Response(500)), sleep=lambda s: None)
    with pytest.raises(FetchError):
        f.get("https://x/a", cache_key="a")
    assert not (tmp_path / "a.bin").exists()


def test_secret_params_are_masked_in_meta(tmp_path):
    f = CachedFetcher(tmp_path, client=_ok(), sleep=lambda s: None)
    f.get("https://x/a", params={"OC": "me", "serviceKey": "k", "query": "근로기준법"}, cache_key="a")
    meta = json.loads((tmp_path / "a.meta.json").read_text(encoding="utf-8"))
    assert meta["params"] == {"OC": "***", "serviceKey": "***", "query": "근로기준법"}


def test_waits_between_requests(tmp_path):
    slept = []
    times = iter([0.0, 0.2])
    f = CachedFetcher(tmp_path, client=_ok(), sleep=slept.append, clock=lambda: next(times))
    f.get("https://x/a", cache_key="a")
    f.get("https://x/b", cache_key="b")
    assert slept == [pytest.approx(0.8)]


def test_nested_cache_key_creates_dirs(tmp_path):
    f = CachedFetcher(tmp_path, client=_ok(), sleep=lambda s: None)
    f.get("https://x/a", cache_key="law/근로기준법_20251023")
    assert (tmp_path / "law" / "근로기준법_20251023.bin").exists()


def test_safe_key_replaces_windows_unsafe_chars():
    assert safe_key('a:b*c?"d<e>f|g') == "a_b_c__d_e_f_g"
