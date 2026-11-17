"""원본을 캐시하고 요청 간격을 지키는 수집기 (설계 3.4, 12절 수집 예절)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

SECRET_PARAMS = {"OC", "serviceKey", "ServiceKey"}


class FetchError(Exception):
    pass


def safe_key(s: str) -> str:
    """캐시 파일 이름 한 부분에 쓸 수 없는 문자를 `_`로 바꾼다."""
    return re.sub(r'[/\\:*?"<>|]', "_", s)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class CachedFetcher:
    def __init__(
        self,
        cache_dir: Path,
        min_interval_s: float = 1.0,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.cache_dir = Path(cache_dir)
        self.min_interval_s = min_interval_s
        self.client = client or httpx.Client(timeout=60.0, follow_redirects=True)
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def _paths(self, cache_key: str) -> tuple[Path, Path]:
        base = self.cache_dir / cache_key
        return base.with_name(base.name + ".bin"), base.with_name(base.name + ".meta.json")

    def _throttle(self) -> None:
        now = self._clock()
        if self._last is not None:
            wait = self.min_interval_s - (now - self._last)
            if wait > 0:
                self._sleep(wait)
                now += wait
        self._last = now

    def get(
        self,
        url: str,
        params: dict | None = None,
        *,
        cache_key: str,
        validate: Callable[[bytes], None] | None = None,
    ) -> bytes:
        body_path, meta_path = self._paths(cache_key)
        if body_path.exists():
            return body_path.read_bytes()

        self._throttle()
        try:
            resp = self.client.get(url, params=params)
        except httpx.HTTPError as e:
            raise FetchError(f"{url}: 요청 실패: {e}") from e
        if resp.status_code != 200:
            raise FetchError(f"{url}: HTTP {resp.status_code}")
        body = resp.content
        if validate is not None:
            try:
                validate(body)
            except Exception as e:
                raise FetchError(f"{url}: 응답 검증 실패: {e}") from e

        masked = {k: ("***" if k in SECRET_PARAMS else v) for k, v in (params or {}).items()}
        meta = {
            "url": url,
            "params": masked,
            "fetched_at": datetime.now(UTC).isoformat(),
            "status": resp.status_code,
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        # 메타를 먼저 쓴다. 본문이 캐시 존재의 기준이므로, 중간에 끊겨도 메타 없는 본문은 남지 않는다.
        _atomic_write(meta_path, json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
        _atomic_write(body_path, body)
        return body
