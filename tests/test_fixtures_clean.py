"""fixture에 실제 OC(API 아이디)가 섞여 커밋되지 않게 막는다."""

import re
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def test_no_real_oc_in_fixtures():
    leaked = []
    for p in FIXTURES.rglob("*"):
        if p.is_file():
            text = p.read_bytes().decode("utf-8", errors="ignore")
            for m in re.finditer(r"OC=([A-Za-z0-9_.-]+)", text):
                if m.group(1) != "test":
                    leaked.append(f"{p.name}: OC={m.group(1)[:2]}***")
    assert not leaked, leaked
