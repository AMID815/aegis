# -*- coding: utf-8 -*-
from scripts import calendar as cal

DAYS = ["2026-08-12", "2026-08-13", "2026-08-14", "2026-08-18", "2026-08-19"]
# 2026-08-15 광복절, 16~17 주말 → 달력에 없다


def test_보유일수는_거래일로_센다():
    assert cal.held_days(DAYS, "2026-08-13", "2026-08-19") == 3


def test_같은_날이면_0():
    assert cal.held_days(DAYS, "2026-08-19", "2026-08-19") == 0


def test_달력_범위_밖은_None():
    assert cal.held_days(DAYS, "2026-01-02", "2026-08-19") is None
    assert cal.held_days(DAYS, "2026-08-13", "2026-12-31") is None


def test_거꾸로된_날짜는_None():
    """매도일이 매수일보다 앞서면 계산이 성립하지 않는다.

    models.py 는 저장 시점에 sell < buy 를 거부하지만, 이 함수는 그 경계
    안쪽에서만 안전하다고 가정하면 안 된다 — 예를 들어 아직 진행 중인
    포지션의 '오늘까지 보유일수'를 구할 때 buy_date 가 잘못 입력되어
    오늘보다 미래인 경우처럼, models.py 의 검증을 거치지 않고 이 함수에
    직접 인자가 들어올 수 있는 경로가 있다. 음수를 그대로 돌려주면 호출자
    실수를 조용히 삼키게 된다.
    """
    assert cal.held_days(DAYS, "2026-08-19", "2026-08-13") is None


def test_휴장일은_달력에_없다():
    assert "2026-08-15" not in DAYS
    assert cal.is_trading_day(DAYS, "2026-08-15") is False
    assert cal.is_trading_day(DAYS, "2026-08-18") is True


def test_최근_n거래일():
    assert cal.recent(DAYS, 3) == ["2026-08-14", "2026-08-18", "2026-08-19"]
    assert cal.recent(DAYS, 99) == DAYS


def test_최근_0또는_음수_거래일은_빈리스트():
    """days[-n:] 는 n=0 일 때 days[-0:] == days[0:] 이 되어 전체를 돌려준다.

    '최근 0거래일' 을 요청했는데 달력 전체가 나오면, close.py 가 윈도우
    상수를 잘못 설정했을 때 조용히 전체 백필을 해버릴 수 있다. 음수도
    마찬가지로 의미가 없는 입력이므로 빈 리스트로 처리한다.
    """
    assert cal.recent(DAYS, 0) == []
    assert cal.recent(DAYS, -1) == []


def test_빠진_날짜를_찾는다():
    있음 = {"2026-08-18", "2026-08-19"}
    assert cal.missing(DAYS, 3, 있음) == ["2026-08-14"]


def test_달력이_짧으면_경고한다():
    assert cal.too_short(DAYS, need=30) is True
    assert cal.too_short(DAYS * 10, need=30) is False
