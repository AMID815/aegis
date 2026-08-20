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
    assert orders.stop_loss([]) is None      # 체결이 없으면 손절선도 없다


def test_손절선은_3차_체결가보다_반드시_아래다():
    """이 부등식이 깨지면 3차가 체결되는 순간 곧바로 손절이 발동한다 —
    물타기를 다 하고 즉시 던지는 꼴이 된다.

    확정된 -6%/-6% 사다리에서 이 부등식이 깨지는 임계는 **손절 -6.38%**
    다. 즉 이 테스트가 잡는 건 그보다 얕은 손절률뿐이다(설계 §2).
    실제로 모순이 났던 건 검토 초기의 -7%/-7% 사다리 + 손절 -7% 조합이고
    (3차 86,000 vs 손절 86,490), 확정값 -9% 는 3차가 대비 2.8%p 여유가
    있다. 나중에 누가 비율을 만질 때 이 테스트가 막는다."""
    for first in (10000, 100000, 247500, 1000000):
        p = orders.plan(first)
        sl = orders.stop_loss([first, p["buy2"], p["buy3"]])
        assert sl < p["buy3"], f"손절선 {sl} 이 3차가 {p['buy3']} 보다 위 (1차 {first})"


def test_체결된_매수가_없으면_거부한다():
    with pytest.raises(ValueError):
        orders.average([])


def test_반올림이지_절단이_아니다():
    """`int()` 로 바꾸면 실패해야 하는 테스트 — 이게 없으면 '계통적 편향
    방지'라고 적어둔 결정을 아무것도 지키지 않는다(2026-08-20 리뷰가
    mutation 으로 확인: round→int 로 바꿔도 8개 전부 통과했다).

    기존 테스트 입력이 전부 나누어떨어지는 값이라(247,500 × 0.94 = 232,650.0)
    반올림 자체가 발동하지 않았다. 여기서는 일부러 안 떨어지는 값을 쓴다."""
    # 12345 × 0.88 = 10863.6 → 반올림 10864, 절단 10863 (구분됨)
    assert orders.plan(12345)["buy3"] == 10864

    # 평균: (100000 + 94000 + 88002) / 3 = 94000.666... → 반올림 94001, 절단 94000
    assert orders.average([100000, 94000, 88002]) == 94001

    # 익절: 평균이 정확히 90010(= (100000+80020)/2, 나누어떨어짐)이라
    # take_profit 자체의 반올림만 골라 검사한다.
    # 90010 × 1.053 = 94780.53 → 반올림 94781, 절단 94780 (구분됨)
    # (리뷰가 제시한 [100000, 94002] 예시는 94002 × ... 조합이 마침 소수부
    # 0.053 으로 0.5 미만이라 round 와 int 가 같은 값을 내 구분이 안 됐다 —
    # 그래서 실제로 구분되는 값으로 교체했다.)
    assert orders.take_profit([100000, 80020]) == 94781

    # 손절: 평균 94001(위에서 반올림된 값) × 0.91 = 85540.91 → 반올림 85541, 절단 85540
    assert orders.stop_loss([100000, 94000, 88002]) == 85541


def test_아주_싼_종목에서는_부등식이_깨진다():
    """알려진 한계를 못박는다 — 고치는 게 아니라 '알고 있다'를 남긴다.

    40원 이하에서 손절선이 3차가보다 위로 올라간다(설계 §2 의 핵심 부등식이
    깨진다). 정리매매·관리종목이 아니면 닿지 않는 영역이라 막지 않기로 했다
    (plan() 독스트링 참조). 이 테스트가 실패하면 그 경계가 움직였다는 뜻이다."""
    p = orders.plan(40)
    assert orders.stop_loss([40, p["buy2"], p["buy3"]]) >= p["buy3"]
    p = orders.plan(41)
    assert orders.stop_loss([41, p["buy2"], p["buy3"]]) < p["buy3"]
