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
