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
