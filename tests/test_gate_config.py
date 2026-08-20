# -*- coding: utf-8 -*-
"""통과 커튼(#gate)의 배포 상수가 서로 어긋나지 않게 못박는다.

**왜 있나**

`GATE_PBKDF2_HEX` 는 자리표시자를 봐주는 경로가 **없다** — app.js 의 커튼은
입력 문구의 해시를 이 상수와 그냥 `===` 로 비교한다. 그래서 자리표시자인
채로 배포하면 **어떤 문구로도 커튼이 열리지 않는다.** 사이트가 통째로 잠기고,
고치려면 다시 커밋해서 GitHub Pages 재배포를 기다려야 한다.

소금·반복수도 같이 고정한다. 이 둘 중 하나만 바꾸면 같은 문구가 다른 해시를
내므로 `GATE_PBKDF2_HEX` 가 조용히 무효가 된다 — 증상은 위와 똑같다(아무
문구도 안 통함). 값을 올리는 건 보안상 옳은 변경일 수 있으므로 이 테스트는
"바꾸지 마라"가 아니라 **"바꿨으면 해시도 다시 계산해서 같이 고쳐라"** 를
강제한다.

문구 자체는 여기 없다(공개 저장소다). 해시가 실제로 Worker 의 GATE_PASS 와
같은 문구에서 나왔는지는 정적으로 알 수 없다 — 그건 app.js 의
probeWorkerAuth() 가 런타임에 감지한다.
"""
from __future__ import annotations

import pathlib
import re

import pytest

APP_JS = pathlib.Path(__file__).resolve().parent.parent / "app.js"

HEX_RE = re.compile(r'^const GATE_PBKDF2_HEX = "([^"]*)";', re.M)
SALT_RE = re.compile(r'^const GATE_PBKDF2_SALT = new TextEncoder\(\)\.encode\("([^"]*)"\);', re.M)
ITER_RE = re.compile(r'^const GATE_PBKDF2_ITERATIONS = (\d+);', re.M)

# 2026-08-20 배포 시점에 확정된 값. 해시는 이 둘에 묶여 있다.
EXPECTED_SALT = "mouigosa-gate-salt-v1"
EXPECTED_ITERATIONS = 600000


def _one(rx: str, src: str, what: str):
    m = rx.search(src)
    assert m, f"app.js 에서 {what} 를 못 찾았다"
    return m.group(1)


def test_검증값이_자리표시자가_아니다():
    hex_ = _one(HEX_RE, APP_JS.read_text(encoding="utf-8"), "GATE_PBKDF2_HEX")
    assert re.fullmatch(r"[0-9a-f]{64}", hex_), (
        f"GATE_PBKDF2_HEX 가 64자리 소문자 16진수가 아니다: {hex_!r}\n"
        "이대로 배포하면 어떤 문구로도 커튼이 열리지 않아 사이트가 잠긴다.\n"
        "worker/README.md 5단계의 파이썬 한 줄로 다시 계산해 넣을 것.")


def test_소금과_반복수가_해시와_함께_고정돼_있다():
    src = APP_JS.read_text(encoding="utf-8")
    salt = _one(SALT_RE, src, "GATE_PBKDF2_SALT")
    iters = int(_one(ITER_RE, src, "GATE_PBKDF2_ITERATIONS"))
    assert (salt, iters) == (EXPECTED_SALT, EXPECTED_ITERATIONS), (
        f"소금/반복수가 바뀌었다: {salt!r}, {iters}\n"
        f"(기대: {EXPECTED_SALT!r}, {EXPECTED_ITERATIONS})\n"
        "바꾸는 것 자체는 괜찮지만, 그러면 같은 문구가 다른 해시를 내므로\n"
        "GATE_PBKDF2_HEX 를 새 값으로 다시 계산해 함께 고치고, 이 테스트의\n"
        "EXPECTED_* 도 같이 갱신해야 한다. 하나만 고치면 아무 문구도 안 통한다.")


# ── 검사기 자체가 진짜로 잡는지 ─────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    "REPLACE_WITH_YOUR_PBKDF2_HEX",                                        # 자리표시자
    "",                                                                    # 빈 값
    "1ECC80828EE19C54A6CD9BB512CCF5CD64A2878ED3E7C9C5CD1B05518BF198AF",    # 대문자
    "1ecc80828ee19c54a6cd9bb512ccf5cd64a2878ed3e7c9c5cd1b05518bf198a",     # 63자
    "1ecc80828ee19c54a6cd9bb512ccf5cd64a2878ed3e7c9c5cd1b05518bf198aff",   # 65자
    "zecc80828ee19c54a6cd9bb512ccf5cd64a2878ed3e7c9c5cd1b05518bf198af",    # 16진수 아님
])
def test_검사기가_잘못된_검증값을_잡는다(bad):
    assert not re.fullmatch(r"[0-9a-f]{64}", bad), f"놓쳤다: {bad!r}"


def test_검사기가_정상값을_통과시킨다():
    assert re.fullmatch(r"[0-9a-f]{64}", "0" * 64)


def test_상수_추출이_실제로_동작한다():
    """정규식이 안 맞아 빈 문자열을 검사하면 위 테스트가 공짜로 통과한다."""
    src = APP_JS.read_text(encoding="utf-8")
    assert len(_one(HEX_RE, src, "hex")) == 64
    assert _one(SALT_RE, src, "salt") == EXPECTED_SALT
