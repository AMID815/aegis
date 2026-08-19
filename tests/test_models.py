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


# ── 아래는 코드 리뷰에서 지적된 결함(F1~F12)을 고정하는 테스트다 ──────────────


def test_같은_종목_여러_보유_중_가장_오래된_것이_매도된다():
    # 오래된 매수(08-19)를 나중에 추가해서, min() 이 리스트 순서가 아니라
    # 날짜 값으로 고르는지 확인한다. 순서로 골랐다면 이 테스트는 실패해야 한다.
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 250000, "date": "2026-08-20"})
    d = models.apply_buy(d, {
        "code": "005930", "name": "삼성전자", "price": 240000, "date": "2026-08-19"})
    assert [p["buys"][0]["date"] for p in d["positions"]] == ["2026-08-20", "2026-08-19"]

    out = models.apply_sell(d, {
        "code": "005930", "price": 260000, "date": "2026-08-25"})
    closed = [p for p in out["positions"] if p["status"] == "closed"]
    still_open = [p for p in out["positions"] if p["status"] == "open"]
    assert len(closed) == 1 and closed[0]["buys"][0]["date"] == "2026-08-19"
    assert len(still_open) == 1 and still_open[0]["buys"][0]["date"] == "2026-08-20"


def test_가격이_불리언이면_거부한다():
    with pytest.raises(models.RejectedError):
        models._price(True)


def test_가격_0_4는_0으로_저장되지_않고_거부된다():
    with pytest.raises(models.RejectedError):
        models._price(0.4)


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_가격이_무한_또는_NaN이면_거부한다(bad):
    with pytest.raises(models.RejectedError):
        models._price(bad)


def test_id가_없는_보유도_정규화되고_이어지는_매수에서_KeyError가_나지_않는다():
    raw = {"schema": 1, "positions": [
        {"code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-01", "price": 200000}]},
    ]}
    d = models.normalize(raw)
    assert d["positions"][0]["id"] == "20260801-005930"
    out = models.apply_buy(d, {
        "code": "000660", "name": "SK하이닉스", "price": 150000, "date": "2026-08-19"})
    assert len(out["positions"]) == 2


def test_buys의_첫_항목이_이상하면_격리되고_매도해도_TypeError가_아니다():
    raw = {"schema": 1, "positions": [
        {"code": "005930", "name": "삼성전자", "buys": ["문자열"], "status": "open"},
    ]}
    d = models.normalize(raw)
    assert d["positions"] == []
    with pytest.raises(models.RejectedError):
        models.apply_sell(d, {"code": "005930", "price": 100, "date": "2026-08-19"})


def test_normalize는_입력을_변형하지_않는다():
    raw = {"schema": 1, "positions": [
        {"code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-19", "price": 100000}]},
    ]}
    pos_ref = raw["positions"][0]
    before = dict(pos_ref)
    out = models.normalize(raw)
    assert pos_ref == before                    # 원본 내용이 그대로 남아있다
    assert out["positions"][0] is not pos_ref    # 반환된 것은 별개 객체다


def test_dropped_인자로_버려진_항목을_돌려받는다():
    raw = {"schema": 1, "positions": [
        {"code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-19", "price": 100000}]},
        {"없는키": 1},
        {"code": "005930", "buys": ["문자열"]},
    ]}
    dropped = []
    out = models.normalize(raw, dropped)
    assert len(out["positions"]) == 1
    assert len(dropped) == 2


def test_알수없는_schema는_거부한다():
    with pytest.raises(models.RejectedError):
        models.normalize({"schema": 2, "positions": []})


def test_status가_open_closed가_아니면_격리한다():
    raw = {"schema": 1, "positions": [
        {"code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-19", "price": 100000}], "status": "halted"},
    ]}
    assert models.normalize(raw)["positions"] == []


def test_매도일이_매수일보다_이르면_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError):
        models.apply_sell(d, {
            "code": "005930", "price": 260000, "date": "2026-08-18"})


@pytest.mark.parametrize("bad_name", [12345, ["가", "나"]])
def test_이름이_문자열이_아니면_거부한다(bad_name):
    with pytest.raises(models.RejectedError):
        models.apply_buy(models.empty_state(), {
            "code": "005930", "name": bad_name, "price": 247500, "date": "2026-08-19"})


def test_출처가_20자를_넘으면_잘라내지_않고_거부한다():
    with pytest.raises(models.RejectedError):
        models.apply_buy(models.empty_state(), {
            "code": "005930", "name": "삼성전자", "price": 247500,
            "date": "2026-08-19", "source": "가" * 21})


def test_정상적인_상태는_정규화해도_내용이_그대로다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500,
        "date": "2026-08-19", "source": "종가베팅",
        "signal_date": "2026-08-18", "memo": "메모",
    })
    assert models.normalize(d) == d


def test_시그널일_형식이_틀리면_거부한다():
    with pytest.raises(models.RejectedError):
        models.apply_buy(models.empty_state(), {
            "code": "005930", "name": "삼성전자", "price": 247500,
            "date": "2026-08-19", "signal_date": "2026/08/18"})


def test_시그널일이_매수일보다_늦으면_거부한다():
    with pytest.raises(models.RejectedError):
        models.apply_buy(models.empty_state(), {
            "code": "005930", "name": "삼성전자", "price": 247500,
            "date": "2026-08-19", "signal_date": "2026-08-20"})


def test_존재하지_않는_날짜는_거부한다():
    with pytest.raises(models.RejectedError):
        models.apply_buy(models.empty_state(), {
            "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-02-30"})


# ── 재검토(R1·R3·R4)에서 지적된 결함을 고정하는 테스트다 ──────────────────


@pytest.mark.parametrize("bad_exits", ["망가짐", {"a": 1}])
def test_exits가_리스트가_아니면_격리되고_매도해도_AttributeError가_아니다(bad_exits):
    raw = {"schema": 1, "positions": [
        {"code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-19", "price": 100000}], "exits": bad_exits},
    ]}
    d = models.normalize(raw)
    assert d["positions"] == []
    with pytest.raises(models.RejectedError):
        models.apply_sell(d, {"code": "005930", "price": 100, "date": "2026-08-20"})


def test_adjustments가_리스트가_아니면_격리한다():
    # exits 와 대칭으로 검증하기로 한 선택을 고정한다(강제되진 않지만 일관성을 위해).
    raw = {"schema": 1, "positions": [
        {"code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-19", "price": 100000}], "adjustments": "망가짐"},
    ]}
    assert models.normalize(raw)["positions"] == []


def test_dropped_페이로드는_합성된_키를_담지_않는다():
    original = {"code": "005930", "name": "n",
                "buys": [{"date": "2026-08-01", "price": 100000}], "status": "halted"}
    raw = {"schema": 1, "positions": [dict(original)]}
    dropped = []
    out = models.normalize(raw, dropped)
    assert out["positions"] == []
    assert len(dropped) == 1
    # id/signal_date/exits/adjustments 등 setdefault 로 합성되는 키가 섞여 들어가면 안 된다
    assert dropped[0] == original


@pytest.mark.parametrize("good_price", [100, 100.0])
def test_저장된_가격이_반올림해도_그대로면_통과한다(good_price):
    raw = {"schema": 1, "positions": [
        {"code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-19", "price": good_price}]},
    ]}
    out = models.normalize(raw)
    assert len(out["positions"]) == 1
    assert out["positions"][0]["buys"][0]["price"] == good_price


def test_저장된_가격이_소수면_격리한다():
    raw = {"schema": 1, "positions": [
        {"code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-19", "price": 100.4}]},
    ]}
    assert models.normalize(raw)["positions"] == []


# ── 최종 검토에서 지적된 결함: 큰 정수에서 isfinite 가 OverflowError ──────


def test_아주_큰_정수_가격도_OverflowError_없이_받아들인다():
    # int 는 항상 유한하므로 math.isfinite() 자체를 태우면 안 된다(10**309 부근에서 죽음).
    huge = int("9" * 400)
    assert models._price(huge) == huge


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_큰_정수_수정_후에도_inf_nan은_여전히_거부한다(bad):
    with pytest.raises(models.RejectedError):
        models._price(bad)


@pytest.mark.parametrize("good_price", [100, 100.0])
def test_큰_정수_수정_후에도_정수값_가격은_여전히_통과한다(good_price):
    assert models._price(good_price) == 100


def test_큰_정수_수정_후에도_0_4는_여전히_거부한다():
    with pytest.raises(models.RejectedError):
        models._price(0.4)
