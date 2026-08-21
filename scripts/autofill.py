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
from . import trading_calendar as cal

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


def run(bars: dict, day: str, days_list: list) -> int:
    """하루치 집행. `bars` 는 close.py 가 이미 받아둔 일봉이다.

    `days_list` 는 거래일 달력(close.py 가 `naver.fetch_trading_days` 로
    이미 받아둔 것)이다 — 자동매수의 유효 기간(watch.days)이 거래일로
    셀 것을 요구하므로(달력일로 세면 연휴마다 거짓 만료가 난다,
    trading_calendar.py 모듈 독스트링 참조) 이 함수에도 그대로 필요하다.

    종료코드 관례는 close.py 와 같다 — **읽기 실패는 0, 쓰기 실패는 1.**
    네이버 타임아웃 같은 "매번 벌어지는 일"까지 실패로 표시하면 정작
    쓰기가 실패하는(진짜 봐야 할) 신호를 무시하게 훈련시킨다. 만료도
    쓰기다(status 를 EXPIRED 로 바꾸는 커밋) — 그 실패도 같은 규칙을 탄다.

    기록 하나마다 따로 읽고 따로 쓴다. 한 번에 모아 쓰면 그 커밋 하나가
    409 로 실패했을 때 그날 체결 전체를 잃는데, 나눠 쓰면 실패한 기록만
    다음 실행이 다시 잡는다(분봉 창 7거래일 안이면 복구된다).
    """
    key = day.replace("-", "")
    problems = []
    done = 0

    try:
        state, _ = gh.read_json(POSITIONS, default=models.empty_state())
    except Exception as e:
        print(f"[경고] positions.json 조회 실패: {type(e).__name__}: {e} — 자동 체결을 건너뛴다")
        return 0

    bad = []
    try:
        state = models.normalize(state, bad)
    except models.RejectedError as e:
        print(f"[중단] positions.json 스키마를 알 수 없다: {e}")
        return 0
    if bad:
        # positions.json 은 다시 만들 수 없는 파일이다. 손상 항목이 있으면
        # 아무것도 쓰지 않는다 — intake.py·close.py 와 같은 태도.
        print(f"[중단] 해석 불가 항목 {len(bad)}건 — 자동 체결을 건너뛴다")
        return 0

    # 대기 주문(pending) 먼저 본다 — 오늘 체결되면 그 뒤 물타기·익절
    # 판정까지 같은 실행에서 이어져야 한다(같은 날 매수·매도가 나는
    # 경우를 다음 실행으로 미루면 그만큼 분봉 창을 까먹는다).
    for p in [x for x in state["positions"]
              if x["status"] == models.PENDING and x.get("auto", True)]:
        watch = p["watch"]

        # 기한부터 본다 — 가격을 보기 전에. 창을 넘긴 뒤 오늘 우연히
        # 닿아도 "그 기간 안에 온 신호"가 아니다(지시문 결정 3) — 그래서
        # 가격 조회조차 하지 않고 곧장 만료로 끝낸다. 유일한 예외는 마감일
        # 그 날짜 자체다: `day > deadline` 을 엄격한 부등식으로 지켜야
        # (`>=` 가 아니라) 마감일 당일의 정상 체결이 이 검사에 가로채이지
        # 않는다 — 그래서 마감일 당일은 이 if 를 그냥 지나쳐 아래 가격
        # 확인으로 넘어간다(순서가 여기서 실제로 의미를 가지는 지점).
        # 달력이 답을 못 하면(watch_deadline 이 None) 만료로 보지 않는다
        # — 클램프하지 않는 held_days 와 같은 태도.
        deadline = cal.watch_deadline(days_list, watch["date"], watch["days"])
        if deadline is not None and day > deadline:
            try:
                fresh, fresh_sha = gh.read_json(POSITIONS, default=models.empty_state())
                out = models.apply_expire(models.normalize(fresh), p["id"], day)
                gh.write_json(POSITIONS, out, fresh_sha, f"관찰 기한 만료: {p['name']}")
            except Exception as e:
                print(f"[경고] 관찰 만료 쓰기 실패 {p['id']}: {type(e).__name__}: {e}")
                problems.append(p["id"])
                continue
            print(f"  관찰 기한 만료: {p['name']} (마감 {deadline} 지남)")
            state = out
            continue

        bar = bars.get(p["code"], {}).get(key)
        if bar is None or bar["low"] > watch["price"]:
            continue
        try:
            minutes = naver.fetch_minute(p["code"], day)
        except Exception as e:
            print(f"[경고] 분봉 실패 {p['code']} {day}: {type(e).__name__}: {e} — 건너뛴다")
            continue
        hit = next((m for m in minutes if m["low"] <= watch["price"]), None)
        if hit is None:
            continue
        try:
            fresh, fresh_sha = gh.read_json(POSITIONS, default=models.empty_state())
            out = models.apply_watch_fill(models.normalize(fresh), p["id"], day, hit["t"])
            gh.write_json(POSITIONS, out, fresh_sha, f"지정가 체결: {p['name']}")
        except Exception as e:
            print(f"[경고] 지정가 체결 쓰기 실패 {p['id']}: {type(e).__name__}: {e}")
            problems.append(p["id"])
            continue
        print(f"  지정가 체결: {p['name']} @ {watch['price']}")
        state = out

    for p in candidates(state):
        bar = bars.get(p["code"], {}).get(key)
        if bar is None:
            continue
        filled = filled_prices(p)
        if not touched(bar, p["orders"], filled):
            continue

        try:
            minutes = naver.fetch_minute(p["code"], day)
        except Exception as e:
            # 분봉 창(약 7거래일)을 넘겼거나 네트워크 실패다. 한 종목의
            # 실패가 나머지 종목의 체결까지 막으면 안 된다. 읽기 실패라
            # 종료코드는 더럽히지 않는다 — 다음 실행이 다시 잡는다.
            print(f"[경고] 분봉 실패 {p['code']} {day}: {type(e).__name__}: {e} — 건너뛴다")
            continue

        # `since` 가 이 호출의 핵심 방어다 — since_for() 독스트링 참조.
        # 저장된 사다리(p["orders"])를 그대로 넘긴다. 1차가로부터 다시
        # 계산하면 사용자가 지정한 customized 사다리가 무시된다.
        fills = orders.replay(p["orders"], filled, minutes, since=since_for(p))
        if not fills:
            continue

        # 체결이 있는 기록만 그때그때 따로 쓴다. state/sha 를 매번 다시
        # 읽는다 — 다른 워크플로(intake)가 그 사이에 썼을 수 있다.
        try:
            fresh, fresh_sha = gh.read_json(POSITIONS, default=models.empty_state())
            out = models.apply_fills(models.normalize(fresh), p["id"], fills, day)
            gh.write_json(POSITIONS, out, fresh_sha,
                          f"자동체결: {p['name']} ({len(fills)}건)")
        except models.AlreadyApplied:
            continue
        except Exception as e:
            print(f"[경고] 자동체결 쓰기 실패 {p['id']}: {type(e).__name__}: {e}")
            problems.append(p["id"])
            continue
        done += 1
        print(f"  자동체결: {p['name']} — {', '.join(f['kind'] for f in fills)}")

    if done:
        print(f"자동 체결 {done}건")
    return 1 if problems else 0
