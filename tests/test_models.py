# -*- coding: utf-8 -*-
import pytest
from scripts import models


def test_빈_상태를_만든다():
    d = models.empty_state()
    assert d == {"schema": 1, "positions": []}


def test_매수를_추가한다():
    d = models.empty_state()
    out = models.apply_buy(d, {
        "code": "005930", "name": "삼성전자", "price": 247500,
        "date": "2026-08-19", "source": "종가베팅",
        "signal_date": "2026-08-18", "memo": "",
    })
    assert len(out["positions"]) == 1
    p = out["positions"][0]
    assert p["id"] == "20260819-005930"
    assert p["status"] == "open"
    assert p["buys"] == [{"date": "2026-08-19", "price": 247500}]
    assert p["exits"] == []
    assert p["adjustments"] == []


def test_같은_종목_같은_날_중복매수는_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError):
        models.apply_buy(d, {
            "code": "005930", "name": "삼성전자", "price": 250000, "date": "2026-08-19"})


def test_매도는_해당_보유를_종결시킨다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    out = models.apply_sell(d, {
        "code": "005930", "price": 260000, "date": "2026-08-25", "reason": "목표가"})
    p = out["positions"][0]
    assert p["status"] == "closed"
    assert p["exits"] == [{"date": "2026-08-25", "price": 260000, "reason": "목표가"}]


def test_보유중이_아닌_종목_매도는_거부한다():
    with pytest.raises(models.RejectedError):
        models.apply_sell(models.empty_state(), {
            "code": "005930", "price": 260000, "date": "2026-08-25"})


@pytest.mark.parametrize("bad", [
    {"code": "5930", "name": "x", "price": 100, "date": "2026-08-19"},        # 6자리 아님
    {"code": "005930", "name": "x", "price": 0, "date": "2026-08-19"},        # 가격 0
    {"code": "005930", "name": "x", "price": -1, "date": "2026-08-19"},       # 음수
    {"code": "005930", "name": "x", "price": 100, "date": "2026/08/19"},      # 날짜 형식
    {"code": "005930", "name": "x", "price": "많이", "date": "2026-08-19"},   # 숫자 아님
])
def test_잘못된_입력은_거부한다(bad):
    with pytest.raises(models.RejectedError):
        models.apply_buy(models.empty_state(), bad)


def test_출처를_비우면_수동이_된다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    assert d["positions"][0]["source"] == "수동"


def test_손상된_파일은_빈_상태로_격리한다():
    assert models.normalize(None) == models.empty_state()
    assert models.normalize({"positions": "목록아님"}) == models.empty_state()
    assert models.normalize({"schema": 1, "positions": [{"없는키": 1}]})["positions"] == []
