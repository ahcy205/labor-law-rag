"""국가법령정보 OPEN API에서 기준일에 시행 중인 법령 본문을 받는다 (설계 3.3).

요청 형식(2026-11-17 확인):
- 목록: https://www.law.go.kr/DRF/lawSearch.do?OC=..&target=eflaw&type=XML&query=<법령명>&display=100&page=N
- 본문: https://www.law.go.kr/DRF/lawService.do?OC=..&target=eflaw&type=XML&MST=<법령일련번호>&efYd=<시행일자>
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from lxml import etree
from pydantic import BaseModel

from labor_law_rag.config import LawSpec
from labor_law_rag.fetch import CachedFetcher, safe_key

BASE = "https://www.law.go.kr/DRF"
_ERROR_MARKERS = ("사용자 정보 검증에 실패", "일치하는 법령이 없습니다", "미신청된", "<Response>")


class LawVersion(BaseModel):
    name: str
    mst: str
    effective_date: date
    promulgation_date: date


def _ymd(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y%m%d").date()


def check_api_error(body: bytes) -> None:
    """API는 오류도 200으로 돌려준다. 오류 본문이면 ValueError(캐시에 남지 않게)."""
    head = body[:2000].decode("utf-8", errors="ignore")
    for marker in _ERROR_MARKERS:
        if marker in head:
            raise ValueError(f"API 오류 응답: {' '.join(head.split())[:200]}")


def parse_versions(search_xml: bytes, name: str) -> list[LawVersion]:
    root = etree.fromstring(search_xml)
    versions = []
    for law in root.findall("law"):
        if (law.findtext("법령명한글") or "").strip() != name:
            continue
        versions.append(LawVersion(
            name=name, mst=law.findtext("법령일련번호").strip(),
            effective_date=_ymd(law.findtext("시행일자")), promulgation_date=_ymd(law.findtext("공포일자")),
        ))
    return versions


def select_version(candidates: list[LawVersion], base_date: date) -> LawVersion:
    effective = [v for v in candidates if v.effective_date <= base_date]
    if not effective:
        raise ValueError(f"{base_date}에 시행 중인 버전이 없습니다")
    return max(effective, key=lambda v: (v.effective_date, v.promulgation_date))


def search_versions(fetcher: CachedFetcher, oc: str, name: str, base_date: date) -> list[LawVersion]:
    versions: list[LawVersion] = []
    for page in range(1, 50):
        xml = fetcher.get(
            f"{BASE}/lawSearch.do",
            {"OC": oc, "target": "eflaw", "type": "XML", "query": name, "display": 100, "page": page},
            cache_key=f"law/search/{safe_key(name)}_{base_date:%Y%m%d}_p{page}",
            validate=check_api_error,
        )
        versions.extend(parse_versions(xml, name))
        if len(etree.fromstring(xml).findall("law")) < 100:
            break
    return versions


class NoticeVersion(BaseModel):
    name: str
    rule_id: str
    effective_date: date


_WAGE_NOTICE = re.compile(r"^\d{4}년 적용 최저임금 고시$")


def select_notice(search_xml: bytes, base_date: date) -> NoticeVersion:
    """행정규칙 목록에서 기준일에 시행 중인 고용노동부 'YYYY년 적용 최저임금 고시'를 고른다.

    '최저임금안 고시', '선원 최저임금 고시'는 이름 규칙으로 걸러진다.
    """
    root = etree.fromstring(search_xml)
    cands = []
    for r in root.findall("admrul"):
        name = (r.findtext("행정규칙명") or "").strip()
        if _WAGE_NOTICE.match(name) and (r.findtext("소관부처명") or "").strip() == "고용노동부":
            cands.append(NoticeVersion(name=name, rule_id=r.findtext("행정규칙일련번호").strip(),
                                       effective_date=_ymd(r.findtext("시행일자"))))
    effective = [c for c in cands if c.effective_date <= base_date]
    if not effective:
        raise ValueError(f"{base_date}에 시행 중인 최저임금 고시가 없습니다")
    return max(effective, key=lambda c: c.effective_date)


def notice_pdf_link(body_xml: bytes) -> str:
    """고시 본문은 비어 있고 첨부 PDF만 있다. 고시 PDF 링크(이유서 제외)를 돌려준다."""
    root = etree.fromstring(body_xml)
    att = root.find("첨부파일")
    names = [(n.text or "").strip() for n in att.findall("첨부파일명")]
    links = [(n.text or "").strip() for n in att.findall("첨부파일링크")]
    for name, link in zip(names, links, strict=True):
        if name.endswith(".pdf") and "고시" in name and "이유" not in name:
            return link
    raise ValueError(f"고시 PDF 첨부를 찾을 수 없습니다: {names}")


def collect_notice(fetcher: CachedFetcher, oc: str, base_date: date) -> tuple[Path, NoticeVersion, str]:
    """기준일 시행 최저임금 고시 PDF를 캐시에 받고 (경로, 버전, PDF 주소)를 돌려준다."""
    search = fetcher.get(
        f"{BASE}/lawSearch.do",
        {"OC": oc, "target": "admrul", "type": "XML", "query": "최저임금", "display": 100},
        cache_key=f"notice/search_최저임금_{base_date:%Y%m%d}", validate=check_api_error,
    )
    v = select_notice(search, base_date)
    body = fetcher.get(f"{BASE}/lawService.do", {"OC": oc, "target": "admrul", "type": "XML", "ID": v.rule_id},
                       cache_key=f"notice/body_{v.rule_id}", validate=check_api_error)
    link = notice_pdf_link(body).replace("http://", "https://")
    key = f"notice/pdf_{v.rule_id}"

    def is_pdf(b: bytes) -> None:
        if not b.startswith(b"%PDF"):
            raise ValueError("PDF가 아닌 응답")

    fetcher.get(link, cache_key=key, validate=is_pdf)
    return fetcher.cache_dir / f"{key}.bin", v, link


def collect_law(fetcher: CachedFetcher, oc: str, spec: LawSpec, base_date: date) -> Path:
    """기준일 시행 버전의 본문 XML을 캐시에 받고 그 경로를 돌려준다."""
    v = select_version(search_versions(fetcher, oc, spec.name, base_date), base_date)
    key = f"law/{safe_key(spec.name)}_{v.effective_date:%Y%m%d}"
    fetcher.get(
        f"{BASE}/lawService.do",
        {"OC": oc, "target": "eflaw", "type": "XML", "MST": v.mst, "efYd": f"{v.effective_date:%Y%m%d}"},
        cache_key=key,
        validate=check_api_error,
    )
    return fetcher.cache_dir / f"{key}.bin"
