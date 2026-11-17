"""고용노동부 법령해석(중앙부처 1차 해석) 수집 (설계 3.1).

공공데이터포털 15140237은 LINK 방식이라, 국가법령정보 OPEN API로 직접 받는다(2026-11-17 확인).
- 목록: lawSearch.do?OC=..&target=moelCgmExpc&type=XML&display=100&page=N (전체 약 9,600건)
- 본문: lawService.do?OC=..&target=moelCgmExpc&type=XML&ID=<법령해석일련번호>
"""

from __future__ import annotations

import re
from datetime import date, datetime

from lxml import etree
from pydantic import BaseModel

from labor_law_rag.collect.law import BASE, check_api_error
from labor_law_rag.fetch import CachedFetcher
from labor_law_rag.models import Document

PAGE_SIZE = 100


class InterpRef(BaseModel):
    serial: str
    title: str
    case_no: str
    date: date | None


def _date(s: str | None) -> date | None:
    s = re.sub(r"\D", "", s or "")
    return datetime.strptime(s, "%Y%m%d").date() if len(s) == 8 else None


def _clean(s: str | None) -> str:
    text = re.sub(r"<[^>]+>", " ", s or "")  # 드물게 섞이는 HTML 태그
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def parse_interp_list(xml: bytes) -> tuple[list[InterpRef], int]:
    root = etree.fromstring(xml)
    seen, refs = set(), []
    for e in root.findall("cgmExpc"):
        serial = (e.findtext("법령해석일련번호") or "").strip()
        if not serial or serial in seen:
            continue
        seen.add(serial)
        refs.append(InterpRef(serial=serial, title=_clean(e.findtext("안건명")), case_no=_clean(e.findtext("안건번호")),
                              date=_date(e.findtext("해석일자"))))
    return refs, int(root.findtext("totalCnt") or 0)


def match_topics(title: str, topics: dict[str, list[str]]) -> bool:
    return any(kw in title for kws in topics.values() for kw in kws)


def parse_interpretation(xml: bytes, *, url: str) -> Document:
    root = etree.fromstring(xml)
    serial = root.findtext("법령해석일련번호").strip()
    parts = []
    for label, tag in (("질의", "질의요지"), ("회답", "회답"), ("이유", "이유")):
        body = _clean(root.findtext(tag))
        if body:
            parts.append(f"{label}\n{body}")
    return Document(
        doc_id=f"interp:{serial}", source_type="interpretation", title=_clean(root.findtext("안건명")),
        text="\n\n".join(parts), date=_date(root.findtext("해석일자")), url=url, license="공공누리 제1유형",
        meta={"case_no": _clean(root.findtext("안건번호")), "agency": _clean(root.findtext("해석기관명")),
              "related_laws": _clean(root.findtext("관련법령"))},
    )


def list_interpretations(fetcher: CachedFetcher, oc: str) -> list[InterpRef]:
    refs: list[InterpRef] = []
    seen: set[str] = set()
    page = 1
    while True:
        xml = fetcher.get(f"{BASE}/lawSearch.do",
                          {"OC": oc, "target": "moelCgmExpc", "type": "XML", "display": PAGE_SIZE, "page": page},
                          cache_key=f"interp/list_p{page}", validate=check_api_error)
        page_refs, total = parse_interp_list(xml)
        refs.extend(r for r in page_refs if r.serial not in seen)
        seen.update(r.serial for r in page_refs)
        if not page_refs or page * PAGE_SIZE >= total:
            return refs
        page += 1


def fetch_interpretation(fetcher: CachedFetcher, oc: str, serial: str) -> Document:
    xml = fetcher.get(f"{BASE}/lawService.do", {"OC": oc, "target": "moelCgmExpc", "type": "XML", "ID": serial},
                      cache_key=f"interp/body_{serial}", validate=check_api_error)
    # 출처 표시용 주소. OC(개인 아이디)는 넣지 않는다.
    return parse_interpretation(xml, url=f"{BASE}/lawService.do?target=moelCgmExpc&type=HTML&ID={serial}")
