# -*- coding: utf-8 -*-
"""가상 지정가 주문의 집행 — 일봉으로 거르고, 닿은 종목만 분봉으로 재생.

close.py 가 하루 한 번 부른다. 계산은 전부 orders.py 에 있고, 여기는
"무엇을 조회하고 무엇을 쓸 것인가"만 맡는다.

**거름망이 왜 일봉인가.** 일봉의 고가·저가는 그날 일어난 모든 일을
수학적으로 감싼다 — 고가가 익절선에 못 미쳤다면 그날 어떤 순간에도 익절
조건이 안 됐다는 게 **증명된다**. 30분 폴링에는 이 성질이 없다(그 순간의
가격 하나뿐이라 폴링 사이의 왕복을 못 본다). 그래서 거름망은 반드시
일봉이어야 하고, 폴링은 화면 표시 전용으로 남는다(설계 §4).

**분봉은 닿은 종목만 요청한다.** 일봉은 close.py 가 이미 받아둔 것이라
거름 비용이 0 이고, 실제로 주문가에 닿는 종목은 하루에 몇 건이다.

**재생 시작 시각은 관측 시각이 아니다.** close.yml 은 하루 두 번 돌고
(cron "0 8,23"), 두 번째 실행은 개장 전이라 같은 거래일을 다시 처리한다.
그때 filled 에는 이미 그날 체결된 매수가 들어 있어서, 관측 시각부터
재생하면 체결 이전 분봉이 **내려간 익절선**으로 평가된다 — 떨어지는
종목이 +5.3% 승리로 기록된다(2026-08-20 실측 재현). since_for() 참조.
"""
from __future__ import annotations

from . import gh, models, naver, orders

POSITIONS = "positions.json"


def candidates(state: dict) -> list:
    """재생 대상 기록들. 예외·종결·주문가 미설정은 뺀다."""
    out = []
    for p in state.get("positions", []):
        if not p.get("auto", True):
            continue
        if p["status"] == models.CLOSED or p["exits"]:
            continue
        if not p.get("orders"):
            # 주문가가 없는 옛 기록에 소급해서 지정가를 만들어 붙이지
            # 않는다 — 사용자가 명시적으로 걸어야 한다.
            continue
        out.append(p)
    return out


def _stamp(v):
    """"2026-08-19T15:30" 또는 "202608191000" → "202608191530" 꼴 12자리.

    모양이 아니면 None — 손편집으로 들어온 쓰레기 때문에 크래시하지 않는다.
    """
    if not isinstance(v, str):
        return None
    s = v.replace("-", "").replace("T", "").replace(":", "")[:12]
    return s if len(s) == 12 and s.isdigit() else None


def since_for(p: dict) -> str:
    """재생 시작 시각 — **관측 시각과 마지막 체결 시각 중 나중**.

    이 함수가 이 모듈에서 가장 중요하다. 관측 시각만 쓰면 모듈 독스트링의
    사고가 난다(하루 두 번 도는 cron 의 두 번째 실행이 소급 익절을 낸다).

    **왜 단순 max 인가.** "지금까지 이미 반영된 가장 늦은 시점"이 정확히
    재생을 시작해야 할 자리다. 관측 시각과 체결 시각 중 어느 쪽이 나중이든
    그 이전은 이미 처리됐거나(체결) 아직 관측하지도 않은(관측 전) 구간이다.

    날짜만 비교하고 시각을 무시하는 변형을 쓰면 안 된다 — 체결 시각이 관측
    시각보다 이른 기록(정상 경로로는 불가능하지만 손편집으로는 생긴다)에서
    **관측 이전 분봉을 재생**하게 되어, orders.replay 의 since 가드가
    막으려던 소급 체결이 그대로 열린다(2026-08-20 비교 실측).

    시각 정보가 전혀 없는 옛 기록은 매수일 15:30 관측으로 본다 — 즉 다음
    거래일부터 판정한다(설계 §5). 저녁에 종가 보고 넣은 관측이 그날 오전
    고가로 익절되면 승률이 부풀려지므로 보수적인 쪽을 고른다.
    """
    marks = [s for s in (_stamp(p.get("observed_at")),) if s]
    for b in p.get("buys", []):
        s = _stamp(b.get("t")) if isinstance(b, dict) else None
        if s:
            marks.append(s)
    if marks:
        return max(marks)
    return p["buys"][0]["date"].replace("-", "") + "1530"


def touched(bar: dict, ords: dict, filled: list) -> bool:
    """이 일봉이 어떤 주문가에라도 닿았는가 — 분봉을 받을지 판정한다.

    거짓 음성이 없어야 한다(놓치면 체결을 영원히 잃는다). 거짓 양성은
    분봉 요청 한 번 낭비하는 것뿐이라 싸다.
    """
    if bar["high"] >= orders.take_profit(filled):
        return True
    if len(filled) == 1 and bar["low"] <= ords["buy2"]:
        return True
    if len(filled) == 2 and bar["low"] <= ords["buy3"]:
        return True
    sl = orders.stop_loss(filled)
    if sl is not None and bar["low"] <= sl:
        return True
    return False


def filled_prices(p: dict) -> list:
    return [b["price"] for b in p["buys"]]
