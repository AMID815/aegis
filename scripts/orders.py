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


def average(prices: list) -> int:
    """체결된 매수가들의 평균. 설계 §3 확정: 동일 수량 가정 = 산술평균.

    수량을 기록하지 않기로 했으므로(포트폴리오 규모 노출 방지) 평균가는
    가정에서 나온다. 나중에 "매번 같은 금액"(조화평균)으로 바꿀 수 있는데,
    그때 **과거 기록의 평균가가 소급해서 바뀌면 안 된다** — 이미 그 평균가로
    익절·손절이 체결된 기록들이라 계산식이 바뀌면 과거 체결이 소급 무효가
    된다. 그래서 체결 기록에 그 시점의 방식(`weighting`)을 함께 저장한다
    (models.apply_fills 참조).
    """
    if not prices:
        raise ValueError("체결된 매수가 없다")
    return round(sum(prices) / len(prices))


def take_profit(prices: list) -> int:
    """익절선. 평균가 기준이라 물타기하면 내려온다 — 그게 물타기의 목적이다."""
    return round(average(prices) * TAKE_PROFIT_RATIO)


def stop_loss(prices: list):
    """손절선. **3차 체결 후에만** 존재한다(설계 §2). 그 전에는 None.

    3차까지 안 간 종목은 손절 경로가 없어 영원히 열려 있을 수 있다 —
    설계 §11 이 명시한 한계이고, 통계 화면이 미결 건수를 드러내야 한다.
    """
    if len(prices) < 3:
        return None
    return round(average(prices) * STOP_LOSS_RATIO)
