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

**등록일 당일은 체결 대상이 아니다(결함1, 2026-08-21 감사 재현).**
watch 는 장 마감 뒤에 등록되므로, 등록일의 분봉은 그 워치가 존재하기 전
시각이다 — 15:41 KST 에 등록된 워치(7900원)가 같은 날 09:00 분봉으로
소급 체결되는 사고가 실측됐다(등록 6시간 41분 전). `trading_calendar.
watch_deadline()` 은 이미 등록일 당일을 안 세고 다음 거래일부터 만료
기한을 센다 — 체결 판정도 같은 기준을 써야 한다(아래 pending 루프의
`day <= watch["date"]` 가드). 두 절반이 어긋나면 등록 당일치가 소급
체결된다.

**분봉 창은 약 7거래일이다(결함2, 2026-08-21 감사).** `close.main()` 이
놓친 거래일을 뒤늦게 캐치업하려 들면, 그 날짜가 이미 이 창을 벗어나
있을 수 있다 — naver.fetch_minute 은 그때 영구히 빈 응답을 준다(재시도로
해결 안 됨). 그런 날은 분봉을 기다리지 않고 일봉 하나를 "분봉 하나"처럼
`orders.replay`/직접 대조에 넘겨 확정한다 — 설계 §9("하루 안에 손절선·
익절선을 둘 다 스치면 손절로 본다")와 같은 태도이고, 그 사실을
`minute_verified=False` 로 남긴다. `_minute_window_open()` 참조.
"""
from __future__ import annotations

from . import gh, models, naver, orders
from . import trading_calendar as cal

POSITIONS = "positions.json"

# 실측(naver.py, 2026-08-20): 분봉 API(api.stock.naver.com)는 최근 약
# 7거래일만 응답한다. 그보다 오래된 날짜는 EmptyParseError(빈 응답) —
# 네트워크 재시도로 해결되지 않는, 영구적인 데이터 부재다.
MINUTE_WINDOW_DAYS = 7


def _minute_window_open(day: str, days_list: list) -> bool:
    """`day` 의 분봉을 아직 기대할 수 있는가.

    `days_list` 의 마지막 날을 "오늘"의 대용으로 쓴다 — close.py 가
    `latest = days[-1]` 을 오늘로 쓰는 관례와 같다.

    판단 근거가 없으면(달력이 비었거나 `day` 가 달력 밖) True 를 돌려준다
    — "창이 닫혔다"고 함부로 단정하지 않는다(`trading_calendar.held_days`
    가 클램프 대신 None 을 돌려주는 것과 같은 태도). 그 경우 평소처럼
    `fetch_minute` 을 시도해보고, 실패하면 그 종목만 건너뛴다(다음 실행이
    재시도 — 창이 아직 열려 있을 수도 있으니 영구 포기하지 않는다).
    """
    if not days_list:
        return True
    age = cal.held_days(days_list, day, days_list[-1])
    return age is None or age <= MINUTE_WINDOW_DAYS


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

        # 등록일 당일은 아직 체결 대상이 아니다(결함1, 2026-08-21 감사).
        # watch 는 장 마감 뒤에 등록되므로, 등록일의 분봉은 그 워치가
        # 존재하기 전 시각이다 — 실측: 15:41 KST 등록된 워치(7900원)가
        # 같은 날 09:00 분봉으로 소급 체결됐다(등록 6시간 41분 전). 위
        # watch_deadline() 이 등록일 당일을 안 세고 다음 거래일부터 기한을
        # 세는 것과 대칭이어야 한다 — 두 절반이 어긋나면 등록 당일치가
        # 소급 체결된다. 이 스크리너들은 거의 다 장 마감(15:00) 이후에
        # 등록하므로 이 가드는 매일 조용히(로그 없이) 걸린다 — 정상
        # 무동작이지 오류가 아니다.
        if day <= watch["date"]:
            continue

        bar = bars.get(p["code"], {}).get(key)
        if bar is None:
            # 결함4(2026-08-21 감사): "안 닿음"과 "판정 자체를 못 했다"를
            # 같은 continue 로 뭉치면 안 된다 — 이 코드의 일봉이 아예 빠진
            # 것(예: close.py 가 대기 종목의 일봉을 안 받아온 사고, 이미
            # 한 번 실측됨)은 눈에 띄어야 한다.
            print(f"[경고] 일봉 없음 {p['code']} {day} — 대기 체결 판정 불가")
            continue
        if bar["low"] > watch["price"]:
            continue    # 정상 무터치 — 조용히 넘어간다

        if _minute_window_open(day, days_list):
            try:
                minutes = naver.fetch_minute(p["code"], day)
            except Exception as e:
                print(f"[경고] 분봉 실패 {p['code']} {day}: {type(e).__name__}: {e} — 건너뛴다")
                continue
            hit = next((m for m in minutes if m["low"] <= watch["price"]), None)
            if hit is None:
                # 결함4: 일봉 저가가 이미 목표가 이하로 찍혔다고 방금
                # 확인했는데(위) 분봉 어디에도 그 가격이 없다 — 두 데이터
                # 출처가 모순된다. 조용히 넘기면 이 모순 자체가 사라진다.
                print(f"[경고] 일봉·분봉 불일치 {p['code']} {day}: "
                      f"일봉 저가({bar['low']})가 목표가({watch['price']}) 이하인데 분봉에서 확인 안 됨")
                continue
            t = hit["t"]
        else:
            # 결함2: 분봉 창(약 7거래일)을 이미 넘겼다 — 다시 시도해도
            # 영구히 빈 응답이 온다. 일봉 저가가 목표가 도달을 이미
            # 증명했으므로(위에서 확인), 체결 시각은 그날 15:30 관측으로
            # 간주한다(관측 시각을 모르는 옛 기록과 같은 관례 —
            # since_for() 참조).
            t = f"{key}1530"
            print(f"  분봉 창 밖 — 일봉만으로 지정가 체결 확정: {p['name']} {day}")
        try:
            fresh, fresh_sha = gh.read_json(POSITIONS, default=models.empty_state())
            out = models.apply_watch_fill(models.normalize(fresh), p["id"], day, t)
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
            # 결함4(2026-08-21 감사): 이 코드의 일봉이 아예 없는 것과
            # "안 닿았다"는 전혀 다른 상황이다 — 정확히 이 모양의 결손이
            # (close.py 가 종목 하나의 일봉을 안 받아온 것) 기능이 나온
            # 이후 한동안 안 들키고 넘어갔었다. 조용한 continue 로 뭉치지
            # 않는다.
            print(f"[경고] 일봉 없음 {p['code']} {day} — 자동 체결 판정 불가")
            continue
        filled = filled_prices(p)
        if not touched(bar, p["orders"], filled):
            continue    # 정상 무터치 — 조용히 넘어간다

        if _minute_window_open(day, days_list):
            try:
                minutes = naver.fetch_minute(p["code"], day)
            except Exception as e:
                # 창 안인데도 실패했다 — 네트워크 문제일 가능성이 크다.
                # 한 종목의 실패가 나머지 종목의 체결까지 막으면 안 된다.
                # 읽기 실패라 종료코드는 더럽히지 않는다.
                #
                # **결함5(2026-08-21 무동작 감사)의 정정.** 이 자리의 옛
                # 주석은 "다음 실행이 다시 잡는다"고 적어뒀지만, 그건 `day`
                # 가 `latest`(오늘)일 때만 참이었다 — close.main() 이
                # 예전엔 `sorted(set(todo) | {latest})` 로만 이 함수를
                # 불러서, 캐치업 날짜(latest 가 아닌 날)는 그
                # history/{day}.json 이 (이 실패와 무관하게, 다른 루프에서
                # 먼저) 한 번 쓰이는 순간 missing_days 에서 영구히 빠졌다 —
                # 그러면 이 날짜는 다시는 autofill.run 에 안 넘어와서, 이
                # 실패로 놓친 체결이(예: 2차 매수) 영영 복구되지 않았다
                # (실측 재현: tests/test_close.py 의 결함5 재현 테스트).
                # 손절선은 3차 체결 후에만 켜지므로, 놓친 2차·3차는 그
                # 포지션을 익절로만 닫힐 수 있게 만든다 — 승률이 조용히
                # 부풀려진다.
                #
                # 지금은 close.main() 이 분봉 창(MINUTE_WINDOW_DAYS≈7거래일)
                # 안의 모든 거래일을 history 존재 여부와 무관하게 매 실행
                # 다시 이 함수에 넘긴다(close.py 참조) — 그래서 이 주석의
                # "다음 실행이 다시 잡는다"는 이제 **모든** 날짜에 대해
                # 참이다(창을 넘긴 날짜는 애초에 이 분기에 안 온다 — 아래
                # else 의 일봉 대체 경로로 간다). 이미 끝난 날짜를 다시
                # 넘겨도 since_for()/replay 의 since 가드가 중복 체결을
                # 막으므로(모듈 독스트링) 이 재시도는 안전하고 거의 공짜다
                # (터치된 종목만 분봉을 다시 요청한다).
                print(f"[경고] 분봉 실패 {p['code']} {day}: {type(e).__name__}: {e} — 건너뛴다")
                continue

            # `since` 가 이 호출의 핵심 방어다 — since_for() 독스트링 참조.
            # 저장된 사다리(p["orders"])를 그대로 넘긴다. 1차가로부터 다시
            # 계산하면 사용자가 지정한 customized 사다리가 무시된다.
            fills = orders.replay(p["orders"], filled, minutes, since=since_for(p))
            minute_verified = True
        else:
            # 결함2: 분봉 창(약 7거래일)을 이미 넘겼다 — fetch_minute 을
            # 시도해도 영구히 빈 응답이라 헛수고다. 일봉 OHLC 하나를
            # "분봉 하나"처럼 orders.replay 에 넘긴다 — replay() 는 이미
            # 한 틱 안에서 매수 먼저·(둘 다 스치면) 손절 우선의 순서를
            # 지키므로(그 docstring 참조), 하루 전체를 한 틱으로 압축해도
            # 설계 §9("승률을 부풀리지 않는 쪽")와 같은 결과가 나온다.
            # 시각 정보가 없어 그날 15:30 관측으로 간주한다(pending 루프,
            # since_for() 와 같은 관례).
            fills = orders.replay(p["orders"], filled,
                                  [{"t": f"{key}1530", "high": bar["high"], "low": bar["low"]}],
                                  since=since_for(p))
            minute_verified = False
            if fills:
                print(f"  분봉 창 밖 — 일봉만으로 체결 확정: {p['name']} {day}")
        if not fills:
            continue

        # 체결이 있는 기록만 그때그때 따로 쓴다. state/sha 를 매번 다시
        # 읽는다 — 다른 워크플로(intake)가 그 사이에 썼을 수 있다.
        try:
            fresh, fresh_sha = gh.read_json(POSITIONS, default=models.empty_state())
            out = models.apply_fills(models.normalize(fresh), p["id"], fills, day,
                                     minute_verified=minute_verified)
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
