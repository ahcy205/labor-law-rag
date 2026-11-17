from datetime import date
from pathlib import Path

import httpx
import pytest

from labor_law_rag.collect.law import LawVersion, check_api_error, collect_law, parse_versions, select_version
from labor_law_rag.config import LawSpec
from labor_law_rag.fetch import CachedFetcher, FetchError

FIX = Path(__file__).parent.parent / "fixtures" / "law"


def test_select_version_ignores_future_amendment():
    v = [LawVersion(name="근로기준법", mst="1", effective_date=date(2025, 10, 23), promulgation_date=date(2025, 4, 1)),
         LawVersion(name="근로기준법", mst="2", effective_date=date(2027, 1, 1), promulgation_date=date(2026, 7, 1))]
    assert select_version(v, date(2026, 11, 17)).mst == "1"


def test_select_version_tie_breaks_on_promulgation():
    v = [LawVersion(name="x", mst="1", effective_date=date(2026, 1, 1), promulgation_date=date(2025, 1, 1)),
         LawVersion(name="x", mst="2", effective_date=date(2026, 1, 1), promulgation_date=date(2025, 6, 1))]
    assert select_version(v, date(2026, 11, 17)).mst == "2"


def test_select_version_none_effective_raises():
    with pytest.raises(ValueError):
        select_version([LawVersion(name="x", mst="1", effective_date=date(2027, 1, 1),
                                   promulgation_date=date(2026, 1, 1))], date(2026, 11, 17))


def test_parse_versions_keeps_exact_name_only():
    vs = parse_versions((FIX / "eflaw_search_근로기준법.xml").read_bytes(), "근로기준법")
    assert vs and all(v.name == "근로기준법" for v in vs)
    assert select_version(vs, date(2026, 11, 17)).effective_date == date(2026, 10, 8)


def test_check_api_error_rejects_error_body():
    with pytest.raises(ValueError):
        check_api_error("<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>미신청된 목록/본문</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>".encode())
    with pytest.raises(ValueError):
        check_api_error("사용자 정보 검증에 실패하였습니다.".encode())
    check_api_error((FIX / "근로기준법.xml").read_bytes())


def test_collect_law_uses_selected_version(tmp_path):
    search = (FIX / "eflaw_search_근로기준법.xml").read_bytes()
    body = (FIX / "근로기준법.xml").read_bytes()
    seen = []

    def handler(r):
        seen.append(dict(r.url.params))
        return httpx.Response(200, content=search if "lawSearch" in r.url.path else body)

    f = CachedFetcher(tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    path = collect_law(f, "test", LawSpec(name="근로기준법", kind="law"), date(2026, 11, 17))
    assert path.read_bytes() == body
    svc = seen[-1]
    assert svc["target"] == "eflaw" and svc["efYd"] == "20261008" and svc["MST"] == "285279"


def test_collect_law_api_error_raises(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content="사용자 정보 검증에 실패하였습니다.".encode())))
    f = CachedFetcher(tmp_path, client=client, sleep=lambda s: None)
    with pytest.raises(FetchError):
        collect_law(f, "test", LawSpec(name="근로기준법", kind="law"), date(2026, 11, 17))
