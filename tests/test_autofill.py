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
                      "2026-08-20")
    assert rc == 0
    assert len(fake.writes) == 1
    p = fake.writes[0][1]["positions"][0]
    assert p["status"] == "closed"
    assert p["exits"][0]["reason"] == "자동익절"
    assert p["exits"][0]["price"] == 105300


def test_안_닿으면_분봉을_요청하지도_쓰지도_않는다(monkeypatch):
    calls = []
    fake = FakeGH(_state())
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: calls.append(code) or [])
    rc = autofill.run({"005930": {"20260820": {"high": 101000, "low": 99000}}},
                      "2026-08-20")
    assert rc == 0
    assert calls == []
    assert fake.writes == []


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
                      "2026-08-19")
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
                      "2026-08-20")
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
                      "2026-08-20")
    assert rc == 1


def test_손상된_파일에는_아무것도_쓰지_않는다(monkeypatch):
    """positions.json 은 다시 만들 수 없다 — intake·close 와 같은 태도."""
    fake = FakeGH({"schema": 1, "positions": [{"code": "망가짐"}]})
    monkeypatch.setattr(autofill, "gh", fake)
    rc = autofill.run({}, "2026-08-20")
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
                      "2026-08-20")
    assert rc == 0
    p = fake.writes[0][1]["positions"][0]
    assert p["buys"][1]["price"] == 95000   # 기본값 94,000 이 아니다


# ── Task 12: 지정가 관찰(pending) — 목표가에 닿으면 1차 매수로 체결된다 ─────


def _pending(**over):
    p = {"id": "20260820-005930", "code": "005930", "name": "삼성전자",
         "buys": [], "exits": [], "adjustments": [], "status": "pending",
         "source": "종가베팅", "memo": "", "signal_date": None,
         "watch": {"price": 240000, "date": "2026-08-20"},
         "orders": {}, "auto": True, "observed_at": None}
    p.update(over)
    return p


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
                      "2026-08-21")
    assert rc == 0
    p = fake.state["positions"][0]
    assert p["status"] == "open"
    assert p["buys"][0]["price"] == 240000
    assert p["buys"][0]["t"] == "202608210931"
    assert p["observed_at"] == "2026-08-21T09:31"


def test_지정가에_안_닿으면_pending_그대로다(monkeypatch):
    calls = []
    fake = FakeGH({"schema": 1, "positions": [_pending()]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute",
                        lambda code, day: calls.append(code) or [])
    rc = autofill.run({"005930": {"20260821": {"high": 250000, "low": 245000}}},
                      "2026-08-21")
    assert rc == 0
    assert calls == [], "일봉 저가가 목표가 위인데 분봉을 받았다"
    assert fake.writes == []


def test_예외_지정된_pending_은_체결되지_않는다(monkeypatch):
    """예외는 자동매도뿐 아니라 자동매수도 멈춘다(설계 §8)."""
    fake = FakeGH({"schema": 1, "positions": [_pending(auto=False)]})
    monkeypatch.setattr(autofill, "gh", fake)
    monkeypatch.setattr(autofill.naver, "fetch_minute", lambda code, day: [
        {"t": "202608210931", "high": 241000, "low": 239000}])
    rc = autofill.run({"005930": {"20260821": {"high": 245000, "low": 239000}}},
                      "2026-08-21")
    assert rc == 0
    assert fake.writes == []
