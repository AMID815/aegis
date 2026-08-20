# -*- coding: utf-8 -*-
"""가상 지정가 주문 — 순수 계산.

네트워크도 파일 접근도 없다. 주문 가격을 산출하고, 분봉을 시간순으로
재생해 체결 목록을 돌려준다. 부수효과는 전부 autofill.py 몫이다.

확정 규칙은 docs/설계_가상지정가주문.md §2. 숫자를 여기서 바꾸면
test_orders.py 의 부등식 테스트가 막는다 — 손절선이 3차 체결가보다
위로 올라가면 3차 체결 직후 즉시 손절되는 모순이 생긴다.
"""
from __future__ import annotations

# 1차 매수가 대비 비율. 설계 §2 확정값.
BUY2_RATIO = 0.94        # -6%
BUY3_RATIO = 0.88        # -12%
# 평균가 대비 비율.
TAKE_PROFIT_RATIO = 1.053    # +5.3%
STOP_LOSS_RATIO = 0.91       # -9%, 3차 체결 후에만 발동


def plan(first_price: int) -> dict:
    """1차 매수가로부터 2차·3차 지정가를 산출한다.

    진짜 지정가 주문처럼 **관측 시점에 절대가격으로 확정**한다 — 매번
    비율로 다시 계산하면, 나중에 1차가를 amend 로 고쳤을 때 이미 체결된
    2차·3차의 근거 가격이 소급해서 바뀐다.

    원 단위 정수로 반올림한다(절단 아님 — models._price 와 같은 이유로
    계통적 편향을 만들지 않는다). 정수가 아니면 models._price 가 저장
    단계에서 거부한다.
    """
    return {
        "buy2": round(first_price * BUY2_RATIO),
        "buy3": round(first_price * BUY3_RATIO),
    }
