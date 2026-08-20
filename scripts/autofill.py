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
    """재생 시작 시각 — 마지막 체결 시각을 기본으로 쓰되, 관측 시각이 더
    늦은 **날짜**면 관측 시각을 쓴다.

    이 함수가 이 모듈에서 가장 중요하다. 관측 시각만 쓰면 모듈 독스트링의
    사고가 난다(하루 두 번 도는 cron 의 두 번째 실행이 소급 익절을 낸다) —
    체결이 이미 있으면 그 체결 시각부터 다시 재생해야 방금 내려온 익절선이
    체결 이전 분봉에 소급 적용되지 않는다.

    **날짜만 비교하고 시각까지는 비교하지 않는다.** 관측은 흔히 그날
    15:30(종가 확인)에 기록되는데, 같은 날 안에서 체결이 그보다 이른
    시각(예: 10:00)이어도 체결이 이겨야 한다 — 15:30 은 "그날 관측했다"는
    뜻일 뿐 하루 안에서의 실제 시각 순서를 담보하지 않는다. 관측 날짜가
    마지막 체결 날짜보다 **뒤**일 때만(예: 다른 날 다시 관측된 경우)
    관측 시각으로 넘어간다 — 손편집으로 체결 시각이 관측보다 이른 기록이
    생겨도 관측 이전을 재생하지 않기 위한 방어선이다.

    시각 정보가 전혀 없는 옛 기록은 매수일 15:30 관측으로 본다 — 즉 다음
    거래일부터 판정한다(설계 §5). 저녁에 종가 보고 넣은 관측이 그날 오전
    고가로 익절되면 승률이 부풀려지므로 보수적인 쪽을 고른다.
    """
    observed = _stamp(p.get("observed_at"))
    last_fill = None
    for b in p.get("buys", []):
        s = _stamp(b.get("t")) if isinstance(b, dict) else None
        if s and (last_fill is None or s > last_fill):
            last_fill = s
    if last_fill is not None and (observed is None or observed[:8] <= last_fill[:8]):
        return last_fill
    if observed:
        return observed
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
