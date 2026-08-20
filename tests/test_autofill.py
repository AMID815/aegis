# -*- coding: utf-8 -*-
"""autofill — 일봉으로 거르고, 닿은 종목만 분봉으로 재생한다.

네트워크는 전부 스텁이다. 여기서 확인하는 건 "언제 분봉을 요청하고 언제
안 하는가", "재생을 언제부터 시작하는가", "쓰기 실패를 어떻게 다루는가"다.
"""
from __future__ import annotations

import pytest

from scripts import autofill, models


def _pos(**over):
    p = {"id": "20260819-005930", "code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-19", "price": 100000}],
         "exits": [], "adjustments": [], "status": "open",
         "source": "종가베팅", "memo": "", "signal_date": None,
         "orders": {"buy2": 94000, "buy3": 88000, "customized": False},
         "auto": True, "observed_at": "2026-08-19T15:30"}
    p.update(over)
    return p


def _state(**over):
    return {"schema": 1, "positions": [_pos(**over)]}


# ── 거름망 ──────────────────────────────────────────────────────────────

def test_아무_주문가에도_안_닿으면_거름망이_막는다():
    """거름망의 존재 이유 — 일봉은 이미 손에 있어 공짜다."""
    assert autofill.touched({"high": 101000, "low": 99000},
                            {"buy2": 94000, "buy3": 88000}, [100000]) is False


def test_익절선에_닿으면_거름망을_통과한다():
    assert autofill.touched({"high": 106000, "low": 99000},
                            {"buy2": 94000, "buy3": 88000}, [100000]) is True


def test_물타기_주문가에_닿으면_거름망을_통과한다():
    assert autofill.touched({"high": 101000, "low": 93000},
                            {"buy2": 94000, "buy3": 88000}, [100000]) is True


def test_3차까지_체결된_뒤엔_손절선도_거름망에_들어간다():
    assert autofill.touched({"high": 90000, "low": 85000},
                            {"buy2": 94000, "buy3": 88000},
                            [100000, 94000, 88000]) is True


# ── 대상 선별 ───────────────────────────────────────────────────────────

def test_예외_지정된_기록은_아예_대상이_아니다():
    st = models.normalize(_state(auto=False))
    assert autofill.candidates(st) == []


def test_종결된_기록은_대상이_아니다():
    st = models.normalize(_state(status="closed",
                                 exits=[{"date": "2026-08-20", "price": 1,
                                         "reason": ""}]))
    assert autofill.candidates(st) == []


def test_주문가가_없는_기록은_대상이_아니다():
    """옛 기록(orders={})에 소급해서 지정가를 만들어 붙이지 않는다 — 그러면
    예전에 그냥 구경하려고 넣어둔 기록이 어느 날 갑자기 자동 매매된다."""
    st = models.normalize(_state(orders={}))
    assert autofill.candidates(st) == []


def test_열린_기록은_대상이다():
    st = models.normalize(_state())
    assert [p["id"] for p in autofill.candidates(st)] == ["20260819-005930"]


# ── 재생 시작 시각 ──────────────────────────────────────────────────────

def test_체결이_없으면_관측_시각부터():
    assert autofill.since_for(_pos()) == "202608191530"


def test_체결이_있으면_마지막_체결_시각부터():
    """이게 이 모듈에서 가장 중요한 함수다 — 관측 시각만 쓰면 하루 두 번
    도는 cron 의 두 번째 실행이 소급 익절을 낸다(모듈 독스트링 참조)."""
    p = _pos(buys=[{"date": "2026-08-19", "price": 100000},
                   {"date": "2026-08-19", "price": 94000,
                    "kind": "buy2", "t": "202608191000", "auto": True}])
    assert autofill.since_for(p) == "202608191000"


def test_관측_시각이_더_늦으면_관측_시각을_쓴다():
    """방어적 — 손편집으로 체결 시각이 관측보다 이른 기록이 생겨도
    관측 이전을 재생하지 않는다."""
    p = _pos(observed_at="2026-08-20T09:00",
             buys=[{"date": "2026-08-19", "price": 100000},
                   {"date": "2026-08-19", "price": 94000,
                    "kind": "buy2", "t": "202608191000", "auto": True}])
    assert autofill.since_for(p) == "202608200900"


def test_시각_정보가_전혀_없는_옛_기록은_매수일_15시30분으로_본다():
    """observed_at 도 buys[].t 도 없는 기록 — 다음 거래일부터 판정한다(설계 §5).
    저녁에 종가 보고 넣은 관측이 그날 오전 고가로 익절되면 승률이 부풀려진다."""
    p = _pos(observed_at=None)
    assert autofill.since_for(p) == "202608191530"


def test_체결_시각이_없는_추가매수는_무시한다():
    """손편집으로 t 없이 buys 가 늘어난 경우 — 그것 때문에 크래시하면 안 된다."""
    p = _pos(observed_at=None,
             buys=[{"date": "2026-08-19", "price": 100000},
                   {"date": "2026-08-19", "price": 94000}])
    assert autofill.since_for(p) == "202608191530"
