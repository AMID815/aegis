# -*- coding: utf-8 -*-
"""거래일 배열만 가지고 센다. **달력일로 세지 않는다** — 연휴마다 거짓이 된다.

달력은 일봉에서 온다(네이버 fchart). 정적 휴장일 목록을 쓰지 않는 이유는
임시공휴일이 연중 지정되기 때문이다 (2026-07-17 제헌절 누락 사고).
"""
from __future__ import annotations

from collections.abc import Iterable


def is_trading_day(days: list, d: str) -> bool:
    return d in set(days)


def held_days(days: list, start: str, end: str) -> int | None:
    """start 매수 → end 까지 몇 거래일 지났나.

    달력 밖이면 None (클램프하지 않는다). end 가 start 보다 앞서서 인덱스가
    거꾸로 나오는 경우도 None — models.py 는 저장 시점에 sell < buy 를
    거부하지만, 이 함수는 그 검증을 거치지 않은 값(예: 아직 열린 포지션의
    '오늘까지' 계산에 잘못된 buy_date)이 들어올 수 있다고 가정한다. 음수
    보유일수를 그대로 돌려주면 호출자 실수를 조용히 삼키게 된다.
    """
    idx = {d: i for i, d in enumerate(days)}
    if start not in idx or end not in idx:
        return None
    delta = idx[end] - idx[start]
    return delta if delta >= 0 else None


def recent(days: list, n: int) -> list:
    """최근 n거래일. n<=0 이면 빈 리스트 — days[-n:] 슬라이스는 n=0 일 때
    days[-0:] == days[0:] 이 되어 전체를 돌려주는 함정이 있어 명시적으로 막는다.
    """
    if n <= 0:
        return []
    if n >= len(days):
        return list(days)
    return days[-n:]


def missing(days: list, n: int, have: Iterable[str]) -> list:
    """최근 n거래일 중 have 에 없는 날짜(오래된 것부터)."""
    have = set(have)
    return [d for d in recent(days, n) if d not in have]


def too_short(days: list, need: int) -> bool:
    return len(days) < need
