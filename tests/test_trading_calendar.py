# -*- coding: utf-8 -*-
from scripts import trading_calendar as cal

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


def test_빠진_날짜는_오래된_것부터_순서대로():
    """전부 빠졌을 때만 순서가 드러난다 — 원소 하나짜리 결과로는 뒤집혀도 통과한다.

    docstring 이 약속하는 '오래된 것부터' 를 실제로 고정한다. close.py 는
    이 순서대로 과거 쪽부터 백필한다.
    """
    assert cal.missing(DAYS, 5, set()) == DAYS


def test_달력이_짧으면_경고한다():
    assert cal.too_short(DAYS, need=30) is True
    assert cal.too_short(DAYS * 10, need=30) is False


def test_빈_달력():
    """빈 달력은 too_short() 가 걸러주는 게 정상 경로지만, 나머지 함수들도
    각자 정직하게 응답해야 한다 — 예외를 던지거나 엉뚱한 값을 주지 않는다.
    """
    assert cal.held_days([], "2026-08-13", "2026-08-19") is None
    assert cal.recent([], 5) == []
    assert cal.missing([], 30, {"2026-08-19"}) == []
    assert cal.too_short([], need=30) is True


# ── watch_deadline: 자동매수의 만료일 ──────────────────────────────────
# 2026-08-20(목), 21(금), 22-23 은 주말이라 달력에 없다, 24(월), 25(화).
WATCH_DAYS = ["2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25", "2026-08-26"]


def test_사흘_기한은_등록일_다음날부터_센다():
    """등록일(목) 당일은 세지 않는다 — 마감 후 등록이라 이미 지난 하루다.
    금·월·화가 유효(주말은 거래일이 아니라 자동으로 건너뛴다) → 화요일이 마감일.
    """
    assert cal.watch_deadline(WATCH_DAYS, "2026-08-20", 3) == "2026-08-25"


def test_주말을_건너뛴다():
    """days=3 은 달력일로 금·토·일(=금요일 하루만 거래일)이 아니라
    거래일로 금·월·화다 — 이 구분이 이 함수가 존재하는 이유 그 자체다."""
    deadline = cal.watch_deadline(WATCH_DAYS, "2026-08-20", 3)
    assert deadline != "2026-08-22"   # 토요일 — 애초에 달력에 없다
    assert deadline == "2026-08-25"


def test_하루_기한():
    assert cal.watch_deadline(WATCH_DAYS, "2026-08-20", 1) == "2026-08-21"


def test_등록일이_달력_밖이면_None():
    """만료를 판단할 근거가 없다 — 클램프하지 않는다(held_days 와 같은 태도)."""
    assert cal.watch_deadline(WATCH_DAYS, "2026-01-02", 3) is None


def test_등록일_뒤로_n거래일이_아직_안_쌓였으면_None():
    """마지막 날짜(08-26)에서 3거래일을 요구하면 달력이 그만큼 안 쌓였다 —
    아직 만료를 판단할 수 없다는 뜻이지, 만료됐다는 뜻이 아니다."""
    assert cal.watch_deadline(WATCH_DAYS, "2026-08-26", 3) is None
    assert cal.watch_deadline(WATCH_DAYS, "2026-08-25", 2) is None  # 딱 하나 부족(idx 3+2=5, len=5)


def test_마지막_날짜에_등록해도_n이_0을_넘으면_None():
    assert cal.watch_deadline(WATCH_DAYS, "2026-08-26", 1) is None


def test_빈_달력에서는_None():
    assert cal.watch_deadline([], "2026-08-20", 3) is None


# ── watch_date_unreachable: 결함6(2026-08-21 무동작 감사) — 비거래일 등록 감지 ──
# watch_deadline() 의 None 이 "아직 마감일 아님"(정상, self-healing)과
# "watch_date 자체가 거래일이 아님"(영구적)을 뭉개는 것을 이 함수가 가른다.


def test_비거래일_등록은_감지된다():
    """08-22(토)는 WATCH_DAYS 에 없고, 달력은 그 이후로도(08-24~26) 거래일을
    담고 있다 — 앞으로도 절대 안 나타날 날짜라고 확신할 수 있다."""
    assert "2026-08-22" not in WATCH_DAYS
    assert cal.watch_date_unreachable(WATCH_DAYS, "2026-08-22") is True


def test_거래일_등록은_불가능으로_판정되지_않는다():
    assert cal.watch_date_unreachable(WATCH_DAYS, "2026-08-20") is False


def test_달력의_마지막_날짜와_같으면_판단을_보류한다():
    """이후로 며칠이나 지나왔는지 근거가 없는 경계 — 방어적으로 다룬다."""
    assert cal.watch_date_unreachable(WATCH_DAYS, "2026-08-26") is False


def test_달력보다_미래_날짜는_판단을_보류한다():
    """아직 달력이 그 날짜까지 안 왔을 뿐일 수 있다 — 성급하게 단정하지 않는다."""
    assert cal.watch_date_unreachable(WATCH_DAYS, "2026-08-27") is False
    assert cal.watch_date_unreachable(WATCH_DAYS, "2026-12-31") is False


def test_watch_date_unreachable_빈_달력에서는_판단_보류():
    assert cal.watch_date_unreachable([], "2026-08-20") is False
