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
    도는 cron 의 두 번째 실행이 소급 익절을 낸다(모듈 독스트링 참조).

    관측(08-18 15:30) 뒤 다음 거래일(08-19 10:00)에 2차가 체결된 정상 경로.
    """
    p = _pos(observed_at="2026-08-18T15:30",
             buys=[{"date": "2026-08-18", "price": 100000},
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


def test_체결_시각이_관측보다_이르면_관측_시각을_쓴다():
    """정상 경로로는 불가능한 모양(관측 전에 체결될 수 없다)이지만 손편집으로
    생긴다. 그때 체결 시각을 그대로 쓰면 **관측 이전 분봉을 재생**하게 되어
    orders.replay 의 since 가드가 막으려던 소급 체결이 열린다.

    날짜만 비교하는 변형이 정확히 여기서 깨진다 — 그래서 단순 max 를 쓴다.
    """
    p = _pos(observed_at="2026-08-20T10:00",
             buys=[{"date": "2026-08-20", "price": 100000},
                   {"date": "2026-08-20", "price": 94000,
                    "kind": "buy2", "t": "202608200900", "auto": True}])
    assert autofill.since_for(p) == "202608201000"


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


# ── run() ───────────────────────────────────────────────────────────────

class FakeGH:
    """gh 모듈 대역. 쓰기를 가로채 무엇이 쓰였는지 본다."""

    def __init__(self, state):
        self.state = state
        self.writes = []
        self.fail_write = False

    def read_json(self, path, default=None, strict=False):
        return self.state, "sha-1"

    def write_json(self, path, body, sha, message):
        if self.fail_write:
            raise RuntimeError("409 충돌")
        self.writes.append((path, body, message))
        self.state = body


def test_체결되면_positions에_쓴다(monkeypatch):
    fake = FakeGH(_state())
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: [{"t": "202608200931",
                                            "high": 106000, "low": 99000}])
    rc = autofill.run({"005930": {"20260820": {"high": 106000, "low": 99000}}},
                      "2026-08-20", [])
    assert rc == 0
    assert len(fake.writes) == 1
    p = fake.writes[0][1]["positions"][0]
    assert p["status"] == "closed"
    assert p["exits"][0]["reason"] == "자동익절"
    assert p["exits"][0]["price"] == 105300


def test_안_닿으면_분봉을_요청하지도_쓰지도_않는다(monkeypatch, capsys):
    calls = []
    fake = FakeGH(_state())
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: calls.append(code) or [])
    rc = autofill.run({"005930": {"20260820": {"high": 101000, "low": 99000}}},
                      "2026-08-20", [])
    assert rc == 0
    assert calls == []
    assert fake.writes == []
    # 결함4: 정상 무터치는 조용해야 한다 — 매번 나는 일까지 로그로 찍으면
    # 진짜 봐야 할 신호(판정 불가·불일치)가 소음에 묻힌다.
    assert "[경고]" not in capsys.readouterr().out


def test_이미_그날_체결된_구간은_다시_재생하지_않는다(monkeypatch):
    """하루 두 번 도는 cron 의 두 번째 실행 — 모듈 독스트링의 그 사고.

    2차가 10:00 에 체결돼 있는 상태로 그날을 다시 처리한다. 09:30 분봉의
    고가가 (내려간) 익절선을 넘지만, since 가 10:00 이라 잘려서 체결이
    나면 안 된다.
    """
    p = _pos(observed_at="2026-08-18T15:30",
             buys=[{"date": "2026-08-18", "price": 100000},
                   {"date": "2026-08-19", "price": 94000,
                    "kind": "buy2", "t": "202608191000", "auto": True}])
    fake = FakeGH({"schema": 1, "positions": [p]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute", lambda code, day: [
        {"t": "202608190900", "high": 101000, "low": 100000},
        {"t": "202608190930", "high": 103000, "low": 101000},
        {"t": "202608191000", "high":  99000, "low":  94000},
        {"t": "202608191530", "high":  95000, "low":  94000},
    ])
    rc = autofill.run({"005930": {"20260819": {"high": 103000, "low": 94000}}},
                      "2026-08-19", [])
    assert rc == 0
    assert fake.writes == [], f"소급 체결이 났다: {fake.writes}"


def test_분봉_조회_실패는_그_종목만_건너뛴다(monkeypatch):
    """한 종목 실패가 나머지의 체결까지 막으면 안 된다. 읽기 실패라
    종료코드도 더럽히지 않는다 — close.py 의 관례와 같다."""
    from scripts import naver as naver_mod

    def boom(code, day):
        raise naver_mod.EmptyParseError("분봉 결과 0건")

    fake = FakeGH(_state())
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute", boom)
    rc = autofill.run({"005930": {"20260820": {"high": 106000, "low": 99000}}},
                      "2026-08-20", [])
    assert fake.writes == []
    assert rc == 0


def test_쓰기_실패는_종료코드에_반영된다(monkeypatch):
    fake = FakeGH(_state())
    fake.fail_write = True
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: [{"t": "202608200931",
                                            "high": 106000, "low": 99000}])
    rc = autofill.run({"005930": {"20260820": {"high": 106000, "low": 99000}}},
                      "2026-08-20", [])
    assert rc == 1


def test_손상된_파일에는_아무것도_쓰지_않는다(monkeypatch):
    """positions.json 은 다시 만들 수 없다 — intake·close 와 같은 태도."""
    fake = FakeGH({"schema": 1, "positions": [{"code": "망가짐"}]})
    monkeypatch.setattr(autofill, "gh", fake)
    rc = autofill.run({}, "2026-08-20", [])
    assert fake.writes == []
    assert rc == 0


def test_저장된_사다리를_쓴다(monkeypatch):
    """사용자가 손으로 고친 사다리(customized)를 무시하면 안 된다."""
    fake = FakeGH(_state(orders={"buy2": 95000, "buy3": 90000,
                                 "customized": True}))
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: [{"t": "202608200931",
                                            "high": 99000, "low": 94000}])
    rc = autofill.run({"005930": {"20260820": {"high": 99000, "low": 94000}}},
                      "2026-08-20", [])
    assert rc == 0
    p = fake.writes[0][1]["positions"][0]
    assert p["buys"][1]["price"] == 95000   # 기본값 94,000 이 아니다


# ── Task 12: 자동매수(pending) — 목표가에 닿으면 1차 매수로 체결된다 ─────


def _pending(**over):
    p = {"id": "20260820-005930", "code": "005930", "name": "삼성전자",
         "buys": [], "exits": [], "adjustments": [], "status": "pending",
         "source": "종가베팅", "memo": "", "signal_date": None,
         "watch": {"price": 240000, "date": "2026-08-20", "days": 3},
         "orders": {}, "auto": True, "observed_at": None}
    p.update(over)
    return p


# watch.date="2026-08-20"(목), days=3 → 유효일 금(21)·월(24)·화(25), 마감일 25일.
# 22-23 은 주말이라 달력에 없다(거래일로 세라는 규약을 그대로 반영).
CAL = ["2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25", "2026-08-26"]


def test_지정가에_닿으면_체결하고_같은_실행에서_사다리까지_이어간다(monkeypatch):
    """같은 날 매수·매도가 나는 경우를 다음 실행으로 미루면 그만큼 분봉
    창(7거래일)을 까먹는다."""
    fake = FakeGH({"schema": 1, "positions": [_pending()]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute", lambda code, day: [
        {"t": "202608210900", "high": 245000, "low": 241000},
        {"t": "202608210931", "high": 241000, "low": 239000},   # 240,000 터치
        {"t": "202608211000", "high": 242000, "low": 240000},
    ])
    rc = autofill.run({"005930": {"20260821": {"high": 245000, "low": 239000}}},
                      "2026-08-21", CAL)
    assert rc == 0
    p = fake.state["positions"][0]
    assert p["status"] == "open"
    assert p["buys"][0]["price"] == 240000
    assert p["buys"][0]["t"] == "202608210931"
    assert p["observed_at"] == "2026-08-21T09:31"


def test_지정가에_안_닿으면_pending_그대로다(monkeypatch, capsys):
    calls = []
    fake = FakeGH({"schema": 1, "positions": [_pending()]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: calls.append(code) or [])
    rc = autofill.run({"005930": {"20260821": {"high": 250000, "low": 245000}}},
                      "2026-08-21", CAL)
    assert rc == 0
    assert calls == [], "일봉 저가가 목표가 위인데 분봉을 받았다"
    assert fake.writes == []
    # 결함4: 정상 무터치는 조용해야 한다.
    assert "[경고]" not in capsys.readouterr().out


def test_예외_지정된_pending_은_체결되지_않는다(monkeypatch):
    """예외는 자동매도뿐 아니라 자동매수도 멈춘다(설계 §8)."""
    fake = FakeGH({"schema": 1, "positions": [_pending(auto=False)]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute", lambda code, day: [
        {"t": "202608210931", "high": 241000, "low": 239000}])
    rc = autofill.run({"005930": {"20260821": {"high": 245000, "low": 239000}}},
                      "2026-08-21", CAL)
    assert rc == 0
    assert fake.writes == []


# ── 자동매수의 유효 기간(watch.days) ────────────────────────────────────────
# "며칠 이내에 N원에 닿으면 자동 매수" — "며칠 이내에"를 채운다. 대기
# 주문이 영원히 살아있으면, 다음날 닿은 신호와 반년 뒤 닿은 신호가 같은
# "성공"으로 기록되어 스크리너 비교가 오염된다.


def test_마감일_당일에_닿으면_체결하고_만료하지_않는다(monkeypatch):
    """마감일(=CAL 에서 2026-08-25)은 아직 유효한 하루다 — 가격이 먼저다."""
    fake = FakeGH({"schema": 1, "positions": [_pending()]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute", lambda code, day: [
        {"t": "202608250931", "high": 241000, "low": 239000},   # 240,000 터치
    ])
    rc = autofill.run({"005930": {"20260825": {"high": 245000, "low": 239000}}},
                      "2026-08-25", CAL)
    assert rc == 0
    p = fake.state["positions"][0]
    assert p["status"] == "open", "마감일 당일 체결인데 만료로 처리됐다"
    assert p["buys"][0]["price"] == 240000


def test_마감일을_하루_넘기면_만료된다(monkeypatch):
    """가격이 안 닿았고, 오늘(2026-08-26)이 마감일(2026-08-25)을 지났다."""
    calls = []
    fake = FakeGH({"schema": 1, "positions": [_pending()]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: calls.append(code) or [])
    rc = autofill.run({"005930": {"20260826": {"high": 250000, "low": 245000}}},
                      "2026-08-26", CAL)
    assert rc == 0
    assert calls == [], "만료 대상인데 분봉을 요청했다 — 가격을 볼 필요가 없다"
    assert len(fake.writes) == 1
    p = fake.state["positions"][0]
    assert p["status"] == "expired"
    assert p["watch"]["expired_on"] == "2026-08-26"
    assert p["buys"] == []


def test_마감일이_지나면_그날_가격이_닿아도_만료한다(monkeypatch):
    """기한을 넘긴 뒤에는 그날 우연히 닿아도 체결이 아니다 — "그 기간 안에
    온 신호"가 아니기 때문이다(지시문 결정 3). 만료 판정이 가격 판정보다
    우선해야 한다(마감일 당일은 반대 — 위 테스트와 대칭)."""
    fake = FakeGH({"schema": 1, "positions": [_pending()]})
    monkeypatch.setattr(autofill, "gh", fake)
    calls = []
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: calls.append(code) or [])
    rc = autofill.run({"005930": {"20260826": {"high": 245000, "low": 239000}}},
                      "2026-08-26", CAL)   # 저가 239,000 — 240,000 에 닿았다
    assert rc == 0
    assert calls == [], "만료가 가격 확인보다 먼저 결정돼야 한다"
    p = fake.state["positions"][0]
    assert p["status"] == "expired", "닿았지만 이미 기한을 넘겨 만료여야 한다"


def test_달력이_등록일을_모르면_만료시키지_않는다(monkeypatch):
    """watch.date 가 달력 밖 — 만료를 판단할 근거가 없다. 클램프하지
    않는다(watch_deadline docstring)."""
    fake = FakeGH({"schema": 1, "positions": [_pending()]})
    monkeypatch.setattr(autofill, "gh", fake)
    rc = autofill.run({"005930": {"20260930": {"high": 250000, "low": 245000}}},
                      "2026-09-30", [])   # 빈 달력
    assert rc == 0
    assert fake.writes == []
    assert fake.state["positions"][0]["status"] == "pending"


def test_달력이_짧으면_만료시키지_않는다(monkeypatch):
    """등록일은 달력에 있지만 그 뒤로 n거래일이 아직 안 쌓였다."""
    fake = FakeGH({"schema": 1, "positions": [_pending()]})
    monkeypatch.setattr(autofill, "gh", fake)
    rc = autofill.run({"005930": {"20260821": {"high": 250000, "low": 245000}}},
                      "2026-08-21", ["2026-08-20", "2026-08-21"])   # 3거래일 부족
    assert rc == 0
    assert fake.writes == []
    assert fake.state["positions"][0]["status"] == "pending"


def test_이미_만료된_기록은_나중에_닿아도_다시_체결되지_않는다(monkeypatch):
    expired = _pending(status="expired",
                       watch={"price": 240000, "date": "2026-08-20", "days": 3,
                              "expired_on": "2026-08-26"})
    fake = FakeGH({"schema": 1, "positions": [expired]})
    monkeypatch.setattr(autofill, "gh", fake)
    called = []
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: called.append(code) or [
                            {"t": "202608270931", "high": 241000, "low": 239000}])
    rc = autofill.run({"005930": {"20260827": {"high": 245000, "low": 239000}}},
                      "2026-08-27", CAL)
    assert rc == 0
    assert called == [], "이미 만료된 기록인데 분봉을 요청했다"
    assert fake.writes == []


def test_만료_쓰기_실패는_종료코드에_반영된다(monkeypatch):
    fake = FakeGH({"schema": 1, "positions": [_pending()]})
    fake.fail_write = True
    monkeypatch.setattr(autofill, "gh", fake)
    rc = autofill.run({"005930": {"20260826": {"high": 250000, "low": 245000}}},
                      "2026-08-26", CAL)
    assert rc == 1


def test_대기_종목의_일봉이_없으면_자동매수가_안_걸린다(monkeypatch, capsys):
    """close.py 가 대기 종목의 일봉을 안 받아오던 실측 사고(2026-08-21)를
    못박는다. bars 에 그 코드가 없으면 run() 은 `bar is None` 으로 조용히
    건너뛴다 — 오류도, 경고도 없이 **자동매수가 영영 안 걸린다.**

    이 테스트는 "일봉이 없으면 안 걸린다"는 사실 자체를 고정한다. 그래서
    close.py 가 quotes.live_codes 로 대기 종목까지 받아오는 것이 왜
    필수인지가 코드로 남는다.

    결함4(2026-08-21 감사): 지금은 이 상황이 더 이상 "조용히" 안 걸리지
    않는다 — "판정 불가"를 로그로 남긴다. 바로 이 모양의 결손(일봉이
    안 온 것)이 이 기능의 수명 내내 안 들켰던 이유이기도 하다.
    """
    fake = FakeGH({"schema": 1, "positions": [_pending()]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: [{"t": "202608210931",
                                            "high": 241000, "low": 239000}])
    # 일봉을 아예 안 넘긴다 — close.py 가 대기 종목을 빠뜨린 상태 그대로
    rc = autofill.run({}, "2026-08-21", ["2026-08-20", "2026-08-21"])
    assert rc == 0
    assert fake.writes == [], "일봉이 없는데 체결됐다"
    assert fake.state["positions"][0]["status"] == "pending"
    out = capsys.readouterr().out
    assert "일봉 없음" in out
    assert "005930" in out


def test_대기_종목의_일봉이_있으면_자동매수가_걸린다(monkeypatch):
    """위 테스트의 짝 — 일봉만 있으면 정상 체결된다. 둘을 같이 둬야
    '안 걸리는 게 정상'과 '고쳐야 할 결손'이 구분된다."""
    fake = FakeGH({"schema": 1, "positions": [_pending()]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: [{"t": "202608210931",
                                            "high": 241000, "low": 239000}])
    rc = autofill.run({"005930": {"20260821": {"high": 245000, "low": 239000}}},
                      "2026-08-21", ["2026-08-20", "2026-08-21"])
    assert rc == 0
    assert fake.state["positions"][0]["status"] == "open"


# ── 결함1(2026-08-21 감사): 등록일 당일은 소급 체결되지 않는다 ───────────
#
# 실측: 2026-08-21T15:41 KST 에 등록된 워치(7900원)가 같은 날 09:00
# 분봉으로 체결됐다 — 등록보다 6시간 41분 앞선 시각이다. watch_deadline()
# 은 이미 등록일 당일을 안 세고 다음 거래일부터 만료 기한을 센다 — 체결
# 판정도 같은 기준(다음 거래일부터)을 써야 두 절반이 어긋나지 않는다.


def test_등록일_당일에는_체결되지_않는다(monkeypatch, capsys):
    """워치는 장 마감 뒤에 등록되므로, 등록일 당일의 분봉은 그 워치가
    존재하기 전 시각이다. 등록일 당일 저가가 목표가 밑으로 찍혀도 그건
    소급 체결이다 — 실측 재현: 같은 날 09:00 분봉으로 15:41 등록 워치가
    체결됐었다."""
    calls = []
    fake = FakeGH({"schema": 1, "positions": [_pending()]})   # watch.date=2026-08-20
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: calls.append(code) or [
                            {"t": "202608200900", "high": 241000, "low": 239000}])
    rc = autofill.run({"005930": {"20260820": {"high": 245000, "low": 239000}}},
                      "2026-08-20", CAL)   # day == watch.date — 등록일 당일
    assert rc == 0
    assert calls == [], "등록일 당일인데 분봉을 요청했다 — 체결 판정 자체를 하면 안 된다"
    assert fake.writes == []
    assert fake.state["positions"][0]["status"] == "pending"
    # 등록일 당일 스킵은 거의 매일 벌어지는 정상 상황이다(스크리너가 전부
    # 장 마감 후에 등록하므로) — 조용해야 한다(결함4 원칙과 같다).
    assert "[경고]" not in capsys.readouterr().out


def test_등록일_다음_거래일부터는_정상_체결된다(monkeypatch):
    """위 테스트의 짝 — 다음 거래일부터는 정상적으로 체결된다."""
    fake = FakeGH({"schema": 1, "positions": [_pending()]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute", lambda code, day: [
        {"t": "202608210931", "high": 241000, "low": 239000}])
    rc = autofill.run({"005930": {"20260821": {"high": 245000, "low": 239000}}},
                      "2026-08-21", CAL)   # CAL[1] — 등록일(20일) 다음 거래일
    assert rc == 0
    assert fake.state["positions"][0]["status"] == "open"


# ── 결함2(2026-08-21 감사): 분봉 창(약 7거래일)을 넘긴 날은 일봉만으로 확정 ──
#
# naver.fetch_minute 은 최근 약 7거래일만 응답한다 — 그보다 오래된 날짜는
# 영구히 빈 응답이다(재시도로 해결 안 됨). 캐치업이 그 창을 넘긴 날짜를
# 처리해야 할 때, 일봉 하나를 "분봉 하나"처럼 재생해 확정하고
# minute_verified=False 를 남긴다(설계 §9).

DAYS10 = ["2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24",
          "2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"]


def test_분봉_창을_넘긴_날은_사다리_체결도_일봉만으로_확정한다(monkeypatch):
    """분봉 창(약 7거래일)을 넘긴 날짜는 fetch_minute 을 시도조차 하지
    않는다 — 시도해도 영구히 빈 응답이라 헛수고다. 일봉 OHLC 를 그대로
    재생해 체결을 확정하고, minute_verified=False 를 남긴다."""
    p = _pos(observed_at="2026-07-19T15:30",
             buys=[{"date": "2026-07-19", "price": 100000}])
    fake = FakeGH({"schema": 1, "positions": [p]})
    monkeypatch.setattr(autofill, "gh", fake)

    def boom(code, day):
        raise AssertionError("분봉 창 밖인데 fetch_minute 을 호출했다")
    monkeypatch.setattr(autofill.naver, "fetch_minute", boom)

    day = DAYS10[0]   # days_list 끝(DAYS10[-1])으로부터 9거래일 전 — 창 밖
    key = day.replace("-", "")
    rc = autofill.run({"005930": {key: {"high": 106000, "low": 99000}}}, day, DAYS10)
    assert rc == 0
    assert len(fake.writes) == 1
    exit_rec = fake.writes[0][1]["positions"][0]["exits"][0]
    assert exit_rec["reason"] == "자동익절"
    assert exit_rec["minute_verified"] is False


def test_분봉_창을_넘긴_대기_체결도_일봉만으로_확정된다(monkeypatch):
    """pending 루프도 같은 창 규칙을 따른다 — 그러지 않으면 캐치업이 오래
    밀린 대기 종목은 체결 증거(일봉 저가)가 있어도 계속 pending 으로
    남다가 결국 (틀리게) 만료된다."""
    watch_date = DAYS10[0]
    day = DAYS10[1]     # days_list 끝으로부터 8거래일 전 — 창 밖. 등록일(0) 다음날.
    key = day.replace("-", "")
    p = _pending(watch={"price": 240000, "date": watch_date, "days": 5})
    fake = FakeGH({"schema": 1, "positions": [p]})
    monkeypatch.setattr(autofill, "gh", fake)

    def boom(code, d):
        raise AssertionError("분봉 창 밖인데 fetch_minute 을 호출했다")
    monkeypatch.setattr(autofill.naver, "fetch_minute", boom)

    rc = autofill.run({"005930": {key: {"high": 245000, "low": 239000}}}, day, DAYS10)
    assert rc == 0
    pos = fake.state["positions"][0]
    assert pos["status"] == "open"
    assert pos["buys"][0]["price"] == 240000
    assert pos["buys"][0]["t"] == f"{key}1530"


def test_캐치업_날짜를_두_번_처리해도_since_가드가_중복을_막는다(monkeypatch):
    """결함2 핵심 요구사항: 캐치업이 우연히 같은(오늘이 아닌) 날짜를 두 번
    처리해도(재시도 등) 안전해야 한다. 첫 호출이 buy2 를 체결시킨 뒤에도
    그날 일봉 고가는 (내려간) 익절선을 여전히 넘는다 — touched() 필터만
    으로는 두 번째 호출을 못 막는다. 실제 방어는 since_for() 다(모듈
    독스트링의 "하루 두 번 도는 cron" 사고와 메커니즘이 같다 — 여기서는
    "캐치업 재처리"라는 다른 문맥에서 같은 가드를 확인한다)."""
    p = _pos(observed_at="2026-08-18T15:30",
             buys=[{"date": "2026-08-18", "price": 100000}])
    fake = FakeGH({"schema": 1, "positions": [p]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute", lambda code, day: [
        {"t": "202608190900", "high": 101000, "low": 100000},
        {"t": "202608190930", "high": 103000, "low": 101000},
        {"t": "202608191000", "high": 99000, "low": 94000},
        {"t": "202608191530", "high": 95000, "low": 94000},
    ])
    day = "2026-08-19"
    bars = {"005930": {"20260819": {"high": 103000, "low": 94000}}}

    rc1 = autofill.run(bars, day, [])
    assert rc1 == 0
    assert len(fake.writes) == 1
    pos = fake.state["positions"][0]
    assert len(pos["buys"]) == 2 and pos["buys"][1]["t"] == "202608191000"

    rc2 = autofill.run(bars, day, [])
    assert rc2 == 0
    assert len(fake.writes) == 1, "같은 날짜를 다시 처리했는데 추가 체결이 났다"


def test_놓친_날을_캐치업으로_처리하면_그때_체결된다(monkeypatch):
    """결함2: close.main() 이 이제 놓친 거래일도 그 날짜 그대로 autofill.run
    에 넘긴다(test_close.py 의 통합 테스트 참조) — 여기서는 autofill.run
    자체가 "오늘"이 아닌 날짜를 받아도 정상적으로 그 날의 체결을 확정하는지
    본다. 2026-08-20 에 진짜로 체결됐어야 할 워치가 cron 이 그날을 건너뛰어
    2026-08-21 에야(캐치업으로 정확히 그 날짜를 받아) 처리되는 상황이다."""
    fake = FakeGH({"schema": 1, "positions": [_pending()]})   # watch.date=2026-08-20
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute", lambda code, day: [
        {"t": f"{day.replace('-', '')}0931", "high": 241000, "low": 239000}])

    missed_day = "2026-08-21"   # 진짜 체결일 — cron 이 이 날을 건너뛰었다
    rc = autofill.run({"005930": {"20260821": {"high": 245000, "low": 239000}}},
                      missed_day, CAL)
    assert rc == 0
    pos = fake.state["positions"][0]
    assert pos["status"] == "open", "놓친 날을 그 날짜 그대로 캐치업 처리했는데 체결되지 않았다"
    assert pos["buys"][0]["date"] == missed_day


# ── 결함3(2026-08-21 감사): 손편집된 pending+orders 는 격리되어 크래시하지 않는다 ──


def test_손편집된_orders를_가진_pending_기록은_크래시_없이_격리된다(monkeypatch, capsys):
    """pending 기록(buys=[])에 orders 사다리가 손편집으로 붙어 있으면,
    candidates()/touched() 까지 도달했을 때 orders.take_profit([]) →
    orders.average([]) 의 ValueError 가 close.main() 밖으로 새어나갔다
    (감사가 end-to-end 로 재현). models.normalize() 가 이 모양(buys 비고
    orders 참) 자체를 격리하도록 고쳤다 — positions.json 전체가(기존
    관례대로, run() 상단의 `if bad:` 게이트) 그날은 쓰기를 건너뛰지만,
    최소한 크래시는 없다."""
    bad = _pending(orders={"buy2": 94000, "buy3": 88000, "customized": False})
    fake = FakeGH({"schema": 1, "positions": [bad]})
    monkeypatch.setattr(autofill, "gh", fake)
    calls = []
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: calls.append(code) or [])
    rc = autofill.run({"005930": {"20260821": {"high": 300000, "low": 200000}}},
                      "2026-08-21", CAL)
    assert rc == 0
    assert fake.writes == []
    assert calls == [], "손상 항목이 있으면 판정 자체를 시도하면 안 된다(전체 스킵)"
    out = capsys.readouterr().out
    assert "중단" in out


# ── 결함4(2026-08-21 감사): "판정 불가"와 "안 닿음"을 구분해 로그로 남긴다 ──


def test_사다리_대상_기록의_일봉이_없으면_판정_불가로_로그를_남긴다(monkeypatch, capsys):
    """candidates() 루프(이미 산 기록)도 pending 루프와 같은 구분이
    필요하다 — bar is None 은 "안 닿음"이 아니다."""
    fake = FakeGH(_state())
    monkeypatch.setattr(autofill, "gh", fake)
    rc = autofill.run({}, "2026-08-20", [])   # 005930 의 일봉 자체가 없음
    assert rc == 0
    assert fake.writes == []
    out = capsys.readouterr().out
    assert "일봉 없음" in out
    assert "005930" in out


def test_일봉_저가가_목표가에_닿았는데_분봉에서_확인_안되면_불일치를_로그로_남긴다(monkeypatch, capsys):
    """일봉이 이미 "닿았다"를 증명했는데(bar["low"] <= watch["price"]) 분봉
    어디에도 그 가격이 없으면, 두 데이터 출처가 모순된다 — 조용히 넘기면
    이 모순 자체가 사라진다."""
    fake = FakeGH({"schema": 1, "positions": [_pending()]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute", lambda code, day: [
        {"t": "202608210931", "high": 245000, "low": 241000}])   # 240,000 을 아무 분봉도 못 찍음
    rc = autofill.run({"005930": {"20260821": {"high": 245000, "low": 239000}}},
                      "2026-08-21", CAL)
    assert rc == 0
    assert fake.writes == []
    out = capsys.readouterr().out
    assert "불일치" in out


# ── 결함7(2026-08-21 무동작 감사): mutation 에도 살아남는 가드를 못박는다 ──
#
# 아래 세 테스트는 지금 통과하는 코드를 하나도 안 고친다 — 각 분기/조건을
# 지워도(뮤테이션) 전체 588개 테스트가 그대로 통과하는 사각지대였다. 여기서
# 그 분기가 없으면 실패하는 테스트를 추가해 못박는다.


def test_2차까지_체결된_뒤_3차가에_닿으면_거름망을_통과한다():
    """touched() 의 `len(filled)==2 → buy3` 분기 — 정확히 2건 체결된
    상황을 다루는 유일한 분기라, 지워도 다른 분기가 우연히 못 잡는다.
    놓치면 3차가 영원히 안 걸리고, 손절선은 3차 체결 후에만 켜지므로
    이 포지션은 이후 익절로만 닫힐 수 있다(승률 부풀림). 기존 touched()
    테스트 4개 중 이 상황(len(filled)==2)을 쓰는 건 하나도 없었다."""
    assert autofill.touched({"high": 96000, "low": 87500},
                            {"buy2": 94000, "buy3": 88000},
                            [100000, 94000]) is True


def test_저가가_목표가와_정확히_같아도_대기_체결이_닿은_것으로_본다(monkeypatch):
    """`bar["low"] > watch["price"]`(엄격한 부등식)가 핵심이다 — `>=` 로
    바뀌면 저가가 목표가에 정확히 같은 날(사용자가 고르는 목표가는 흔히
    라운드 넘버라 저가가 정확히 그 값을 찍는 일이 드물지 않다)을 "안
    닿음"으로 오판해 대기 체결이 영원히 안 걸린다."""
    fake = FakeGH({"schema": 1, "positions": [_pending()]})   # watch.price=240000
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute", lambda code, day: [
        {"t": "202608210931", "high": 241000, "low": 240000}])
    rc = autofill.run({"005930": {"20260821": {"high": 245000, "low": 240000}}},
                      "2026-08-21", CAL)
    assert rc == 0
    p = fake.state["positions"][0]
    assert p["status"] == "open", "저가==목표가인데 체결되지 않았다"
    assert p["buys"][0]["price"] == 240000


# ── 결함6(2026-08-21 무동작 감사): 비거래일에 등록된 watch 는 무한 대기하지 않는다 ──
#
# watch_deadline() 이 돌려주는 None 은 "아직 기한 아님"(정상)과 "watch.date
# 자체가 거래일이 아님"(영구적, 페이지 #date 기본값이 오늘이지만 사용자가
# 주말/휴장일로 고칠 수 있다)을 구분 못 했다. 후자를 놓치면 그 기록은
# 영원히 pending 으로 남아 만료 집계에서 빠지고, 그 사이 우연히 가격이
# 닿으면 소급 체결까지 될 수 있다.


def test_비거래일에_등록된_대기는_무효로_즉시_만료된다(monkeypatch, capsys):
    """실측 재현: 2026-08-08(토)에 등록된 관찰 — CAL 은 이 날짜를 모르고,
    그 이후로도 여러 거래일(08-20~26)을 담고 있다. 그러면 watch_deadline()
    은 영원히 None 이지만, 이 기록은 만료로 처리돼야 한다 — 가격 확인보다
    먼저(우연한 소급 체결을 막는다)."""
    p = _pending(watch={"price": 240000, "date": "2026-08-08", "days": 5})
    fake = FakeGH({"schema": 1, "positions": [p]})
    monkeypatch.setattr(autofill, "gh", fake)
    calls = []
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: calls.append(code) or [])
    rc = autofill.run({"005930": {"20260821": {"high": 250000, "low": 235000}}},
                      "2026-08-21", CAL)
    assert rc == 0
    assert calls == [], "무효 처리는 가격 확인보다 먼저 결정돼야 한다"
    assert len(fake.writes) == 1
    pos = fake.state["positions"][0]
    assert pos["status"] == "expired"
    out = capsys.readouterr().out
    assert "비거래일" in out


def test_거래일에_등록된_대기는_무효_처리되지_않는다(monkeypatch):
    """위 테스트의 짝 — 정상 등록(거래일)은 절대 이 경로를 타면 안 된다."""
    fake = FakeGH({"schema": 1, "positions": [_pending()]})   # watch.date=2026-08-20(CAL 안)
    monkeypatch.setattr(autofill, "gh", fake)
    rc = autofill.run({"005930": {"20260821": {"high": 250000, "low": 245000}}},
                      "2026-08-21", CAL)   # 아직 마감(08-25) 전, 안 닿음
    assert rc == 0
    assert fake.writes == []
    assert fake.state["positions"][0]["status"] == "pending"


# ── 결함8(2026-08-21 무동작 감사): auto:false 인 대기도 기한이 지나면 만료된다 ──
#
# apply_auto 의 계약(설계 §8)은 매매(자동매수·자동매도)를 멈추는 것이지
# 만료(장부 정리)를 멈추는 게 아니다. 예전엔 pending 루프 자체가
# auto:false 기록을 걸러서, 그런 기록은 기한이 지나도 절대 만료되지
# 않았다 — 화면엔 "기한 지남"이 계속 찍히고 통계의 만료 집계에선 빠졌다.


def test_예외_지정된_pending도_기한이_지나면_만료된다(monkeypatch, capsys):
    """auto:false 는 자동 매수를 막을 뿐 만료 판정까지 막으면 안 된다."""
    fake = FakeGH({"schema": 1, "positions": [_pending(auto=False)]})
    monkeypatch.setattr(autofill, "gh", fake)
    calls = []
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: calls.append(code) or [])
    rc = autofill.run({"005930": {"20260826": {"high": 250000, "low": 245000}}},
                      "2026-08-26", CAL)   # 마감(08-25) 하루 지남
    assert rc == 0
    assert calls == [], "만료는 auto:false 여도 가격 확인 없이 결정돼야 한다"
    assert len(fake.writes) == 1
    p = fake.state["positions"][0]
    assert p["status"] == "expired"
    assert p["watch"]["expired_on"] == "2026-08-26"
    out = capsys.readouterr().out
    assert "관찰 기한 만료" in out


def test_예외_지정된_pending은_기한_전에는_여전히_체결되지_않는다(monkeypatch):
    """위 테스트의 짝 — auto:false 는 여전히 매매(체결)를 막아야 한다
    (기존 test_예외_지정된_pending_은_체결되지_않는다 와 같은 계약,
    회귀 방지로 한 번 더 확인한다)."""
    fake = FakeGH({"schema": 1, "positions": [_pending(auto=False)]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute", lambda code, day: [
        {"t": "202608210931", "high": 241000, "low": 239000}])
    rc = autofill.run({"005930": {"20260821": {"high": 245000, "low": 239000}}},
                      "2026-08-21", CAL)   # 마감 전, 안 만료
    assert rc == 0
    assert fake.writes == []
    assert fake.state["positions"][0]["status"] == "pending"
