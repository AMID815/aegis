# -*- coding: utf-8 -*-
"""worker.js 의 KNOWN_OPS/OP_LABEL/ALLOWED_ORIGIN 이 실제 라우팅과 어긋나지 않게 못박는다.

**왜 있나 (2026-08-21 실측 사고)**

worker/worker.js 의 KNOWN_OPS 는 scripts/intake.py 의 apply() 가 실제로
라우팅하는 op 목록을 손으로 그대로 베낀 값이다 — 새 op 를 추가할 때마다
사람이 여기도 같이 고쳐야 한다. 실제로 한 번 낡았었다: models.py·intake.py
에는 이미 watch/orders/auto/delete 가 구현돼 있는데 KNOWN_OPS 는
{buy, sell, amend} 셋뿐인 채로 배포됐다. 그 결과 그 네 op 는 Worker 단계에서
전부 HTTP 400 으로 거부됐는데 —

- **아무도 눈치채지 못했다.** worker.js 의 fetch 핸들러는 패스프레이즈
  검사를 op 검사보다 먼저 한다 — 그래서 틀린 패스프레이즈로 찌르는 흔한
  스모크 테스트("401 이 오나")는 op 값과 무관하게 항상 401 만 본다. 진짜
  패스프레이즈를 가진 실사용자가 새 op 를 실제로 써야만 이 400 이 드러난다.
- 601개 테스트 중 이걸 잡는 테스트가 하나도 없었다 — KNOWN_OPS 를
  {buy, sell, amend} 로 되돌려도 기존 스위트는 전부 초록이었다.

이 파일은 그 간극을 막는다. worker.js 의 KNOWN_OPS/OP_LABEL 을 정규식으로
뽑아 scripts/intake.py 의 KNOWN_OPS(apply() 가 실제로 참조하는 dispatch
테이블의 키 — 아래 "왜 정규식이 아닌가" 참조)와 대조하고, ALLOWED_ORIGIN 이
실제 서비스 오리진과 같은지도 함께 못박는다.

**scripts/intake.py 쪽은 정규식으로 파싱하지 않는다.** apply() 의 if/elif
사슬을 정규식으로 다시 읽는 접근은 리팩터에 약할 뿐 아니라 — "이 정규식이
실제로 apply() 가 라우팅하는 op 와 같다"는 보장이 애초에 없다(정규식과
실제 분기가 따로 낡을 수 있다. 이 테스트가 막으려는 것과 정확히 같은 종류의
함정을 검사기 자신이 반복하는 셈이다). 그래서 scripts/intake.py 에
`KNOWN_OPS`(frozenset) 를 두고 `apply()` 가 그 frozenset 으로 만든 dispatch
dict(`_OP_HANDLERS`)를 직접 참조하게 고쳤다 — intake.py 안에서는 이제 이
둘이 **구조적으로** 벌어질 수 없다(dispatch dict 에 없는 op 를 apply() 가
처리할 방법이 없다). 이 테스트는 그렇게 정의된 `intake.KNOWN_OPS` 를 worker.js
의 KNOWN_OPS 와 대조하기만 하면 된다 — 실제 파이썬 객체이므로 파싱이
아니라 import 다.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from scripts import intake

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKER_JS = ROOT / "worker" / "worker.js"

# 페이지가 실제로 서빙되는 오리진(README/CLAUDE.md 기준: amid815.github.io/aegis).
SERVED_ORIGIN = "https://amid815.github.io"

_KNOWN_OPS_RE = re.compile(r"const KNOWN_OPS = new Set\(\[(.*?)\]\);", re.S)
_OP_LABEL_RE = re.compile(r"const OP_LABEL = \{(.*?)\};", re.S)
_ALLOWED_ORIGIN_RE = re.compile(r'const ALLOWED_ORIGIN = "([^"]*)";')
_STRING_RE = re.compile(r'"([^"]+)"')
_LABEL_ENTRY_RE = re.compile(r'(\w+):\s*"([^"]+)"')


def worker_known_ops(js: str) -> set:
    m = _KNOWN_OPS_RE.search(js)
    assert m, "worker.js 에서 `const KNOWN_OPS = new Set([...]);` 를 못 찾았다"
    return set(_STRING_RE.findall(m.group(1)))


def worker_op_label(js: str) -> dict:
    m = _OP_LABEL_RE.search(js)
    assert m, "worker.js 에서 `const OP_LABEL = {...};` 를 못 찾았다"
    return dict(_LABEL_ENTRY_RE.findall(m.group(1)))


def worker_allowed_origin(js: str) -> str:
    m = _ALLOWED_ORIGIN_RE.search(js)
    assert m, 'worker.js 에서 `const ALLOWED_ORIGIN = "...";` 를 못 찾았다'
    return m.group(1)


# ── 실제 파일 ───────────────────────────────────────────────────────────

def test_KNOWN_OPS가_intake_apply와_같다():
    js = WORKER_JS.read_text(encoding="utf-8")
    js_ops = worker_known_ops(js)
    py_ops = set(intake.KNOWN_OPS)
    assert js_ops == py_ops, (
        f"worker/worker.js 의 KNOWN_OPS({sorted(js_ops)}) 가 "
        f"scripts/intake.py 의 apply() 가 실제로 라우팅하는 op 집합"
        f"({sorted(py_ops)}) 과 다르다.\n"
        "worker.js 의 fetch 핸들러는 패스프레이즈 검사를 op 검사보다 먼저 "
        "하므로, 이 둘이 어긋나도 틀린 패스프레이즈로 찌르는 흔한 스모크 "
        "테스트(항상 401)로는 절대 드러나지 않는다 — 진짜 패스프레이즈를 "
        "가진 실사용자가 빠진 op 를 실제로 써야만 HTTP 400 으로 드러난다 "
        "(실측: 2026-08-21, watch/orders/auto/delete 네 op 가 이렇게 배포된 "
        "채 방치돼 있었다). 새 op 를 추가하면 scripts/intake.py 의 "
        "_OP_HANDLERS(그리고 worker.js 의 KNOWN_OPS·OP_LABEL)를 같이 고칠 것.")


def test_OP_LABEL이_KNOWN_OPS_전체를_덮는다():
    js = WORKER_JS.read_text(encoding="utf-8")
    ops = worker_known_ops(js)
    labels = worker_op_label(js)
    missing = ops - set(labels)
    assert not missing, (
        f"worker.js 의 OP_LABEL 이 KNOWN_OPS 의 op {sorted(missing)} 를 "
        "빠뜨렸다 — buildTitle() 이 이 op 에 라벨이 없으면 이슈 제목이 "
        "조용히 'WRITE'로 낮아진다(사용자가 알아채기 어렵다).")


def test_ALLOWED_ORIGIN이_실제_서비스_오리진과_같다():
    js = WORKER_JS.read_text(encoding="utf-8")
    origin = worker_allowed_origin(js)
    assert origin == SERVED_ORIGIN, (
        f"worker.js 의 ALLOWED_ORIGIN({origin}) 이 실제 페이지가 서빙되는 "
        f"오리진({SERVED_ORIGIN}) 과 다르다 — 브라우저가 CORS 로 모든 쓰기 "
        "요청을 막고, 페이지는 이를 네트워크 오류와 구분하지 못한 채 깃허브 "
        "폴백으로 조용히 넘어간다.")


def test_worker_js가_실제로_읽힌다():
    """경로가 틀려 빈 문자열을 검사하면 위 테스트들이 공짜로 통과한다."""
    js = WORKER_JS.read_text(encoding="utf-8")
    assert "KNOWN_OPS" in js and "OP_LABEL" in js and "ALLOWED_ORIGIN" in js, WORKER_JS


# ── 검사기 자체가 진짜로 잡는지 못박는다 ────────────────────────────────
# 아무것도 못 찾는 검사기는 없는 것보다 나쁘다(test_worker_url.py 와 같은 원칙).

def test_검사기가_KNOWN_OPS_어긋남을_잡는다():
    # 실제로 배포됐던 낡은 값 그대로 재현(2026-08-21).
    stale_js = 'const KNOWN_OPS = new Set([\n  "buy", "sell", "amend",\n]);\n'
    assert worker_known_ops(stale_js) != set(intake.KNOWN_OPS)


def test_검사기가_KNOWN_OPS_일치를_통과시킨다():
    literal = ", ".join(f'"{op}"' for op in sorted(intake.KNOWN_OPS))
    js = f"const KNOWN_OPS = new Set([{literal}]);\n"
    assert worker_known_ops(js) == set(intake.KNOWN_OPS)


def test_검사기가_OP_LABEL_누락을_잡는다():
    js = ('const KNOWN_OPS = new Set(["buy", "sell"]);\n'
          'const OP_LABEL = {\n  buy: "BUY",\n};\n')
    ops = worker_known_ops(js)
    labels = worker_op_label(js)
    assert ops - set(labels), "놓쳤다: sell 이 라벨에 없는데 안 잡혔다"


def test_검사기가_OP_LABEL_전체_커버를_통과시킨다():
    js = ('const KNOWN_OPS = new Set(["buy", "sell"]);\n'
          'const OP_LABEL = {\n  buy: "BUY", sell: "SELL",\n};\n')
    ops = worker_known_ops(js)
    labels = worker_op_label(js)
    assert not (ops - set(labels))


def test_검사기가_ALLOWED_ORIGIN_어긋남을_잡는다():
    js = 'const ALLOWED_ORIGIN = "https://evil.example.com";\n'
    assert worker_allowed_origin(js) != SERVED_ORIGIN


def test_검사기가_ALLOWED_ORIGIN_일치를_통과시킨다():
    js = f'const ALLOWED_ORIGIN = "{SERVED_ORIGIN}";\n'
    assert worker_allowed_origin(js) == SERVED_ORIGIN


def test_검사기가_상수를_못_찾으면_조용히_통과하지_않는다():
    """정규식이 못 찾으면 assert 로 바로 드러나야 한다 — 빈 문자열을 넣어도
    "같다"로 잘못 통과하면 검사기 자체가 무력하다는 뜻이다."""
    with pytest.raises(AssertionError):
        worker_known_ops("")
    with pytest.raises(AssertionError):
        worker_op_label("")
    with pytest.raises(AssertionError):
        worker_allowed_origin("")
