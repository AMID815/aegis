# -*- coding: utf-8 -*-
"""가상 지정가 주문의 순수 계산 — 가격 산출과 분봉 재생.

이 모듈에는 네트워크도 파일도 없다. 그래서 분봉을 리터럴로 넣고 체결
목록을 그대로 비교할 수 있다 — 재생 규칙(설계 §4-1)이 가장 빽빽하게
테스트돼야 하는 부분이라 그렇게 뗐다.
"""
from __future__ import annotations

import pytest

from scripts import orders


def test_기본_주문가는_1차가_기준으로_계산된다():
    o = orders.plan(100000)
    assert o["buy2"] == 94000      # -6%
    assert o["buy3"] == 88000      # -12%


def test_주문가는_원단위_정수다():
    """소수가 남으면 positions.json 의 _price 검증(정수만)에 걸려 거부된다."""
    o = orders.plan(247500)
    assert o["buy2"] == round(247500 * 0.94)
    assert o["buy3"] == round(247500 * 0.88)
    assert all(isinstance(v, int) for v in o.values())


def test_평균가는_체결된_매수만_센다():
    assert orders.average([100000]) == 100000
    assert orders.average([100000, 94000]) == 97000
    assert orders.average([100000, 94000, 88000]) == 94000


def test_평균가는_동일수량_가정의_산술평균이다():
    """수량을 기록하지 않으므로(포트폴리오 규모 노출 방지) 가정에서 나온다.
    설계 §3 확정: 매번 같은 수량 → 산술평균."""
    assert orders.average([300, 200]) == 250


def test_익절선은_평균가_기준이라_물타기하면_내려간다():
    """물타기를 하는 이유 자체가 이것이다 — 목표가가 내려온다."""
    assert orders.take_profit([100000]) == round(100000 * 1.053)
    assert orders.take_profit([100000, 94000]) == round(97000 * 1.053)
    assert orders.take_profit([100000, 94000, 88000]) == round(94000 * 1.053)


def test_손절선은_3차_체결_전에는_없다():
    assert orders.stop_loss([100000]) is None
    assert orders.stop_loss([100000, 94000]) is None
    assert orders.stop_loss([100000, 94000, 88000]) == round(94000 * 0.91)


def test_손절선은_3차_체결가보다_반드시_아래다():
    """이 부등식이 깨지면 3차가 체결되는 순간 곧바로 손절이 발동한다.

    -6%/-6% 간격에 손절 -7% 이면 손절선(87,420)이 3차가(88,000)보다 위라
    모순이었다 — 그래서 손절이 -9% 로 확정됐다(설계 §2). 나중에 누가
    숫자를 만질 때 이 테스트가 막는다."""
    for first in (10000, 100000, 247500, 1000000):
        p = orders.plan(first)
        sl = orders.stop_loss([first, p["buy2"], p["buy3"]])
        assert sl < p["buy3"], f"손절선 {sl} 이 3차가 {p['buy3']} 보다 위 (1차 {first})"


def test_체결된_매수가_없으면_거부한다():
    with pytest.raises(ValueError):
        orders.average([])
