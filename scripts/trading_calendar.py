# -*- coding: utf-8 -*-
"""거래일 배열만 가지고 센다. **달력일로 세지 않는다** — 연휴마다 거짓이 된다.

달력은 일봉에서 온다(네이버 fchart). 정적 휴장일 목록을 쓰지 않는 이유는
임시공휴일이 연중 지정되기 때문이다 (2026-07-17 제헌절 누락 사고).
"""
from __future__ import annotations

from collections.abc import Iterable


def is_trading_day(days: list, d: str) -> bool:
    return d in days


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


def watch_deadline(days_list: list, watch_date: str, n: int) -> str | None:
    """자동매수(op: watch)이 살아있는 마지막 거래일 — 이 날짜까지 목표가에
    안 닿으면 만료다.

    `watch_date` 당일은 세지 않는다 — 관찰은 장 마감 뒤에 등록되므로
    그날은 이미 지난 하루다. 다음 거래일부터 `n` 거래일째가 마감일이다.
    예: n=3, watch_date=목요일(달력에 08-20,21,24,25,26 ... 주말은 애초에
    달력에 없다) → 금(21)·월(24)·화(25)가 유효, 화요일이 마감일 — 달력일로
    센 금·토·일이 아니다. `며칠 밀렸다` 카운트는 거래일로 세라는 이 저장소의
    공유 규약(시장달력_공유노트.md) 그대로다.

    달력이 답할 수 없으면(watch_date 가 달력 밖이거나, 그 뒤로 n 거래일이
    아직 안 쌓였으면) None 이다 — **만료로 판단하지 않는다.** 만료는
    되돌릴 수 없는 조작(status 를 EXPIRED 로 바꾸는 쓰기)이라, 달력이
    짧다는 이유로 잘못 만료시키면 그 대가가 훨씬 크다 — held_days 가
    클램프 대신 None 을 돌려주는 것과 같은 태도(모듈 독스트링 참조).
    """
    idx = {d: i for i, d in enumerate(days_list)}
    if watch_date not in idx:
        return None
    deadline_i = idx[watch_date] + n
    if deadline_i >= len(days_list):
        return None
    return days_list[deadline_i]


def watch_date_unreachable(days_list: list, watch_date: str) -> bool:
    """`watch_date` 가 이 거래일 달력 안에서 앞으로도 나타날 수 없는 날짜인가
    — 주말·임시공휴일처럼 애초에 거래일이 아닌 날에 등록된 관찰이라는 뜻이다.

    **결함6(2026-08-21 무동작 감사)**: `watch_deadline()` 이 돌려주는 None 은 서로
    다른 두 사정을 하나로 뭉갠다 — (a) "마감일 계산에 필요한 미래 거래일이
    아직 안 쌓였다"(달력이 자라면 저절로 풀린다, 정상 — self-healing)와
    (b) "watch_date 자체가 거래일이 아니다"(달력이 아무리 자라도 안 풀린다,
    영구적). autofill.run 이 둘 다 "만료로 보지 않는다"로 처리하면, (b)의
    기록은 영원히 pending 으로 남아 그 사이 우연히 가격이 닿으면 소급
    체결까지 될 수 있다(실측: 토요일에 등록된 관찰이 다음날 아침 가격으로
    체결됨). 이 함수는 (b)만 골라낸다.

    `days_list` 가 이미 `watch_date` **이후로도** 거래일을 담고 있는데(=날짜
    순으로 그 지점을 이미 지나쳐 왔는데) 그래도 `watch_date` 를 못 찾았다면,
    그 날짜는 애초에 거래일이 아니었다고 확신할 수 있다 — 달력이 더 자란다고
    없던 거래일이 새로 생기지 않는다.

    **전제와 한계**: 이 판단은 `days_list` 가 `watch_date` 이후로 충분히
    깊게 쌓여 있다는 것에 기댄다. close.py 는 매번 `naver.fetch_trading_days
    (250)` 로 약 250거래일(≈1년)을 받아온다 — watch 의 최대 유효기간
    (60거래일, `models.WATCH_DAYS_DEFAULT` 옆 `_watch_days` 참조)보다 훨씬
    길어서, 실제 운영에서는 이 전제가 항상 성립한다. 반대로 아주 짧은(예:
    테스트용 5개짜리) 달력에서는 "그냥 아직 짧다"와 "정말 비거래일이다"를
    구분 못 할 수 있다 — 그래서 근거가 부족하면(달력이 비었거나 `watch_date`
    가 달력의 마지막 날짜와 같거나 미래) False 를 돌려준다. 성급하게
    "불가능"으로 단정하지 않는다 — held_days/watch_deadline 이 짧은 달력을
    클램프하지 않는 것과 같은 태도다.
    """
    if not days_list or watch_date in days_list or watch_date >= days_list[-1]:
        return False
    return True
