# -*- coding: utf-8 -*-
"""app.js 의 익절선/손절선 계산 상수가 scripts/orders.py 와 어긋나지 않게 못박는다.

**왜 있나**

익절선·손절선(그리고 2차·3차 지정가)은 positions.json 에 저장되지 않는다 —
저장된 건 체결된 매수가(buys)와 사다리(orders.buy2/buy3)뿐이고, 목표가는
그때그때 orders.py 의 average/take_profit/stop_loss 로 계산한다(설계 §2).
행 상세(app.js renderOpenDetail 등)가 그 값을 화면에 보여주려면 같은 계산을
JS 로 한 번 더 옮겨야 하는데 — **두 구현이 갈리면 화면이 절대 그 가격에
체결되지 않을 숫자를 자신 있게 보여주는 사고가 난다.** 조용히 새는 종류가
아니라 아예 틀린 답을 보여주는 직접적인 사고다.

`test_worker_url.py`(WORKER_URL vs CSP connect-src)와 같은 계열 — 손으로
두 파일을 같이 고쳐야 하는 값을 검증이 닿지 않는 층에서 어긋나게 두지 않는다.

**상수 대조로는 못 잡는 것**: `round()` 를 `Math.round()` 로 잘못 옮기는 실수
(반올림 "방식" 자체의 차이 — 반내림/올림이 아니라 banker's rounding 인지).
비율·호가단위 상수가 같아도 알고리즘이 다르면 위 상수 대조는 통과한다 —
그래서 이 파일 뒤쪽 절이 app.js 의 `pyRound()` 를 **node 로 실제로 실행해**
파이썬 `round()` 와 홀짝 경계에서 같은 답을 내는지 직접 확인한다(정확한
값을 이 파일에 하드코딩하지 않는다 — 파이썬 `round()` 자신이 각 실행마다
정답을 새로 만든다, 아래 참조). `node` 가 없는 환경에서는 그 절만 skip
된다 — 상수 대조(위)는 node 없이도 그대로 돈다.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

from scripts import orders

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = ROOT / "app.js"

_RATIO_RE = {
    "BUY2_RATIO": re.compile(r'const ORD_BUY2_RATIO = ([0-9.]+);'),
    "BUY3_RATIO": re.compile(r'const ORD_BUY3_RATIO = ([0-9.]+);'),
    "TAKE_PROFIT_RATIO": re.compile(r'const ORD_TAKE_PROFIT_RATIO = ([0-9.]+);'),
    "STOP_LOSS_RATIO": re.compile(r'const ORD_STOP_LOSS_RATIO = ([0-9.]+);'),
}
# 중첩 배열 리터럴 — [[num, num], [num, num], ...]. 바깥 대괄호 안을
# "[숫자, 숫자]" 의 반복으로만 매칭해, 안쪽 닫는 대괄호에서 멈추지 않게 한다.
_TICKS_RE = re.compile(r'const ORD_TICKS = (\[(?:\s*\[\d+,\s*\d+\]\s*,?\s*)+\]);')
_TICK_TOP_RE = re.compile(r'const ORD_TICK_TOP = ([0-9]+);')


def _extract_ratio(js: str, name: str) -> float:
    m = _RATIO_RE[name].search(js)
    assert m, f"app.js 에서 `const ORD_{name} = ...;` 를 못 찾았다"
    return float(m.group(1))


def _extract_ticks(js: str) -> tuple:
    m = _TICKS_RE.search(js)
    assert m, "app.js 에서 `const ORD_TICKS = [...];` 를 못 찾았다"
    pairs = json.loads(m.group(1))
    return tuple(tuple(p) for p in pairs)


def _extract_tick_top(js: str) -> int:
    m = _TICK_TOP_RE.search(js)
    assert m, "app.js 에서 `const ORD_TICK_TOP = ...;` 를 못 찾았다"
    return int(m.group(1))


# ── 실제 파일 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, py_value", [
    ("BUY2_RATIO", orders.BUY2_RATIO),
    ("BUY3_RATIO", orders.BUY3_RATIO),
    ("TAKE_PROFIT_RATIO", orders.TAKE_PROFIT_RATIO),
    ("STOP_LOSS_RATIO", orders.STOP_LOSS_RATIO),
])
def test_비율_상수가_orders_py와_같다(name, py_value):
    js = APP_JS.read_text(encoding="utf-8")
    js_value = _extract_ratio(js, name)
    assert js_value == py_value, (
        f"app.js 의 ORD_{name}({js_value}) 이 scripts/orders.py 의 {name}({py_value}) "
        "와 다르다 — 둘 중 하나를 고치면 반드시 같이 고칠 것. 어긋나면 화면이 "
        "실제로 체결되지 않을 익절선/손절선을 자신 있게 보여준다.")


def test_호가단위_표가_orders_py와_같다():
    js = APP_JS.read_text(encoding="utf-8")
    js_ticks = _extract_ticks(js)
    assert js_ticks == orders._TICKS, (
        f"app.js 의 ORD_TICKS({js_ticks}) 가 scripts/orders.py 의 _TICKS({orders._TICKS}) "
        "와 다르다 — KRX 호가단위 표가 두 파일에서 어긋났다.")


def test_호가단위_상한이_orders_py와_같다():
    js = APP_JS.read_text(encoding="utf-8")
    js_top = _extract_tick_top(js)
    assert js_top == orders._TICK_TOP, (
        f"app.js 의 ORD_TICK_TOP({js_top}) 이 scripts/orders.py 의 "
        f"_TICK_TOP({orders._TICK_TOP}) 와 다르다.")


def test_app_js_가_실제로_읽힌다():
    """경로가 틀려 빈 문자열을 검사하면 위 테스트들이 공짜로 통과한다."""
    js = APP_JS.read_text(encoding="utf-8")
    assert "ORD_BUY2_RATIO" in js and "ORD_TICKS" in js, APP_JS


# ── 검사기 자체가 진짜로 잡는지 못박는다 ────────────────────────────────
# 아무것도 못 찾는 검사기는 없는 것보다 나쁘다(test_worker_url.py 와 같은 원칙).

def test_검사기가_비율_어긋남을_잡는다():
    js = "const ORD_BUY2_RATIO = 0.95;\n"   # orders.py 는 0.94
    assert _extract_ratio(js, "BUY2_RATIO") != orders.BUY2_RATIO


def test_검사기가_비율_일치를_통과시킨다():
    js = f"const ORD_TAKE_PROFIT_RATIO = {orders.TAKE_PROFIT_RATIO};\n"
    assert _extract_ratio(js, "TAKE_PROFIT_RATIO") == orders.TAKE_PROFIT_RATIO


def test_검사기가_호가단위_표_어긋남을_잡는다():
    # 세 번째 구간(20000, 10) 을 (20000, 15) 로 바꿔치기 — 이런 손실이
    # 실제로 나면 그 가격대의 모든 지정가·익절선·손절선이 조용히 5원
    # 단위로 어긋난다.
    js = ("const ORD_TICKS = [[2000, 1], [5000, 5], [20000, 15], "
          "[50000, 50], [200000, 100], [500000, 500]];\n")
    assert _extract_ticks(js) != orders._TICKS


def test_검사기가_호가단위_표_일치를_통과시킨다():
    literal = json.dumps([list(pair) for pair in orders._TICKS])
    js = f"const ORD_TICKS = {literal};\n"
    assert _extract_ticks(js) == orders._TICKS


def test_검사기가_호가단위_상한_어긋남을_잡는다():
    js = "const ORD_TICK_TOP = 500;\n"   # orders.py 는 1000
    assert _extract_tick_top(js) != orders._TICK_TOP


def test_검사기가_상수를_못_찾으면_조용히_통과하지_않는다():
    """정규식이 못 찾으면 assert 로 바로 드러나야 한다 — 빈 문자열을 넣어도
    "같다"로 잘못 통과하면(예외 대신 None==None 같은 우연) 검사기 자체가
    무력하다는 뜻이다."""
    with pytest.raises(AssertionError):
        _extract_ratio("", "BUY2_RATIO")
    with pytest.raises(AssertionError):
        _extract_ticks("")
    with pytest.raises(AssertionError):
        _extract_tick_top("")


# ── pyRound() 대 파이썬 round() — banker's rounding 자체를 실행해 비교 ──
#
# 파이썬의 round() 는 반내림/반올림이 아니라 "가장 가까운 짝수로"다
# (half-to-even) — round(0.5)==0, round(2.5)==2. JS 의 Math.round() 는
# 항상 위로 반올림해(half-up) Math.round(0.5)==1. 상수가 아무리 정확히
# 같아도, app.js 의 pyRound() 가 언젠가 실수로 그냥 Math.round() 로
# 되돌아가면(리팩터·복붙 실수 등) 위의 상수 대조 테스트들은 전혀 못 잡는다
# — 그래서 이 절은 실제로 node 로 pyRound() 를 실행해 파이썬 round() 와
# 대조한다. 기대값을 이 파일에 숫자로 박아두지 않는다 — 파이썬 round()
# 자신이 매 실행마다 정답을 새로 계산하므로, 두 "구현"이 아니라 "언어
# 내장 round() 대 app.js pyRound()" 를 직접 비교하는 셈이다.
NODE = shutil.which("node")
_SKIP_NO_NODE = pytest.mark.skipif(
    NODE is None, reason="node 를 찾을 수 없다 — 이 절은 pyRound() 를 실제로 실행해야 한다")

# 밑(정수부)이 짝수/홀수를 고루 섞는다 — 홀수 밑에서는 반내림/반올림이나
# banker's rounding 이나 결과가 우연히 같다(둘 다 위로 올린다). 함정은
# 밑이 짝수일 때뿐이다: 파이썬은 그대로 두는데 Math.round() 는 무조건
# 올린다. 526.5/1501.5/1579.5 는 이 프로젝트가 실제로 만나는 계산에서
# 나온 값이다(500×1.053, 1650×0.91, 1500×1.053 — tests/test_orders.py
# 와 이 작업의 교차검증표 참조). -0.5 는 floor()가 음수일 때도 짝수/홀수
# 판정(floor % 2)이 옳은지 확인한다.
_TIE_CASES = [0.5, 1.5, 2.5, 3.5, 4.5, 45.5, 46.5, 526.5, 527.5, 1501.5, 1579.5, -0.5]


def _run_node_pyround(xs: list[float]) -> list[float]:
    """app.js 를 node vm 컨텍스트에서 로드하고 pyRound(x) 를 xs 각각에 적용한다.

    app.js 맨 아래(통과 커튼)는 document/window/localStorage 를 top-level 에서
    건드리므로 최소 스텁을 준다 — 그 아래에서 던지는 예외는 무시한다(우리가
    쓰는 pyRound 는 함수 선언이라 스크립트 앞부분에서 이미 등록됐다).
    """
    app_js_path = json.dumps(str(APP_JS))
    xs_json = json.dumps(xs)
    script = f"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync({app_js_path}, 'utf8');
const el = () => ({{ addEventListener(){{}}, dataset: {{}} }});
const sandbox = {{
  console,
  document: {{ getElementById: () => el(), querySelector: () => null,
               querySelectorAll: () => [], createElement: () => el() }},
  window: {{ addEventListener(){{}} }},
  localStorage: {{ getItem: () => null, setItem(){{}} }},
  CSS: {{ escape: (s) => s }},
}};
vm.createContext(sandbox);
try {{ vm.runInContext(src, sandbox); }} catch (e) {{ /* 통과 커튼 배선 실패는 무시 */ }}
if (typeof sandbox.pyRound !== "function") {{
  console.error("MISSING_PYROUND");
  process.exit(1);
}}
const xs = {xs_json};
console.log(JSON.stringify(xs.map(sandbox.pyRound)));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (
        f"node 실행이 실패했다(app.js 에서 pyRound() 를 못 찾았을 수 있다):\n{result.stderr}")
    return json.loads(result.stdout)


@_SKIP_NO_NODE
def test_pyRound가_파이썬_round와_홀짝_경계에서_일치한다():
    """이게 이 파일에서 가장 중요한 테스트다 — Math.round() 로 퇴행하면
    여기서만 걸린다(위 상수 대조는 이 실수를 못 잡는다)."""
    js_results = _run_node_pyround(_TIE_CASES)
    py_results = [round(x) for x in _TIE_CASES]
    assert js_results == py_results, (
        f"app.js 의 pyRound() 가 파이썬 round() 와 갈렸다.\n"
        f"  입력:        {_TIE_CASES}\n"
        f"  app.js pyRound: {js_results}\n"
        f"  python round:   {py_results}\n"
        "pyRound() 가 Math.round() 로 되돌아갔다면(half-up) 밑이 짝수인 .5 값마다 "
        "1 씩 더 크게 나온다 — 익절선/손절선이 실제로 체결되지 않을 가격으로 "
        "화면에 확신을 갖고 뜬다.")


def test_검사기가_Math_round_퇴행을_잡는다():
    """검사기 자체가 진짜로 잡는지 못박는다 — pyRound() 자리에 순수
    Math.round(half-up) 흉내를 넣으면 위 비교가 반드시 실패해야 한다.

    node 를 실제로 부르지 않는다(순수 파이썬 계산만 대조) — node 없는
    환경에서도 "검사기가 눈이 멀지 않았다"는 확인만은 계속 돌 수 있다."""
    import math
    naive_half_up = [
        math.floor(x) + 1 if (x - math.floor(x)) >= 0.5 else math.floor(x)
        for x in _TIE_CASES
    ]
    py_results = [round(x) for x in _TIE_CASES]
    assert naive_half_up != py_results, (
        "이 파라미터 집합으로는 half-up 과 파이썬 round() 가 구분되지 않는다 — "
        "검사기가 눈이 먼 상태로 항상 통과할 위험이 있다.")
