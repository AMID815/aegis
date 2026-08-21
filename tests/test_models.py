# -*- coding: utf-8 -*-
import pytest
from scripts import models
from scripts import orders


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
    {"code": "12345", "name": "x", "price": 100, "date": "2026-08-19"},       # 5자리
    {"code": "abcdef", "name": "x", "price": 100, "date": "2026-08-19"},      # 소문자 — KRX 는 대문자만
    {"code": "005930\n", "name": "x", "price": 100, "date": "2026-08-19"},    # 끝에 개행 — $ 는 통과시키지만 \Z 는 거부
    {"code": "005930", "name": "x", "price": 0, "date": "2026-08-19"},        # 가격 0
    {"code": "005930", "name": "x", "price": -1, "date": "2026-08-19"},       # 음수
    {"code": "005930", "name": "x", "price": 100, "date": "2026/08/19"},      # 날짜 형식
    {"code": "005930", "name": "x", "price": "많이", "date": "2026-08-19"},   # 숫자 아님
])
def test_잘못된_입력은_거부한다(bad):
    with pytest.raises(models.RejectedError):
        models.apply_buy(models.empty_state(), bad)


def test_KRX_영숫자_코드도_받는다():
    """2026-08-19 실측: 0126Z0(삼성에피스홀딩스)처럼 숫자만이 아닌 코드가
    코스피 상위종목에도 있다. naver.parse_market_sum 이 이런 코드를 뽑아오는데
    여기서 거부하면 마스터에는 있고 매수 입력만 안 되는 상태가 된다."""
    out = models.apply_buy(models.empty_state(), {
        "code": "0126Z0", "name": "삼성에피스홀딩스", "price": 363500,
        "date": "2026-08-19"})
    assert out["positions"][0]["code"] == "0126Z0"


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


def test_매도_요청이_중복되면_서로_다른_보유를_조용히_닫는다():
    """2026-08-20 보안 리뷰 C1 — 알고 고정해두는 테스트다(고치는 테스트가
    아니다). 매도 payload 에는 대상 id 가 없다({op:"sell", code, price,
    date} 뿐 — app.js onSubmit 참조). 그래서 apply_sell 은 호출될 때마다
    "이 코드의 open 중 가장 오래된 것"을 새로 찾는다(바로 위 테스트가
    확인하는 그 규칙) — 정상 경로(사용자가 같은 종목을 실제로 두 번 사고
    두 번 판 것)에서는 맞는 동작이지만, **같은 제출이 실수로 두 번 나가면**
    (예: Worker 응답이 타임아웃돼 결과를 모르는 채 재시도/폴백한 경우)
    둘째 매도는 거부되지 않고 **다른(첫 번째와 무관한) 보유를 조용히
    닫는다** — 그 보유는 사용자가 이번 제출로 낸 적 없는 가격/날짜로
    종결된다.

    이 위험은 손편집 없이 정상 UI 경로로도 닿는다 — 매수를 잘못 고른 뒤
    "고치기"(amend)로 code 를 다른 보유와 같게 바꾸면 한 코드에 open 이
    2건 이상 남을 수 있다.

    실제 방어는 여기(models.py)가 아니라 app.js 쪽에 있다 — 타임아웃
    (AbortError)을 "network"(자동 폴백 대상)와 분리해 자동 재시도/폴백을
    하지 않는 것(app.js tryWorker의 C1 주석 참조). code 하나만으로 대상을
    고르는 이 계약 자체는 정상 매도에는 맞는 동작이므로 models.py 는
    안 바꾼다 — 이 테스트는 그 결정을 명시적으로 남겨, 미래에 "당연히
    버그겠지"하고 조용히 계약을 바꾸는 일이 없게 한다.
    """
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 240000, "date": "2026-08-01"})
    d = models.apply_buy(d, {
        "code": "005930", "name": "삼성전자", "price": 250000, "date": "2026-08-10"})

    # 첫 매도 — 더 오래된(08-01) 보유가 닫힌다.
    d = models.apply_sell(d, {"code": "005930", "price": 260000, "date": "2026-08-15"})
    closed_after_first = [p for p in d["positions"] if p["status"] == "closed"]
    assert len(closed_after_first) == 1
    assert closed_after_first[0]["buys"][0]["date"] == "2026-08-01"

    # "중복" 매도 — 같은 제출이 실수로 두 번 나간 상황을 흉내낸다. 거부
    # 되지 않는다: id 가 없으므로 이번엔 남은 유일한 open(08-10)이 대신
    # 닫힌다 — apply_sell 은 예외를 내지 않는다(정상 매도와 구분할 방법이
    # 이 함수 안에는 없다).
    d = models.apply_sell(d, {"code": "005930", "price": 999999, "date": "2026-08-16"})
    closed_after_second = [p for p in d["positions"] if p["status"] == "closed"]
    assert len(closed_after_second) == 2

    # 사용자가 08-10 매수분을 위해 낸 적 없는 가격/날짜로 그 기록이 닫혔다
    # — 이게 이 결함의 실제 피해 모양이다.
    second_closed = next(p for p in closed_after_second if p["buys"][0]["date"] == "2026-08-10")
    assert second_closed["exits"][0]["price"] == 999999
    assert second_closed["exits"][0]["date"] == "2026-08-16"


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


# ── 코드리뷰 C1: 최상위 구조가 통째로 이상하면 dropped 에도 남겨야 한다 ──
#
# 고치기 전에는 raw 가 dict 가 아니거나 positions 가 list 가 아니면
# empty_state() 만 조용히 돌려주고 dropped 는 건드리지 않았다. 그러면
# intake.py 의 "dropped 가 있으면 안 쓴다" 가드가 못 보고 지나가서, 기존
# positions.json 전체가 이번 매수 하나로 덮어써지는 사고로 이어진다
# (실측: 배열/키오타/positions가 dict/positions가 null 네 가지 모양 전부).
# 여기서는 "빈 상태가 돌아온다"는 기존 계약(위 test_손상된_파일은_
# 빈_상태로_격리한다)은 그대로 두고, dropped 채널로도 반드시 알려지는지만
# 확인한다.

def test_최상위가_dict가_아니면_dropped에_파일전체_마커를_남긴다():
    dropped = []
    out = models.normalize([{"code": "005930"}], dropped)   # 배열을 통째로 붙여넣은 경우
    assert out == models.empty_state()
    assert len(dropped) == 1
    assert dropped[0]["id"] == "(파일 전체)"


def test_positions가_list가_아니면_dropped에_파일전체_마커를_남긴다():
    dropped = []
    out = models.normalize(
        {"schema": 1, "positions": {"000660": {"code": "000660"}}}, dropped)  # map
    assert out == models.empty_state()
    assert len(dropped) == 1
    assert dropped[0]["id"] == "(파일 전체)"


def test_positions_키가_없어도_dropped에_파일전체_마커를_남긴다():
    dropped = []
    out = models.normalize({"schema": 1, "position": []}, dropped)   # 키 오타
    assert out == models.empty_state()
    assert len(dropped) == 1


def test_positions가_null이어도_dropped에_파일전체_마커를_남긴다():
    dropped = []
    out = models.normalize({"schema": 1, "positions": None}, dropped)
    assert out == models.empty_state()
    assert len(dropped) == 1


def test_dropped를_안_넘기면_최상위_손상도_예전처럼_조용히_격리만_한다():
    # dropped=None(기본값) 호출자는 여전히 아무 예외 없이 빈 상태만 받는다
    # — 이 인자를 넘기지 않는 기존 호출부(있다면)를 깨지 않는다는 확인.
    assert models.normalize([{"code": "005930"}]) == models.empty_state()


# ── 코드리뷰 I3: 중복 id 는 일반 RejectedError 와 다른 클래스로 구분한다ㅡ

def test_중복_id는_AlreadyApplied를_낸다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.AlreadyApplied) as exc_info:
        models.apply_buy(d, {
            "code": "005930", "name": "삼성전자", "price": 250000, "date": "2026-08-19"})
    assert exc_info.value.pid == "20260819-005930"


def test_AlreadyApplied는_RejectedError의_하위클래스라_기존_검사에도_잡힌다():
    # test_같은_종목_같은_날_중복매수는_거부한다 가 pytest.raises(RejectedError)
    # 로 여전히 통과해야 한다는 걸 명시적으로 고정한다.
    assert issubclass(models.AlreadyApplied, models.RejectedError)


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
    out = models.normalize(d)
    # 전체 dict 를 == 로 비교하지 않는다 — 스키마가 계속 자란다(Task 6 이
    # orders/observed_at/auto 를 추가했듯). normalize() 가 apply_buy 는
    # 아직 안 채우는 새 필드에 기본값을 얹는 것 자체는 "이미 있던 값이
    # 그대로다"를 깨지 않으므로, 원래 있던 키만 값이 안 바뀌었는지 본다.
    p, q = out["positions"][0], d["positions"][0]
    for key in q:
        assert p[key] == q[key]


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


# ── 코드리뷰 G2: schema/positions 이외의 최상위 키는 보존된다 ────────────
#
# 고치기 전에는 normalize() 가 마지막에 {"schema": SCHEMA, "positions":
# good} 을 새로 지어서 돌려줘서, positions.json 에 cash/updated_at/
# watchlist 같은(아직 안 쓰지만 손으로 남길 수 있는) 다른 최상위 키가
# 있으면 조용히 사라졌다 — rc=0, "반영했습니다"까지 나가면서.

def test_모르는_최상위_키는_보존된다():
    raw = {"schema": 1, "positions": [
        {"code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-19", "price": 100000}]},
    ], "cash": 5000000, "updated_at": "2026-08-19T15:30:00", "watchlist": ["000660"]}
    out = models.normalize(raw)
    assert out["cash"] == 5000000
    assert out["updated_at"] == "2026-08-19T15:30:00"
    assert out["watchlist"] == ["000660"]
    assert len(out["positions"]) == 1


def test_보존된_최상위_키는_원본과_별개_객체다():
    raw = {"schema": 1, "positions": [], "watchlist": ["000660"]}
    out = models.normalize(raw)
    out["watchlist"].append("005930")
    assert raw["watchlist"] == ["000660"]   # 원본은 안 건드린다


def test_최상위_구조_자체가_이상하면_다른_키_보존_대상이_아니다():
    # positions 가 아예 list 가 아니면(이 케이스는 intake.py 의 최상위
    # 구조 가드가 애초에 normalize() 를 부르기도 전에 막는다) "이게 진짜
    # 데이터인지 오타인지" 판단 근거가 없어 예전처럼 빈 상태만 돌아온다 —
    # G2 의 보존 정책은 schema/positions 가 둘 다 유효할 때만 적용된다.
    raw = {"schema": 1, "positions": "목록아님", "cash": 1000000}
    dropped = []
    out = models.normalize(raw, dropped)
    assert out == models.empty_state()
    assert len(dropped) == 1


# ── 코드리뷰 G3: dropped 에 담기는 non-dict 항목도 dict 모양을 유지한다 ──
#
# 고치기 전에는 positions 배열 항목 자체가 dict 가 아니면(예: 배열이 한
# 겹 더 들어간 손편집 실수) 그 원본을 dropped 에 그대로 넣었다.
# intake.py 는 dropped 항목을 p.get("id") or p.get("code") 로 읽으므로,
# 리스트 같은 non-dict 항목이 들어오면 그 호출부가 AttributeError 로
# 죽어서 의도한 "해석 불가 항목 N건"(rc=3) 대신 예기치 못한 오류로
# 떨어졌다.

def test_배열이_한겹_더_들어간_항목도_dropped에서_dict_모양을_유지한다():
    raw = {"schema": 1, "positions": [["array", "one", "level", "too", "deep"]]}
    dropped = []
    out = models.normalize(raw, dropped)
    assert out["positions"] == []
    assert len(dropped) == 1
    assert isinstance(dropped[0], dict)
    assert dropped[0].get("id") == "(알 수 없음)"   # .get() 이 죽지 않는다


@pytest.mark.parametrize("bad_item", [["array"], "문자열", 123, None, True])
def test_dropped_항목은_어떤_non_dict_타입이든_dict로_감싼다(bad_item):
    dropped = []
    models.normalize({"schema": 1, "positions": [bad_item]}, dropped)
    assert len(dropped) == 1
    assert isinstance(dropped[0], dict)
    assert dropped[0].get("id") == "(알 수 없음)"


# ── Task 15: amend — 기록 고치기 (구현계획.md 참조) ─────────────────────────
#
# amend 는 손편집을 없애기 위한 연산이다. 규칙(설계 그대로):
#  1. 패치다, 교체가 아니다 — 페이로드에 없는 키는 안 바뀐다.
#  2. was 가 저장된 code 와 다르면 거부.
#  3. id 는 (매입일+코드) 로 재계산, 충돌하면 거부.
#  4. exit 는 이미 종결된(exits 가 있는) 기록에만.
#  5. 아무것도 안 바뀌면 AlreadyApplied.
#  6. 값 검증은 buy/sell 과 같은 헬퍼를 쓴다.
# 이 구현이 설계에 추가로 얹은 두 가지(코드리뷰 판단):
#  - code 를 고치면서 name 을 안 주면 거부(이름이 낡은 채로 남는 사고 방지).
#  - 최종 매수일이 최종 매도일보다 늦어지면 거부(apply_sell 의 가드를
#    amend 가 우회하는 뒷문이 되지 않게).


def _닫힌_상태(buy_price=247500, buy_date="2026-08-19",
             sell_price=260000, sell_date="2026-08-25"):
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": buy_price,
        "date": buy_date, "source": "종가베팅", "memo": "눌림"})
    return models.apply_sell(d, {
        "code": "005930", "price": sell_price, "date": sell_date, "reason": "목표가"})


def test_amend은_매입가를_고친다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930",
        "buy": {"price": 250000}})
    p = out["positions"][0]
    assert p["buys"][0]["price"] == 250000
    assert p["buys"][0]["date"] == "2026-08-19"      # 안 건드린 키는 그대로
    assert p["name"] == "삼성전자"                    # 안 건드린 키는 그대로


def test_amend은_지정하지_않은_필드를_보존한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19",
        "source": "종가베팅", "memo": "눌림", "signal_date": "2026-08-18"})
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "memo": "고침"})
    p = out["positions"][0]
    assert p["memo"] == "고침"
    assert p["source"] == "종가베팅"
    assert p["signal_date"] == "2026-08-18"
    assert p["name"] == "삼성전자"


def test_amend은_종결된_기록의_exits를_지우지_않는다():
    # 교체가 아니라 패치라는 규칙 1 을 정면으로 겨눈다 — memo 만 고쳐도
    # exits 가 사라지면 안 된다.
    d = _닫힌_상태()
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "memo": "고침"})
    p = out["positions"][0]
    assert p["exits"] == [{"date": "2026-08-25", "price": 260000, "reason": "목표가"}]
    assert p["status"] == "closed"


def test_amend에서_was가_다르면_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "000660", "memo": "고침"})


def test_amend에서_없는_id는_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260101-999999", "was": "005930", "memo": "고침"})


def test_amend은_id를_재계산한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "buy": {"date": "2026-08-18"}})
    p = out["positions"][0]
    assert p["id"] == "20260818-005930"
    assert p["buys"][0]["date"] == "2026-08-18"


def test_amend은_새_id가_이미_있으면_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    d = models.apply_buy(d, {
        "code": "005930", "name": "삼성전자", "price": 240000, "date": "2026-08-18"})
    # 08-19 기록의 날짜를 08-18 로 옮기면 이미 있는 08-18 기록과 id 가 충돌한다.
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930", "buy": {"date": "2026-08-18"}})


def test_amend은_자기_자신과의_id_충돌은_허용한다():
    # 코드/날짜를 그대로(또는 변화 없는 값으로) 다시 보내도 "이미 있는 id"로
    # 오판해 거부하면 안 된다 — 자기 자신은 충돌 대상에서 빠져야 한다.
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "buy": {"date": "2026-08-19"},
        "memo": "메모"})
    assert out["positions"][0]["id"] == "20260819-005930"
    assert out["positions"][0]["memo"] == "메모"


def test_amend은_열린_기록에_exit을_주면_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930",
            "exit": {"price": 260000}})


def test_amend은_닫힌_기록의_exit을_고칠_수_있다():
    d = _닫힌_상태()
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930",
        "exit": {"price": 265000, "reason": "손절"}})
    e = out["positions"][0]["exits"][0]
    assert e == {"date": "2026-08-25", "price": 265000, "reason": "손절"}


def test_amend은_아무것도_안_바뀌면_AlreadyApplied():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19",
        "memo": "눌림"})
    with pytest.raises(models.AlreadyApplied) as exc_info:
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930", "memo": "눌림"})
    assert exc_info.value.pid == "20260819-005930"


def test_amend은_247500과_247500점0을_같은_값으로_보고_AlreadyApplied():
    # _price 가 정규화한 뒤 비교해야 한다 — 값 비교를 JSON 원본으로 하면
    # 타입만 다른(247500 vs 247500.0) 이 케이스를 "바뀜"으로 오판한다.
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.AlreadyApplied):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930", "buy": {"price": 247500.0}})


def test_amend은_code만_주고_name을_안_주면_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930", "code": "000660"})


def test_amend은_code와_name을_함께_주면_반영되고_id도_바뀐다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930",
        "code": "000660", "name": "SK하이닉스"})
    p = out["positions"][0]
    assert p["code"] == "000660"
    assert p["name"] == "SK하이닉스"
    assert p["id"] == "20260819-000660"


def test_amend은_매수일을_매도일_이후로_옮기면_거부한다():
    d = _닫힌_상태(buy_date="2026-08-19", sell_date="2026-08-25")
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930",
            "buy": {"date": "2026-08-26"}})


def test_amend은_매도일을_매수일_이전으로_옮기면_거부한다():
    d = _닫힌_상태(buy_date="2026-08-19", sell_date="2026-08-25")
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930",
            "exit": {"date": "2026-08-18"}})


def test_amend은_signal_date를_고칠_수_있다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19",
        "signal_date": "2026-08-18"})
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "signal_date": "2026-08-19"})
    assert out["positions"][0]["signal_date"] == "2026-08-19"


def test_amend에서_signal_date가_매입일보다_늦으면_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930", "signal_date": "2026-08-20"})


def test_amend은_adjustments를_건드리지_않는다():
    raw = {"schema": 1, "positions": [
        {"code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-19", "price": 100000}],
         "adjustments": [{"note": "액면분할", "ratio": 5}]},
    ]}
    d = models.normalize(raw)
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "memo": "고침"})
    assert out["positions"][0]["adjustments"] == [{"note": "액면분할", "ratio": 5}]


def test_amend에서_매입가_형식이_틀리면_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930", "buy": {"price": "많이"}})


def test_amend에서_source가_20자를_넘으면_잘라내지_않고_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930", "source": "가" * 21})


def test_amend_결과는_정규화해도_그대로다():
    d = _닫힌_상태()
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "memo": "고침"})
    assert models.normalize(out) == out


# ── Task 15 재검토(F1~F3) — 코드리뷰 재검토에서 지적된 결함 ────────────────
#
# F1: 값 필드가 전부 선택이라(패치니까), 오타난 키는 검증할 대상 자체가
# 없어 조용히 무시되고 "아무것도 안 바뀜" → AlreadyApplied(rc=4) 로 끝난다.
# 가장 흔한 실수(buy:{...} 중첩을 깜빡하고 최상위에 price 를 적는 것)가
# "이미 반영되어 있습니다"로 조용히 닫혀서, amend 가 없애려는 손편집 복귀
# 루프를 오히려 만든다. 화이트리스트로 막는다(intake.main() 을 통한
# 종료코드 확인은 test_intake.py 에 있다).


@pytest.mark.parametrize("bad_req", [
    {"price": 250000},                    # buy 중첩을 깜빡함(가장 흔한 실수)
    {"date": "2026-08-18"},               # 위와 같은 이유, date 버전
    {"buys": {"price": 250000}},          # buy 대신 buys 오타
    {"exlt": {"price": 260000}},          # exit 오타
    {"nmae": "SK하이닉스"},                # name 오타
    {"momo": "고침"},                      # memo 오타
])
def test_amend은_모르는_필드를_조용히_무시하지_않고_거부한다(bad_req):
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    req = {"id": "20260819-005930", "was": "005930"}
    req.update(bad_req)
    with pytest.raises(models.RejectedError, match="모르는 필드"):
        models.apply_amend(d, req)


def test_amend은_buy_안의_모르는_필드를_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError, match="모르는 필드"):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930", "buy": {"pricee": 250000}})


def test_amend은_exit_안의_모르는_필드를_거부한다():
    d = _닫힌_상태()
    with pytest.raises(models.RejectedError, match="모르는 필드"):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930", "exit": {"reasonn": "손절"}})


def test_amend은_알려진_필드는_전부_받는다():
    # 화이트리스트가 실제로 쓰는 모든 필드를 막지 않는지 확인한다.
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "was_price": 247500,
        "code": "005930", "name": "삼성전자", "source": "수동", "memo": "고침",
        "signal_date": "2026-08-19", "buy": {"price": 247500, "date": "2026-08-19"}})
    assert out["positions"][0]["memo"] == "고침"


# F2: normalize() 는 exits 가 *list 인지* 만 보고 원소 모양은 안 보며,
# signal_date 는 아예 검사하지 않는다. apply_buy/apply_sell 은 저장된 이
# 값들을 안 읽어서 지금까지 드러나지 않았는데, amend 의 순서 가드는 이
# 요청이 exit/signal_date 를 안 건드려도(메모만 고쳐도) 항상 이 값들을
# 읽는다 — 손편집이 심어놓은 손상이 TypeError/KeyError 로 그대로 새어나가
# intake.py 의 에러 계약(2/3/4)을 벗어난다.

def _저장된_손상_상태(exits=None, signal_date=None, status="open"):
    raw = {"schema": 1, "positions": [
        {"code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-19", "price": 247500}],
         "status": status, "memo": "눌림"},
    ]}
    if exits is not None:
        raw["positions"][0]["exits"] = exits
        raw["positions"][0]["status"] = "closed"
    if signal_date is not None:
        raw["positions"][0]["signal_date"] = signal_date
    return models.normalize(raw)


@pytest.mark.parametrize("bad_exits", [
    ["garbage"],                              # 원소가 dict 조차 아님
    [{}],                                     # date 키가 없음
    [{"date": 5}],                            # date 가 문자열이 아님
    [{"date": "2026-08-20", "price": "많이"}],  # price 가 숫자가 아님
])
def test_amend에서_저장된_exits가_손상되면_TypeError_대신_거부한다(bad_exits):
    d = _저장된_손상_상태(exits=bad_exits)
    # memo 만 고치는 요청도 exits 순서 가드를 항상 지나가므로 크래시 없이
    # RejectedError(rc=2) 로 끝나야 한다.
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930", "memo": "고침"})


def test_amend에서_저장된_signal_date가_손상되면_TypeError_대신_거부한다():
    d = _저장된_손상_상태(signal_date=20260818)   # 문자열이 아니라 숫자
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930", "memo": "고침"})


def test_amend에서_정상_저장값은_손상_가드에_걸리지_않는다():
    # 위 가드가 정상 케이스까지 막지 않는지 회귀 확인.
    d = _저장된_손상_상태(
        exits=[{"date": "2026-08-25", "price": 260000, "reason": "목표가"}],
        signal_date="2026-08-18")
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "memo": "고침"})
    assert out["positions"][0]["memo"] == "고침"


# 손편집으로 두 기록이 같은 id 를 갖게 됐을 때 "먼저 찾은 걸 고친다"는
# 조용한 오동작 대신 드러나게 거부한다(코드리뷰 minor).
def test_amend은_저장된_id가_중복되면_거부한다():
    raw = {"schema": 1, "positions": [
        {"id": "20260819-005930", "code": "005930", "name": "A",
         "buys": [{"date": "2026-08-19", "price": 100000}]},
        {"id": "20260819-005930", "code": "005930", "name": "B",
         "buys": [{"date": "2026-08-19", "price": 200000}]},
    ]}
    d = models.normalize(raw)
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {"id": "20260819-005930", "was": "005930", "memo": "x"})


# F3: id 는 YYYYMMDD-코드 라서 match["code"] 는 사실 id 접미사 그 자체다 —
# was 단독으로는 "같은 코드, 다른 날짜에 산 기록"을 구분 못 한다. buy.date
# 를 amend 로 옮기면 옛 (날짜+코드) id 가 비고, 그 자리를 정말 새 매수가
# 다시 채우면, 그 사이 떠 있던 낡은 amend 이슈가 was(코드) 만으로 통과해
# 엉뚱한(새) 기록을 고치는 사고로 이어진다. id 로부터 유도되지 않는
# was_price 로 이 재사용 사고를 막는다.

def test_amend에서_was_price가_일치하면_통과한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "was_price": 247500, "memo": "고침"})
    assert out["positions"][0]["memo"] == "고침"


def test_amend에서_was_price가_불일치하면_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930", "was_price": 999999, "memo": "고침"})


def test_amend은_was_price_없이도_동작한다():
    # 하위 호환 — 손으로 쓴 페이로드는 was_price 를 안 보내도 여전히 된다.
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "memo": "고침"})
    assert out["positions"][0]["memo"] == "고침"


def test_amend에서_was_price는_타입만_다른_값도_같은_값으로_본다():
    # was_price 도 _price 를 거쳐 정규화한 뒤 비교한다 — 247500 vs 247500.0.
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    out = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "was_price": 247500.0, "memo": "고침"})
    assert out["positions"][0]["memo"] == "고침"


def test_amend은_was_price로_id_재사용_사고를_막는다():
    # 리뷰에서 실측 재현된 시나리오를 그대로 고정한다.
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    # 원본 기록의 매입일을 08-18 로 옮긴다 — "20260819-005930" id 가 빈다.
    d = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "was_price": 247500,
        "buy": {"date": "2026-08-18"}})
    assert [p["id"] for p in d["positions"]] == ["20260818-005930"]
    # 그 사이 정말 새 매수가 정확히 그 자리(08-19, 005930)를 다시 채운다 —
    # 가격은 원본과 다르다(현실적인 시나리오: 완전히 별개의 매매).
    d = models.apply_buy(d, {
        "code": "005930", "name": "삼성전자", "price": 300000, "date": "2026-08-19"})
    assert sorted(p["id"] for p in d["positions"]) == \
        ["20260818-005930", "20260819-005930"]
    # 낡은 이슈(원본을 겨눴던, was_price=247500)가 이제 도착한다. was(코드)
    # 만 봤다면 그대로 통과해 "새 매수"(가격 300000)를 잘못 고쳤을 것이다.
    with pytest.raises(models.RejectedError):
        models.apply_amend(d, {
            "id": "20260819-005930", "was": "005930", "was_price": 247500,
            "memo": "낡은 이슈"})
    # was_price 를 안 주면(구형 페이로드) 이 사고를 못 막는다는 것도 함께
    # 확인한다 — was_price 가 실제로 방어선 역할을 한다는 대조군.
    d2 = models.apply_amend(d, {
        "id": "20260819-005930", "was": "005930", "memo": "낡은 이슈(was_price 없음)"})
    새매수 = next(p for p in d2["positions"] if p["id"] == "20260819-005930")
    assert 새매수["memo"] == "낡은 이슈(was_price 없음)"
    assert 새매수["buys"][0]["price"] == 300000   # 여전히 "새 매수" 그 기록이다


def test_normalize_가_새_필드에_기본값을_준다():
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [{"date": "2026-08-19", "price": 247500}]}]})
    p = st["positions"][0]
    assert p["auto"] is True          # 기본은 자동 — 예외는 명시적으로만
    assert p["observed_at"] is None   # 옛 기록은 시각을 모른다
    assert p["orders"] == {}          # 아직 주문가가 안 잡힌 기록


def test_normalize_가_저장된_주문가를_보존한다():
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [{"date": "2026-08-19", "price": 247500}],
        "orders": {"buy2": 232650, "buy3": 217800, "customized": True},
        "observed_at": "2026-08-19T15:30", "auto": False}]})
    p = st["positions"][0]
    assert p["orders"]["buy2"] == 232650
    assert p["orders"]["customized"] is True
    assert p["observed_at"] == "2026-08-19T15:30"
    assert p["auto"] is False


def test_orders_가_dict_아니면_격리한다():
    """buys/exits 와 같은 태도 — 있는데 모양이 틀리면 조용히 고치지 않는다."""
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [{"date": "2026-08-19", "price": 247500}],
        "orders": ["망가짐"]}]}, dropped)
    assert st["positions"] == []
    assert len(dropped) == 1


def test_auto_가_불리언_아니면_격리한다():
    """문자열 "false" 는 파이썬에서 참이다 — 예외 지정이 조용히 무시되면
    사용자가 막았다고 믿는 종목이 자동 매매된다."""
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [{"date": "2026-08-19", "price": 247500}],
        "auto": "false"}]}, dropped)
    assert st["positions"] == []
    assert len(dropped) == 1


def test_추가_매수가_있는_기록도_정상_통과한다():
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930",
        "buys": [{"date": "2026-08-19", "price": 100000},
                 {"date": "2026-08-20", "price": 94000, "kind": "buy2",
                  "t": "202608200931", "auto": True}]}]})
    assert len(st["positions"][0]["buys"]) == 2


# ── Task 7: apply_fills — 체결을 기록에 반영 ──────────────────────────────


def _fpos(**over):
    p = {"id": "20260819-005930", "code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-19", "price": 100000}],
         "exits": [], "adjustments": [], "status": "open",
         "source": "종가베팅", "memo": "", "signal_date": None,
         "orders": {"buy2": 94000, "buy3": 88000}, "auto": True,
         "observed_at": "2026-08-19T15:30"}
    p.update(over)
    return {"schema": 1, "positions": [p]}


def test_물타기_체결이_buys에_추가된다():
    st = models.apply_fills(_fpos(), "20260819-005930", [
        {"kind": "buy2", "t": "202608200931", "price": 94000}], "2026-08-20")
    buys = st["positions"][0]["buys"]
    assert len(buys) == 2
    assert buys[1] == {"date": "2026-08-20", "price": 94000, "kind": "buy2",
                       "t": "202608200931", "auto": True}
    assert st["positions"][0]["status"] == "open"


def test_익절_체결이_기록을_닫는다():
    st = models.apply_fills(_fpos(), "20260819-005930", [
        {"kind": "take_profit", "t": "202608200931", "price": 105300}], "2026-08-20")
    p = st["positions"][0]
    assert p["status"] == "closed"
    assert p["exits"] == [{"date": "2026-08-20", "price": 105300,
                           "reason": "자동익절", "t": "202608200931",
                           "auto": True, "session": "KRX",
                           "weighting": "shares", "minute_verified": True}]


def test_한_번에_여러_체결이_순서대로_반영된다():
    """갭하락으로 같은 분에 2차·3차·손절이 함께 나는 경우(설계 §4-1)."""
    st = models.apply_fills(_fpos(), "20260819-005930", [
        {"kind": "buy2", "t": "202608200900", "price": 94000},
        {"kind": "buy3", "t": "202608200900", "price": 88000},
        {"kind": "stop_loss", "t": "202608200900", "price": 85540},
    ], "2026-08-20")
    p = st["positions"][0]
    assert [b["price"] for b in p["buys"]] == [100000, 94000, 88000]
    assert p["status"] == "closed"
    assert p["exits"][0]["reason"] == "자동손절"


def test_분_단위_미확인이면_표시가_남는다():
    """분봉 창(7거래일)을 넘겨 일봉으로만 판정한 경우(설계 §9)."""
    st = models.apply_fills(_fpos(), "20260819-005930", [
        {"kind": "stop_loss", "t": None, "price": 85540}], "2026-08-20",
        minute_verified=False)
    assert st["positions"][0]["exits"][0]["minute_verified"] is False


def test_이미_닫힌_기록에는_반영하지_않는다():
    with pytest.raises(models.RejectedError):
        models.apply_fills(_fpos(status="closed",
                                 exits=[{"date": "2026-08-20", "price": 1,
                                         "reason": ""}]),
                           "20260819-005930",
                           [{"kind": "buy2", "t": "1", "price": 94000}],
                           "2026-08-20")


def test_체결이_없으면_AlreadyApplied():
    """빈 커밋을 만들지 않는다 — apply_amend 와 같은 계약."""
    with pytest.raises(models.AlreadyApplied):
        models.apply_fills(_fpos(), "20260819-005930", [], "2026-08-20")


def test_예외_지정된_기록에는_반영하지_않는다():
    """autofill 이 이미 걸러야 하지만, 여기서도 막는다 — 예외는 사용자가
    '이 종목은 건드리지 마라'고 한 것이라 이중으로 지킨다."""
    with pytest.raises(models.RejectedError):
        models.apply_fills(_fpos(auto=False), "20260819-005930",
                           [{"kind": "buy2", "t": "1", "price": 94000}],
                           "2026-08-20")


# ── Task 6-1: orders 내용 검증 (2026-08-20 리뷰) ──────────────────────────


def _ords(o, first=100000):
    """orders 만 바꿔가며 normalize 를 통과하는지 본다."""
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [{"date": "2026-08-19", "price": first}],
        "orders": o}]}, dropped)
    return st["positions"], dropped


@pytest.mark.parametrize("bad, why", [
    ({"buy2": "94000", "buy3": "88000"}, "문자열 가격 — replay 에서 TypeError"),
    ({"buy3": 88000},                    "buy2 없음 — replay 에서 KeyError"),
    ({"buy2": 94000},                    "buy3 없음 — replay 에서 KeyError"),
    ({"buy2": -5, "buy3": -9},           "음수 — 조용히 안 걸리고 손절도 안 켜짐"),
    ({"buy2": 0, "buy3": 0},             "0원"),
    ({"buy2": 940000, "buy3": 880000},   "1차가보다 높음 — 거래된 적 없는 가격에 체결"),
    ({"buy2": 88000, "buy3": 94000},     "3차가 2차보다 높음 — 순서 뒤집힘"),
    ({"buy2": 94000.5, "buy3": 88000},   "소수 — buys[0] 였다면 거부됐을 값"),
    ({"buy2": True, "buy3": 88000},      "불리언 — 파이썬에서 int 로 통과한다"),
    ({"buy2": 94000, "buy3": 88000, "customized": "yes"}, "customized 가 불리언 아님"),
])
def test_손상된_orders_는_격리한다(bad, why):
    """buys[0].price 와 같은 돈 계산에 쓰이는 값이다 — 같은 수준으로 본다."""
    good, dropped = _ords(bad)
    assert good == [], f"통과하면 안 된다({why}): {bad}"
    assert len(dropped) == 1


@pytest.mark.parametrize("ok", [
    {},                                              # 아직 안 잡힌 기록
    {"buy2": 94000, "buy3": 88000},
    {"buy2": 94000, "buy3": 88000, "customized": True},
    {"buy2": 94000, "buy3": 88000, "customized": False},
])
def test_멀쩡한_orders_는_통과한다(ok):
    good, dropped = _ords(ok)
    assert len(good) == 1 and dropped == []


def test_buys가_없는데_orders가_있으면_격리한다():
    """결함3(2026-08-21 감사, 실측 재현) — 이 테스트는 뒤집혔다.

    이전 이름(`test_buys가_없으면_1차가_대조는_건너뛴다`)이 고정하던 동작은
    "자동매수는 아직 안 산 기록이라 1차가와 대조할 게 없으니, 사다리 자체
    모양(정수·순서)만 보고 통과시킨다"였다. 그런데 buys 가 비었다는 건
    (pending/expired) "1차가 대비 몇 %"라는 사다리의 정의 자체가 성립하지
    않는다는 뜻이다 — 대조를 건너뛸 게 아니라 그 조합 자체를 격리해야
    했다.

    이 기록이 그대로 candidates()/touched() 까지 살아남으면
    orders.take_profit([]) → orders.average([]) 의 ValueError 가
    close.main() 밖으로 새어나간다(감사가 end-to-end 로 재현 —
    tests/test_autofill.py 의 손편집_orders 테스트 참조). 정상 경로로는
    이 모양이 안 생긴다 — apply_watch 는 pending 을 항상 orders={} 로
    만들고, apply_watch_fill 이 orders 를 채우는 순간 status 도 원자적으로
    OPEN 이 된다."""
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [], "status": "pending",
        "watch": {"price": 240000, "date": "2026-08-20", "days": 3},
        "orders": {"buy2": 94000, "buy3": 88000}}]}, dropped)
    assert st["positions"] == []
    assert len(dropped) == 1


# ── Task 9: buys[1:](자동 체결)도 buys[0] 와 같은 기준으로 본다 ──────────


def _buys(second, first_price=100000):
    """buys[1] 만 바꿔가며 normalize 를 통과하는지 본다."""
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930",
        "buys": [{"date": "2026-08-19", "price": first_price}, second],
        "orders": {"buy2": 94000, "buy3": 88000}}]}, dropped)
    return st["positions"], dropped


@pytest.mark.parametrize("bad, why", [
    ({"date": "2026-08-20", "kind": "buy2"},            "price 없음 — filled_prices 가 KeyError"),
    ({"price": 94000, "kind": "buy2"},                  "date 없음"),
    ("망가짐",                                            "dict 아님 — filled_prices 가 TypeError"),
    ({"date": "2026-08-20", "price": "94000"},          "문자열 가격"),
    ({"date": "2026-08-20", "price": 94000.5},          "소수 — buys[0] 였다면 거부됐을 값"),
    ({"date": "2026-08-20", "price": -94000},           "음수"),
    ({"date": "2026-08-20", "price": 0},                "0원"),
    ({"date": "2026-08-20", "price": True},             "불리언 — 파이썬에서 int 로 통과한다"),
    ({"date": "2026-13-99", "price": 94000},            "존재하지 않는 날짜"),
])
def test_손상된_추가매수는_격리한다(bad, why):
    """buys[1:] 는 자동 체결 기록이고, 그 가격이 평균가 계산에 그대로 들어간다.
    buys[0] 와 같은 수준으로 본다 — 실측(2026-08-20): 두 경우는 그날 자동
    체결 전체를 중단시키고, 나머지는 오염된 값이 조용히 평균가에 섞인다."""
    good, dropped = _buys(bad)
    assert good == [], f"통과하면 안 된다({why}): {bad}"
    assert len(dropped) == 1


@pytest.mark.parametrize("ok", [
    {"date": "2026-08-20", "price": 94000},
    {"date": "2026-08-20", "price": 94000, "kind": "buy2",
     "t": "202608200931", "auto": True},
])
def test_멀쩡한_추가매수는_통과한다(ok):
    good, dropped = _buys(ok)
    assert len(good) == 1 and dropped == []


def test_추가매수가_여러_건이어도_전부_본다():
    """3차까지 간 기록 — 마지막 것만 손상돼도 잡아야 한다."""
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930",
        "buys": [{"date": "2026-08-19", "price": 100000},
                 {"date": "2026-08-20", "price": 94000},
                 {"date": "2026-08-21", "price": "88000"}],   # 마지막이 문자열
        "orders": {"buy2": 94000, "buy3": 88000}}]}, dropped)
    assert st["positions"] == []
    assert len(dropped) == 1
    assert isinstance(dropped, list)


# ── Task 11: orders / auto 연산 ────────────────────────────────────────────


def test_매수하면_주문가가_자동으로_붙는다():
    st = models.apply_buy(models.empty_state(), {
        "op": "buy", "code": "005930", "date": "2026-08-20", "price": 100000})
    p = st["positions"][0]
    assert p["orders"] == {"buy2": 94000, "buy3": 88000, "customized": False}
    assert p["auto"] is True


def test_매수_직후의_기록은_normalize_를_그대로_통과한다():
    """apply_buy 가 만든 것을 normalize 가 격리하면 최악이다 — 쓰기는
    성공하는데 다음 읽기에서 사라져, 손편집으로만 복구된다."""
    st = models.apply_buy(models.empty_state(), {
        "op": "buy", "code": "005930", "date": "2026-08-20", "price": 100000})
    dropped = []
    assert len(models.normalize(st, dropped)["positions"]) == 1
    assert dropped == []


@pytest.mark.parametrize("price", [1, 5, 8, 9, 12])
def test_사다리를_만들_수_없는_싼_종목은_매수를_거부한다(price):
    """실측(2026-08-20): 1차가 12원 이하면 반올림 때문에 buy2 >= 1차가 이거나
    buy3 >= buy2 가 되어 _orders_sane 을 통과하지 못한다. 그대로 두면
    apply_buy 는 성공하는데 normalize 가 그 기록을 격리한다 — 쓰기는 됐는데
    화면에서 사라지는, 가장 고약한 모양이다. 문 앞에서 거부한다."""
    with pytest.raises(models.RejectedError):
        models.apply_buy(models.empty_state(), {
            "op": "buy", "code": "005930", "date": "2026-08-20", "price": price})


@pytest.mark.parametrize("price", [13, 100, 247500])
def test_사다리를_만들_수_있으면_매수를_받는다(price):
    st = models.apply_buy(models.empty_state(), {
        "op": "buy", "code": "005930", "date": "2026-08-20", "price": price})
    assert len(st["positions"]) == 1


def test_주문가를_직접_지정하면_customized_가_남는다():
    st = models.apply_buy(models.empty_state(), {
        "op": "buy", "code": "005930", "date": "2026-08-20", "price": 100000})
    st = models.apply_orders(st, {"op": "orders", "id": "20260820-005930",
                                  "was": "005930", "buy2": 95000, "buy3": 90000})
    assert st["positions"][0]["orders"] == {
        "buy2": 95000, "buy3": 90000, "customized": True}


def test_주문가는_1차가보다_낮아야_한다():
    st = models.apply_buy(models.empty_state(), {
        "op": "buy", "code": "005930", "date": "2026-08-20", "price": 100000})
    with pytest.raises(models.RejectedError):
        models.apply_orders(st, {"op": "orders", "id": "20260820-005930",
                                 "was": "005930", "buy2": 110000, "buy3": 90000})


def test_3차가는_2차가보다_낮아야_한다():
    st = models.apply_buy(models.empty_state(), {
        "op": "buy", "code": "005930", "date": "2026-08-20", "price": 100000})
    with pytest.raises(models.RejectedError):
        models.apply_orders(st, {"op": "orders", "id": "20260820-005930",
                                 "was": "005930", "buy2": 90000, "buy3": 95000})


def test_지정한_주문가도_normalize_를_통과한다():
    """apply_orders 가 통과시킨 값을 normalize 가 격리하면 안 된다 —
    두 검증이 어긋나면 저장은 되는데 못 읽는 기록이 생긴다."""
    st = models.apply_buy(models.empty_state(), {
        "op": "buy", "code": "005930", "date": "2026-08-20", "price": 100000})
    st = models.apply_orders(st, {"op": "orders", "id": "20260820-005930",
                                  "was": "005930", "buy2": 95000, "buy3": 90000})
    dropped = []
    assert len(models.normalize(st, dropped)["positions"]) == 1
    assert dropped == []


def test_코드가_다르면_주문가를_못_바꾼다():
    """was 대조 — apply_amend 와 같은 계약. 낡은 목록으로 엉뚱한 기록을
    고치는 걸 막는다."""
    st = models.apply_buy(models.empty_state(), {
        "op": "buy", "code": "005930", "date": "2026-08-20", "price": 100000})
    with pytest.raises(models.RejectedError):
        models.apply_orders(st, {"op": "orders", "id": "20260820-005930",
                                 "was": "000660", "buy2": 90000, "buy3": 85000})


def test_예외_토글():
    st = models.apply_buy(models.empty_state(), {
        "op": "buy", "code": "005930", "date": "2026-08-20", "price": 100000})
    st = models.apply_auto(st, {"op": "auto", "id": "20260820-005930",
                                "was": "005930", "auto": False})
    assert st["positions"][0]["auto"] is False


def test_같은_값으로_토글하면_AlreadyApplied():
    st = models.apply_buy(models.empty_state(), {
        "op": "buy", "code": "005930", "date": "2026-08-20", "price": 100000})
    with pytest.raises(models.AlreadyApplied):
        models.apply_auto(st, {"op": "auto", "id": "20260820-005930",
                               "was": "005930", "auto": True})


def test_auto_가_불리언_아니면_토글을_거부한다():
    """문자열 "false" 는 파이썬에서 참이다 — 조용히 통과시키면 사용자가
    막았다고 믿는 종목이 자동 매매된다."""
    st = models.apply_buy(models.empty_state(), {
        "op": "buy", "code": "005930", "date": "2026-08-20", "price": 100000})
    with pytest.raises(models.RejectedError):
        models.apply_auto(st, {"op": "auto", "id": "20260820-005930",
                               "was": "005930", "auto": "false"})


# ── Task 12: 자동매수 (op: watch) ────────────────────────────────────────


def test_지정가_관찰은_pending_으로_들어간다():
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000, "source": "종가베팅"})
    p = st["positions"][0]
    assert p["status"] == "pending"
    assert p["buys"] == []
    assert p["watch"] == {"price": 240000, "date": "2026-08-20", "days": 5}


def test_pending_은_normalize_를_통과한다():
    """buys 가 비어 있어도 격리되면 안 된다 — 아직 안 산 기록이다."""
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [], "status": "pending",
        "watch": {"price": 240000, "date": "2026-08-20", "days": 3}}]})
    assert len(st["positions"]) == 1


def test_pending_이_아닌데_buys가_비면_여전히_격리한다():
    """pending 예외가 정상 기록의 손상까지 통과시키면 안 된다."""
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [], "status": "open"}]}, dropped)
    assert st["positions"] == []
    assert len(dropped) == 1


def test_pending_이_체결되면_1차_매수가_된다():
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000})
    st = models.apply_watch_fill(st, "20260820-005930", "2026-08-21",
                                 "202608210931")
    p = st["positions"][0]
    assert p["status"] == "open"
    assert p["buys"] == [{"date": "2026-08-21", "price": 240000,
                          "kind": "buy1", "t": "202608210931", "auto": True}]
    assert p["orders"]["customized"] is False
    assert p["observed_at"] == "2026-08-21T09:31"


def test_체결된_pending_의_사다리도_호가에_맞는다():
    """240,000원의 -6%/-12% 는 225,600 / 211,200 인데, 그 가격대 호가단위가
    500원이라 그대로는 주문할 수 없다 — plan() 이 내림 처리한다."""
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000})
    st = models.apply_watch_fill(st, "20260820-005930", "2026-08-21", "202608210931")
    o = st["positions"][0]["orders"]
    assert o == {**orders.plan(240000), "customized": False}
    for k in ("buy2", "buy3"):
        assert o[k] % orders.tick_size(o[k]) == 0


def test_체결된_pending_기록은_normalize_를_그대로_통과한다():
    """apply_watch_fill 이 만든 것을 normalize 가 격리하면 최악이다 —
    체결은 됐는데 다음 읽기에서 사라진다(apply_buy 와 같은 위험)."""
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000})
    st = models.apply_watch_fill(st, "20260820-005930", "2026-08-21", "202608210931")
    dropped = []
    assert len(models.normalize(st, dropped)["positions"]) == 1
    assert dropped == []


@pytest.mark.parametrize("price", [1, 5, 8, 12])
def test_사다리를_만들_수_없는_싼_종목은_관찰도_거부한다(price):
    """apply_buy 와 같은 이유 — 체결 시점에 만들 사다리가 normalize 를
    통과 못 하면, 체결은 되는데 기록이 사라진다. 문 앞에서 막는다."""
    with pytest.raises(models.RejectedError):
        models.apply_watch(models.empty_state(), {
            "op": "watch", "code": "005930", "date": "2026-08-20", "price": price})


def test_이미_체결된_대기주문은_다시_체결되지_않는다():
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000})
    st = models.apply_watch_fill(st, "20260820-005930", "2026-08-21", "202608210931")
    with pytest.raises(models.RejectedError):
        models.apply_watch_fill(st, "20260820-005930", "2026-08-22", "202608220931")


# ── 자동매수의 유효 기간(watch.days) ────────────────────────────────────────
# "며칠 이내에 N원에 닿으면 자동 매수" — 지금까지는 "며칠 이내에"가 빠져
# 있었다. 대기 주문이 영원히 살아있으면, 신호가 다음날 닿은 것과 반년 뒤에
# 닿은 것이 같은 "성공"으로 기록되어 스크리너 비교가 오염된다.


def test_기간을_안_주면_기본값_5이다():
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000})
    assert st["positions"][0]["watch"]["days"] == 5


def test_명시한_기간이_반영된다():
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000, "days": 10})
    assert st["positions"][0]["watch"]["days"] == 10


@pytest.mark.parametrize("days", [0, -1, 61, True, "3", 3.5])
def test_기간이_이상하면_거부한다(days):
    """0/음수/61(상한 초과)/bool(파이썬에서 int 의 서브클래스라 별도로
    막아야 함)/문자열/소수 — 전부 거부한다."""
    with pytest.raises(models.RejectedError):
        models.apply_watch(models.empty_state(), {
            "op": "watch", "code": "005930", "name": "삼성전자",
            "date": "2026-08-20", "price": 240000, "days": days})


@pytest.mark.parametrize("days", [0, -1, 61, True, "5", 3.5])
def test_normalize가_손편집된_기간을_격리한다(days):
    """days 가 **있는데** 모양이 틀리면(0/음수/60초과/bool/문자열/소수) 여전히
    손편집 흔적이다 — 아래 하위호환 테스트(days 가 아예 없는 경우)와 반드시
    구분해야 한다. 이 구분이 무너지면(예: "없거나 틀리면 다 기본값" 으로
    되돌리면) 손편집으로 망가진 값이 조용히 기본 관찰기간으로 둔갑한다."""
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [], "status": "pending",
        "watch": {"price": 240000, "date": "2026-08-20", "days": days}}]}, dropped)
    assert st["positions"] == []
    assert len(dropped) == 1


def test_days_없는_옛_pending_기록은_기본값을_받는다():
    """watch.days(이 브랜치가 추가한 필드) 이전에 만들어진 pending 기록은
    watch 에 {price, date} 두 키만 있고 days 가 아예 없다 — 이걸 손상으로
    보고 격리하면 실제로 기다리고 있던 대기 주문이 화면과 autofill 에서
    통째로 사라진다("옛 pending 기록이 격리되지 않게" CHANGE 2). 없는 것과
    있는데 틀린 것은 다르다 — normalize() 는 후자만 격리하고, 전자는
    기본값을 채워 넣는다(다른 선택 필드에 이미 쓰는 setdefault 관례와 같다)."""
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [], "status": "pending",
        "watch": {"price": 240000, "date": "2026-08-20"}}]}, dropped)   # days 없음
    assert len(st["positions"]) == 1
    assert dropped == []
    assert st["positions"][0]["watch"]["days"] == 5


def test_days_없는_옛_expired_기록도_기본값을_받는다():
    """pending 뿐 아니라 expired 도 never_bought(buys 가 비어 있음) 라서
    같은 검증·같은 기본값 채움을 거친다 — pending 만 다루면 expired 쪽의
    옛 기록은 여전히 격리된다."""
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [], "status": "expired",
        "watch": {"price": 240000, "date": "2026-08-20", "expired_on": "2026-08-26"}}]},
        dropped)   # days 없음
    assert len(st["positions"]) == 1
    assert dropped == []
    assert st["positions"][0]["watch"]["days"] == 5


def test_normalize가_손편집된_가격을_격리한다():
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [], "status": "pending",
        "watch": {"price": -1, "date": "2026-08-20", "days": 3}}]}, dropped)
    assert st["positions"] == []
    assert len(dropped) == 1


def test_normalize가_손편집된_날짜를_격리한다():
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [], "status": "pending",
        "watch": {"price": 240000, "date": "2026-13-40", "days": 3}}]}, dropped)
    assert st["positions"] == []
    assert len(dropped) == 1


def test_normalize가_dict가_아닌_watch를_격리한다():
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [], "status": "pending",
        "watch": [240000, "2026-08-20"]}]}, dropped)
    assert st["positions"] == []
    assert len(dropped) == 1


def test_normalize가_멀쩡한_watch는_통과시킨다():
    dropped = []
    st = models.normalize({"schema": 1, "positions": [{
        "code": "005930", "buys": [], "status": "pending",
        "watch": {"price": 240000, "date": "2026-08-20", "days": 3}}]}, dropped)
    assert len(st["positions"]) == 1
    assert dropped == []


# ── apply_expire ────────────────────────────────────────────────────────

def test_기한이_지나면_expired로_바뀐다():
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000, "days": 3})
    pid = "20260820-005930"
    out = models.apply_expire(st, pid, "2026-08-26")
    p = out["positions"][0]
    assert p["status"] == "expired"
    assert p["buys"] == []
    assert p["watch"]["expired_on"] == "2026-08-26"
    # price/date/days 는 그대로 남는다 — "무엇을 놓쳤는지"가 계속 읽혀야 한다
    assert p["watch"]["price"] == 240000
    assert p["watch"]["days"] == 3


def test_expired_기록은_normalize를_통과한다():
    """apply_expire 가 만든 것을 normalize 가 격리하면 안 된다 — 만료된
    기록이 다음 읽기에서 사라져 "그 기간엔 없었다는 사실"이 지워진다."""
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000})
    out = models.apply_expire(st, "20260820-005930", "2026-08-26")
    dropped = []
    assert len(models.normalize(out, dropped)["positions"]) == 1
    assert dropped == []


def test_pending이_아니면_만료를_거부한다():
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000})
    st = models.apply_watch_fill(st, "20260820-005930", "2026-08-21", "202608210931")
    with pytest.raises(models.RejectedError):
        models.apply_expire(st, "20260820-005930", "2026-08-26")


def test_이미_만료된_기록을_다시_만료시키면_거부한다():
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000})
    st = models.apply_expire(st, "20260820-005930", "2026-08-26")
    with pytest.raises(models.RejectedError):
        models.apply_expire(st, "20260820-005930", "2026-08-27")


def test_만료_대상이_없으면_거부한다():
    with pytest.raises(models.RejectedError):
        models.apply_expire(models.empty_state(), "20260820-005930", "2026-08-26")


# ── CHANGE 3: apply_delete — 이 시스템의 유일한 파괴적 연산 ──────────────────
# 지금까지 스퍼리어스한(있어서는 안 될) 기록을 지우는 유일한 경로는
# 손편집이었다(apply_amend 독스트링의 "잔여 한계" 참조). was_price 를
# apply_amend 와 달리 여기서는 필수로 둔다 — 이유는 apply_delete 자체의
# 독스트링에 있다: id 재사용 사고를 amend 는 감수하지만(잘못 고쳐도
# 되돌릴 수 있다) delete 는 감수하지 않는다(지운 건 되돌릴 수 없다).
# AlreadyApplied 케이스가 없다는 것도 같은 이유다 — "이미 지워짐"과
# "애초에 없었음"을 이 함수가 구분할 방법이 없어, 조용히 성공 취급하면
# 엉뚱한 id 를 겨눈 삭제 요청도 "성공"으로 보인다.


def test_delete는_기록을_완전히_지운다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    out = models.apply_delete(d, {
        "op": "delete", "id": "20260819-005930", "was": "005930", "was_price": 247500})
    assert out["positions"] == []


def test_delete에서_was가_다르면_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError):
        models.apply_delete(d, {
            "op": "delete", "id": "20260819-005930", "was": "000660", "was_price": 247500})


def test_delete에서_was_price가_불일치하면_거부한다():
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError):
        models.apply_delete(d, {
            "op": "delete", "id": "20260819-005930", "was": "005930", "was_price": 999999})


def test_delete에서_was_price가_없으면_거부한다():
    """amend 와 달리 delete 는 was_price 가 선택이 아니라 필수다 — 삭제는
    되돌릴 수 없어 id 재사용 사고를 amend 처럼 감수할 수 없다(apply_delete
    독스트링 참조)."""
    d = models.apply_buy(models.empty_state(), {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19"})
    with pytest.raises(models.RejectedError):
        models.apply_delete(d, {
            "op": "delete", "id": "20260819-005930", "was": "005930"})


def test_delete에서_없는_id는_거부한다():
    with pytest.raises(models.RejectedError):
        models.apply_delete(models.empty_state(), {
            "op": "delete", "id": "20260101-999999", "was": "005930", "was_price": 100000})


def test_delete는_pending_기록을_watch_price로_대조해_지운다():
    """pending 은 buys 가 비어 있다 — 대조할 가격이 buys[0].price 가 아니라
    watch.price 다."""
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000})
    out = models.apply_delete(st, {
        "op": "delete", "id": "20260820-005930", "was": "005930", "was_price": 240000})
    assert out["positions"] == []


def test_delete는_pending_기록에서_watch_price가_불일치하면_거부한다():
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000})
    with pytest.raises(models.RejectedError):
        models.apply_delete(st, {
            "op": "delete", "id": "20260820-005930", "was": "005930", "was_price": 999999})


def test_delete는_expired_기록도_watch_price로_대조해_지운다():
    """expired 도 pending 과 마찬가지로 buys 가 비어 있다 — 같은 대조를 쓴다."""
    st = models.apply_watch(models.empty_state(), {
        "op": "watch", "code": "005930", "name": "삼성전자",
        "date": "2026-08-20", "price": 240000})
    st = models.apply_expire(st, "20260820-005930", "2026-08-26")
    out = models.apply_delete(st, {
        "op": "delete", "id": "20260820-005930", "was": "005930", "was_price": 240000})
    assert out["positions"] == []


def test_delete는_다른_기록을_바이트단위로_그대로_둔다():
    """대상만 지우고 나머지 기록은 완전히 그대로다 — test_intake.py 의
    test_amend은_여러_기록_중_대상만_고치고_형제는_바이트단위로_그대로다
    와 같은 방식(정규화된 원본과 통째로 == 비교)을 apply_delete 에도 쓴다."""
    import copy as _copy
    d = models.apply_buy(models.empty_state(), {
        "code": "000660", "name": "SK하이닉스", "price": 200000, "date": "2026-08-01",
        "memo": "메모1"})
    d = models.apply_buy(d, {
        "code": "005930", "name": "삼성전자", "price": 247500, "date": "2026-08-19",
        "source": "종가베팅", "memo": "눌림", "signal_date": "2026-08-18"})
    d = models.apply_buy(d, {
        "code": "035420", "name": "NAVER", "price": 210000, "date": "2026-08-05"})
    원본 = _copy.deepcopy(d)

    out = models.apply_delete(d, {
        "op": "delete", "id": "20260819-005930", "was": "005930", "was_price": 247500})

    by_id = {p["id"]: p for p in out["positions"]}
    assert len(by_id) == 2
    assert "20260819-005930" not in by_id

    정규화된_원본 = {p["id"]: p for p in models.normalize(원본)["positions"]}
    for sib_id in ("20260801-000660", "20260805-035420"):
        assert by_id[sib_id] == 정규화된_원본[sib_id]   # 형제 기록은 완전히 그대로
