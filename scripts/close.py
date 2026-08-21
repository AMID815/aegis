# -*- coding: utf-8 -*-
"""종가 확정 — **시각이 아니라 백필**.

깃허브 cron 은 공식적으로 지연되고 드롭된다. 그래서 '15:40 에 찍기' 가 아니라
'빠진 날 채우기' 로 정의한다. 일봉 종가는 15:31~32 발행 후 영구 불변이므로
런이 16시에 돌든 다음날 돌든 결과가 같다 — 한 번 걸러도 다음 런이 메운다.
수능일(2026-11-19, 마감 16:30)처럼 시각이 밀리는 날도 그냥 흡수된다.

계획 문서(구현계획.md Task 8) 의 공급 코드에서 아래를 고쳤다(각 지점에도 주석
있음) — 자세한 근거는 tests/test_close.py 모듈 docstring 참조:

1. `quotes.fetch_benchmark()` 가 Task 7 이후 3-tuple `(values, history, failed)`
   를 돌려준다 — 그대로 한 자리에 넣던 걸 풀어서 넘긴다.
2. positions 조회(넓은 실패)와 정규화(RejectedError 하나, 좁은 실패)를 한
   try 로 묶어 `except models.RejectedError` 만 잡던 버그 — quotes.py 가
   Task 7 에서 이미 겪고 고친 것과 같은 결함이 재발해 있었다. 분리했다.
3. 확정 quotes.json 커밋 구간이 어떤 try 에도 없던 버그 — 마찬가지로 고쳤다.
4. `codes` 를 열림(open) 종목으로 좁혔다 — 닫힌 포지션은 오늘 종가가
   필요 없고(실현 손익이 buys/exits 에 이미 고정), 포함시키면 상폐된 닫힌
   종목이 매번 조회를 실패시켜 확정 스냅샷의 missing/fail_count 를 오염시킨다.
5. 보유 중인 종목의 일봉 조회가 (그날 값이 없는 게 아니라) 아예 실패하면
   백필 전체를 건너뛴다 — history/ 는 한 번 쓰면 missing_days 가 다시는 그
   날짜를 보지 않으므로, 종목 하나가 빠진 채로 쓰면 그 결손이 영구화된다.
6. 백필 하루치 쓰기 실패가 나머지 날짜·확정 갱신까지 막지 않게 날짜 단위로
   try/except 를 둘렀다.
7. 보유가 0건이어도(`snapshot_for` 가 그런 날엔 항상 None 을 돌려준다)
   `quotes.build`/`should_commit` 을 거치도록 해 trading_days/benchmark 가
   계속 갱신되게 했다 — quotes.py 의 "진짜 무보유는 커밋한다" 원칙과 맞춘다.

리뷰 2라운드(실제 사용 시나리오를 구성해 검증) 반영:

8. `gh.list_dir("history")` 가 어떤 try 에도 없었다 — Contents API 5xx 는
   일상적으로 벌어지는데, 여기서 죽으면 확정 quotes.json 갱신까지 통째로
   못 하게 된다. try/except 로 감싸고, 실패하면 `todo=[]` 로 백필만
   건너뛴 채 확정 단계로 계속 진행한다.
9. 확정 스냅샷의 `status` 가 `"tradable"` 로 하드코딩돼 있었다. 거래정지
   종목도 그날 일봉은 나온다(naver.py 실측: 시가·고가·저가 0, 종가만 값) —
   그 모양의 봉이 `final["closes"]` 에 그대로 들어가 정지 종목이 "정상
   거래"로 찍혔다. 이미 받아둔 봉만으로(추가 요청 없이) `open==high==low==0
   and close>0` 이면 `"halted"`, 아니면 `"tradable"` 로 추정하게 고쳤다.
   `"market"` 필드도 빈 문자열로 추가했다 — parse_polling(장중) 은 채우는
   자리라 모양을 맞췄다.
10. 종료코드를 "이번 실행에 문제가 있었나"에서 "쓰기 시도가 실패했나"로
    좁혔다. 일봉 조회 실패(naver, 읽기)나 `gh.list_dir` 실패(GitHub, 읽기)는
    이 모듈의 핵심 전제대로 다음 실행이 자연히 메운다 — 매번 실패로
    표시하면 close.yml 에 `continue-on-error` 가 없어 사람에게 매번
    이메일이 가고, 그게 잦아지면 정작 중요한 신호(쓰기 자체가 실패)를
    무시하게 훈련시킨다. `history/*.json`·확정 `quotes.json` **쓰기**가
    실패한 경우만 `problems` 에 쌓고 rc=1 로 낸다.
11. `snapshot_for` 가 돌려주는 종가는 naver 가 조회 시점 기준으로 조정한
    값이다(액면분할·무상증자가 있으면 과거 봉도 소급 재계산된다 — 실측:
    2026-08 알테오젠(196170) 무상증자 전 종가는 틱 단위에 안 맞는 값,
    이후는 전부 500원 단위로 딱 맞음). 그날 실시간으로 찍힌 `history/`
    파일과, 그 뒤 분할·증자가 생긴 다음 이 모듈이 소급 채운 같은 날짜
    파일은 그 비율만큼 어긋날 수 있다 — `price_basis` 필드로 그 사실을
    스냅샷 자체에 남긴다(자세한 근거는 `snapshot_for` docstring).

무동작(silent no-op) 감사(2026-08-21) 반영:

12. **결함5 — 자동 체결의 재시도 창을 `history/` 존재 여부와 분리했다.**
    예전엔 `sorted(set(todo) | {latest})` 만 `autofill.run` 에 넘겼다 —
    캐치업 날짜(latest 가 아닌 날)에서 `naver.fetch_minute` 이 한 번
    실패하면(네트워크 등, autofill.py 는 이를 "다음 실행이 다시 잡는다"는
    전제로 조용히 넘긴다) 그 전제가 실제로는 거짓이었다: 그 날짜의
    `history/{day}.json` 은 이 실패와 무관하게 이미 쓰였으므로
    `missing_days` 가 다음 실행부터 그 날짜를 다시 보지 않고, `latest`
    도 아니니 다시는 `autofill.run` 에 넘어오지 않는다 — 그 실패로 놓친
    체결(2차·3차 매수)이 영구히 사라진다(3차가 없으면 손절선이 안 켜져
    그 포지션은 이후 익절로만 닫힐 수 있다 — 승률이 조용히 부풀려진다).
    고친 방법은 아래 자동 체결 배선 지점의 주석에 자세히 남겼다 —
    요약하면 분봉 재생 창(`autofill.MINUTE_WINDOW_DAYS`≈7거래일) 안의
    모든 거래일을 `history/` 존재 여부와 무관하게 매 실행 다시 넘긴다.
"""
from __future__ import annotations

import sys

from . import trading_calendar as cal
from . import autofill, gh, models, naver, quotes

WINDOW = 30                       # 최근 30거래일까지 메운다
POSITIONS = "positions.json"
QUOTES = "quotes.json"

# `missing_days` 가 잘라내는 접미사 — 리터럴 5 대신 길이로 표현해 "왜 5인지"
# 되물을 필요를 없앤다.
_SUFFIX = ".json"


def missing_days(days: list, n: int, filenames: list) -> list:
    """`filenames`(history/ 디렉토리 목록) 중 `.json` 로 끝나는 것만 날짜로
    본다. `f[:-len(_SUFFIX)]` 가 실제 날짜와 다른 문자열이 되는 경우(예:
    `.json` 단독 파일 → 빈 문자열, `2026-08-19-backup.json` → 접두어가 남은
    문자열)가 있어도 무해하다 — `days` 의 실제 날짜(YYYY-MM-DD, 정확히 이
    모듈이 `history/{day}.json` 으로 쓰는 이름)와 우연히 같아질 일이 없다.
    `.json.bak` 처럼 `.json` 으로 끝나지 않는 이름은 애초에 `endswith` 에서
    걸러져 이 문제 자체가 발생하지 않는다.
    """
    have = {f[:-len(_SUFFIX)] for f in filenames if f.endswith(_SUFFIX)}
    return cal.missing(days, n, have)


def snapshot_for(day: str, bars: dict, state: dict):
    """day 의 종가만 모은다. 봉이 없는 종목은 넣지 않는다 (0 으로 채우면 -100%).

    ⚠ 소급 생성분에서 `positions` 는 **그날의 것이 아니라 실행 시점의 현재 상태**다.
    `closes` 만 그날의 진짜 값이다. 복구 보험으로는 유효하지만 "그날의 보유 목록"으로
    읽으면 안 된다 (설계 §6-3).

    ⚠ `closes` 는 **조회 시점 기준으로 조정된** 값이다. naver fchart 는 액면
    분할·무상증자가 있으면 그 이전 날짜의 봉도 소급 재계산해서 돌려준다 —
    가상이 아니라 실측 확인(2026-08-20, 알테오젠 196170, 신주배정기준일
    2026-08-06 무상증자): 그 이전 날짜들의 종가는 500원 틱에 안 맞는 값
    (예: 244301원)이고, 그 이후는 전부 500원 배수(예: 293500원)로 딱 맞는다
    — 과거 봉이 새 주식 수 기준으로 나눠져서 재계산됐다는 뜻이다. 그래서
    "그날 실시간으로 찍힌 `history/2026-07-20.json`"과 "그 뒤 분할·증자가
    생긴 다음 이 모듈이 뒤늦게 채운 같은 날짜의 `history/2026-07-20.json`"은
    같은 날짜인데도 그 비율만큼 다른 값을 담을 수 있다 — `history/` 는
    write-once 라 이 결손도 영구적이다(위 5번 항목이 막는 결손과 같은
    부류지만, 이건 코드로 감지할 방법이 없어 완전히 막지는 못한다. 최소한
    `price_basis` 필드로 "이 값은 조회 시점 기준"이라는 사실을 스냅샷
    자체에 남겨, 나중에 두 파일이 어긋난 걸 발견했을 때 원인을 바로 알 수
    있게 한다).
    """
    key = day.replace("-", "")
    closes = {code: b[key]["close"] for code, b in bars.items() if key in b}
    if not closes:
        return None
    return {"date": day, "closes": closes, "positions": state.get("positions", []),
            "price_basis": "asof-fetch"}


def _status_for(bar: dict) -> str:
    """일봉(OHLC) 하나에서 거래상태를 추정한다 — 추가 요청 없이, 이미 받아둔
    값만으로. 거래정지 종목의 그날 봉은 시가·고가·저가가 0 이고 종가만 값이
    있다(naver.py 실측: 000880, `20260819|0|0|0|83800|0`). 이 모양이면
    `"halted"`, 아니면 `"tradable"` 로 본다.

    상장폐지처럼 그 자체로 당일 봉이 아예 없는 경우는 `snapshot_for` 단계에서
    이미 `closes` 에서 빠지므로(그 종목은 애초에 이 함수까지 오지 않는다)
    여기서 다룰 대상이 아니다.
    """
    if bar.get("open") == 0 and bar.get("high") == 0 and bar.get("low") == 0 and bar.get("close", 0) > 0:
        return "halted"
    return "tradable"


def main() -> int:
    # positions 조회(넓게 — gh.CorruptJSON·RuntimeError·URLError 까지)와
    # 정규화(좁게 — models.RejectedError 하나)를 별도 try 로 나눈다. 한
    # 블록에 몰면, 조회 쪽에서 나는 예외가 이 아래 except 에 안 잡혀
    # 트레이스백으로 죽는다(quotes.py 가 Task 7 에서 겪고 고친 것과 같은
    # 결함 — 여기서도 같은 이유로 나눈다).
    try:
        state, _ = gh.read_json(POSITIONS, default=models.empty_state())
    except Exception as e:
        print(f"[중단] positions.json 조회 실패: {type(e).__name__}: {e}")
        return 1
    bad: list = []
    try:
        state = models.normalize(state, bad)
    except models.RejectedError as e:
        print(f"[중단] positions.json 스키마를 알 수 없다: {e}")
        return 1
    if bad:
        # **여기서는 멈춘다.** history 스냅샷은 복구용 사본이다(설계 §6-3).
        # 손상 항목을 뺀 채 찍으면, 정작 구조해야 할 기록이 빠진 보험이 된다.
        # quotes.py(경고 후 진행)와 다른, 의도된 결정이다.
        #
        # 최상위 구조 자체가 깨진 경우(quotes.py.WHOLE_FILE_MARKER, 예:
        # positions 가 list 가 아님)와 개별 항목 하나가 깨진 경우를 구분해서
        # 찍는다 — 둘 다 여기서 return 1 로 끝나 결과(아무것도 안 씀)는
        # 같지만, 후자로 뭉뚱그리면 "보유 전체가 안 보인다"는 사고를
        # "기록 1건을 못 읽었다"로 축소 보고하는 셈이다(quotes.py 가 이미
        # 겪은 리뷰 A1 과 같은 함정 — Actions 로그를 보는 사람에게만
        # 영향이 있고 쓰기 동작 자체는 어느 쪽이든 동일하다).
        if len(bad) == 1 and bad[0].get("id") == quotes.WHOLE_FILE_MARKER:
            note = bad[0].get("note", "")
            print(f"[중단] positions.json 최상위 구조를 읽지 못했다 — 보유 전체가 가려짐: {note}")
        else:
            ids = [p.get("id") or p.get("code") for p in bad]
            print(f"[중단] 해석 불가 항목 {len(bad)}건 — 스냅샷을 찍지 않는다: {ids}")
        return 1

    # 열린(open) 종목만 — 닫힌 포지션의 실현 손익은 buys/exits 에 이미
    # 고정돼 있어 오늘 종가가 필요 없다. 전부(닫힌 것까지) 조회하면 상폐된
    # 닫힌 종목이 매번 fetch_bars 를 실패시켜 확정 스냅샷의 missing/
    # fail_count 를 무의미하게 부풀리고, 아래 "일봉 완전 실패 시 백필
    # 건너뛴다" 게이트와 만나면 그 종목이 상폐인 한 백필이 영원히 막힌다.
    # 보유 중 + 자동매수 대기(quotes.live_codes). 대기 종목이 빠지면
    # autofill.run 의 bars 에 그 코드가 없어 `bar is None` 으로 건너뛰고,
    # **자동매수가 한 번도 안 걸린다**(2026-08-21 라이브 실측: 금호전기
    # 001210 이 대기 중인데 조회 종목이 빈 배열이었다).
    codes = quotes.live_codes(state)

    try:
        days = naver.fetch_trading_days(250)
    except Exception as e:
        print(f"[중단] 달력 실패: {type(e).__name__}: {e}")
        return 1
    if cal.too_short(days, need=WINDOW + 2):
        print(f"[중단] 달력이 짧다({len(days)}일) — 잘못 메울 바에 쉰다")
        return 1

    try:
        existing = gh.list_dir("history")
    except Exception as e:
        # gh.list_dir 는 404 이외의 모든 비정상 상태(1,000개 상한 등)에
        # RuntimeError 를, 디렉토리가 아니면 NotADirectoryError 를 내고
        # URLError 도 그대로 새어나온다 — Contents API 5xx 는 일상적으로
        # 벌어진다. 여기서 안 잡으면 트레이스백으로 죽어서 그 아래 확정
        # quotes.json 갱신까지 통째로 못 하게 된다 — 백필 하루 못 채운 것보다
        # 화면이 밤새 확정 안 되는 쪽이 더 크다. 무엇이 빠졌는지 모르니 이번
        # 실행은 백필만 건너뛴다 — 확정 단계는 history/ 목록과 무관하므로
        # 계속 진행한다.
        print(f"[경고] history/ 목록 조회 실패: {type(e).__name__}: {e} — "
              f"이번 실행은 백필을 건너뛰고 확정 시세만 시도한다")
        todo = []
    else:
        todo = missing_days(days, WINDOW, existing)
        if not todo:
            print("메울 날짜 없음")

    # 이번 실행 안에서 벌어진 "쓰기 실패"만 여기 쌓는다 — 종료코드는 이걸로
    # 결정한다. 일봉/디렉토리 목록 같은 읽기 실패는 이 모듈의 핵심 전제대로
    # 다음 실행이 자연히 메우고, close.yml 에 continue-on-error 가 없어
    # 실패 시마다 사람에게 메일이 가므로 "매번 벌어지는 일"(네이버 타임아웃
    # 등)까지 실패로 표시하면 정작 쓰기 자체가 실패하는(진짜 봐야 할) 신호를
    # 무시하게 훈련시킨다.
    problems: list = []

    # n=WINDOW*2: missing_days 가 todo 를 항상 최근 WINDOW(30)거래일로만
    # 제한하므로(트래커가 아무리 오래 안 돌았어도), 60 거래일치를 받으면
    # 그 창을 덮고도 2배 여유가 남는다. 최근에 추가된 종목이라 실제 상장
    # 이후 거래일 수가 60 보다 적으면 있는 만큼만 온다 — snapshot_for 가
    # 그 이전 날짜엔 자연히 그 종목을 빼므로(코드가 없던 날) 문제가 안 된다.
    bars = {}
    fetch_failed: list = []
    for c in codes:
        try:
            bars[c] = naver.fetch_bars(c, n=WINDOW * 2)
        except Exception as e:
            print(f"[경고] 일봉 실패 {c}: {type(e).__name__}: {e}")
            fetch_failed.append(c)
    # fetch_failed 는 읽기 실패다 — problems(쓰기 실패, 종료코드용)에 넣지
    # 않는다. 그래도 아래 게이트가 백필을 건너뛰게 하는 데는 그대로 쓰인다.

    made = 0
    if fetch_failed:
        # 거래정지로 "그날 값이 없는 것"과, 요청 자체가 실패한 건 다르다.
        # history/ 는 한 번 쓰면 missing_days 가 다시는 그 날짜를 보지
        # 않으므로(파일 존재 = "됐다"), 일부 종목이 빠진 채로 쓰면 그
        # 결손이 영구화된다 — bad(개별 positions 항목 손상)에 대해 이미
        # 취하는 "차라리 안 쓴다" 태도를 네트워크발 결손에도 그대로 적용.
        print(f"[중단] 일봉 조회 실패 {len(fetch_failed)}건({fetch_failed}) — "
              f"백필을 건너뛴다(history 는 복구용 사본이라 일부만 쓰면 안 된다). "
              f"다음 실행이 다시 시도한다")
    else:
        for day in todo:
            snap = snapshot_for(day, bars, state)
            if snap is None:
                print(f"  {day}: 봉 없음 — 다음 런이 메운다")
                continue
            try:
                # sha=None 은 "새 파일" 이라는 뜻이다. 이미 있는 날짜에 쓰면
                # 422 로 죽는다(조용히 덮어쓰지 않는다 — 실측 확인).
                # missing_days 가 제대로 거르면 여기 도달할 일이 없고,
                # 도달했다면 그게 버그라는 신호다.
                gh.write_json(f"history/{day}.json", snap, None, f"history: {day}")
            except Exception as e:
                # 하루치 쓰기 실패(429·5xx·네트워크)가 나머지 날짜·확정
                # 갱신까지 막으면 안 된다. 이미 쓴 날짜는 되돌릴 이유가
                # 없고, 이 날짜는 다음 실행의 missing_days 가 다시 찾는다.
                print(f"[경고] history/{day}.json 쓰기 실패: {type(e).__name__}: {e} — 다음 실행이 재시도한다")
                problems.append(f"history/{day}.json 쓰기 실패")
                continue
            made += 1
            print(f"  {day}: 기록 ({len(snap['closes'])}종목)")

    # 확정 시세 = 가장 최근 거래일의 일봉 종가. `days[-1]` 이 오늘이 아니라
    # 어제일 수 있다(예: 삼성전자 오늘 일봉이 아직 안 나온 경우) — 그러면
    # 자동으로 "확정 가능한 가장 최근 날짜"가 된다. 커밋되는 trading_days
    # 배열의 마지막 값이 그 사실을 스스로 드러내므로 별도 필드가 필요 없다.
    latest = days[-1]
    final = snapshot_for(latest, bars, state)
    # `final` 이 None 이어도(보유 0건, 또는 종목은 있으나 오늘 값을 하나도
    # 못 구한 경우 포함) quotes.build/should_commit 을 항상 거친다.
    # should_commit 이 이미 "진짜 무보유"(커밋해야 함)와 "있는데 전부
    # 실패"(커밋하면 안 됨)를 positions_dropped/ok_count/fail_count 로
    # 정확히 구분하므로, `if final:` 로 따로 게이트하면 무보유일 때
    # trading_days/benchmark 갱신 자체가 스킵되는 문제가 생긴다(quotes.py
    # 의 "진짜 무보유는 커밋한다" 원칙과 어긋남).
    latest_key = latest.replace("-", "")
    got = {}
    if final:
        for c, price in final["closes"].items():
            got[c] = {
                "price": price,
                "name": next((p["name"] for p in state["positions"]
                             if p["code"] == c), c),
                # naver.py 실측: 거래정지 종목도 그날 봉은 나온다(시가·고가·
                # 저가 0, 종가만 값). 하드코딩된 "tradable" 은 정지 종목을
                # "정상 거래"로 잘못 표기했다 — 설계 §5 는 정확히 이걸
                # quotes.json 의 종목별 status 로 기록하라고 요구한다
                # ("이게 없으면 죽은 종목이 마지막 가격으로 영원히 살아
                # 있게 된다"). c 는 final["closes"] 를 통해 왔으므로
                # bars[c][latest_key] 는 snapshot_for 의 구성 방식상 항상
                # 존재한다.
                "status": _status_for(bars[c][latest_key]),
                # parse_polling(장중)은 marketStatus 를 같이 준다(§6-2:
                # "종목별 장 상태는 quotes[코드]['market'] 에 들어간다") —
                # fchart 일봉에는 그 정보가 없다. 빈 문자열로 모양만 맞춰
                # 화면이 이 키가 없다고 죽지 않게 한다.
                "market": "",
            }
    else:
        print(f"  {latest}: 확정할 종가 없음")

    bench, bench_history, bench_failed = quotes.fetch_benchmark()
    snap = quotes.build(got, codes, days, bench, quotes.now_kst(), is_final=True,
                        # bad 는 이 지점에 도달했다는 것 자체가 위에서 이미
                        # 비어있음을 확인했다는 뜻이다(비어있지 않으면 그
                        # 위에서 return 1 로 끝난다) — 그래도 quotes.build
                        # 의 dropped 기본값(0)에 암묵적으로 기대지 않고
                        # 명시한다(구현계획.md 코드리뷰 이월 항목).
                        dropped=len(bad),
                        bench_history=bench_history, benchmark_failed=bench_failed)
    if quotes.should_commit(snap):
        try:
            _, sha = gh.read_json(QUOTES)
            gh.write_json(QUOTES, snap, sha, f"quotes(확정): {latest}")
            print(f"확정 시세 갱신: {latest}")
        except Exception as e:
            # quotes.json 조회·쓰기 실패(1MB 초과·409·네트워크)로 여기서
            # 죽으면 이미 커밋한 백필(history/*)까지 트레이스백에 묻힌다.
            # 이 단계는 자연 치유된다 — close.py 는 하루 두 번 돌고, 매번
            # quotes.json 을 통째로 다시 쓰므로 오늘 실패해도 다음 실행이
            # 그대로 다시 커밋한다.
            print(f"[경고] quotes.json 확정 갱신 실패: {type(e).__name__}: {e} — 다음 실행이 재시도한다")
            problems.append("quotes.json 확정 갱신 실패")

    # 가상 지정가 주문 집행(설계 §4). 여기 두는 이유: 위에서 이미 보유
    # 종목의 일봉을 60거래일치 받아뒀다 — 거름망이 공짜다. 별도 워크플로로
    # 떼면 같은 일봉을 두 번 받게 되고, 두 실행 사이에 positions.json 이
    # 바뀌어 어긋날 여지도 생긴다.
    #
    # fetch_failed 가 있으면 건너뛴다. 일봉을 못 받은 종목은 거름망을
    # 통과시킬 근거 자체가 없어서, 그 종목의 체결을 조용히 놓친 채
    # "오늘은 체결 없음"으로 끝나기 때문이다 — 백필을 건너뛰는 것과 같은 이유.
    if fetch_failed:
        print(f"[경고] 일봉 실패 {len(fetch_failed)}건 — 자동 체결을 건너뛴다(다음 실행이 재시도)")
    else:
        # 예전엔 latest 하루만 넘겼다 — cron 이 하루를 통째로 드롭하거나
        # (모듈 독스트링) fetch_failed 로 하루를 건너뛰면, 그날 체결은
        # 영영 안 잡혔다. "한 번 걸러도 다음 런이 메운다"는 history/ 에만
        # 성립하는 얘기였다(missing_days 는 파일이 있으면 다시 안 보지만,
        # autofill 은 애초에 latest 아닌 날을 본 적이 없어 "다시 안 본다"
        # 조차 성립하지 않았다). todo(missing_days 로 구한, WINDOW=30
        # 거래일로 유계인 백필 대상)를 재사용해 놓친 날짜도 오래된 순으로
        # 넘긴다. latest 를 합집합으로 강제 포함하는 이유: gh.list_dir
        # 실패로 todo=[] 가 되더라도(위 8번 리뷰) 오늘 하루치 자동 체결까지
        # 같이 굶으면 안 된다.
        #
        # **결함5(2026-08-21 무동작 감사): 재시도 창을 history/ 존재 여부와
        # 완전히 분리한다.** `todo | {latest}` 만으로는 부족했다 —
        # `naver.fetch_minute` 이 한 종목에서 한 번 실패하면 autofill.py 는
        # 그 실패를 조용히 넘긴다("다음 실행이 다시 잡는다"는 전제, 그
        # 함수 안의 주석 참조). 그런데 위 백필 루프가 이 캐치업 날짜의
        # history/{day}.json 을 (이 실패와 무관하게, autofill 실행 여부와
        # 상관없이) 이미 써버렸으므로, missing_days 는 다음 실행부터 이
        # 날짜를 다시 안 본다 — `todo` 에서 영구히 빠지고, `latest` 도
        # 아니니 다시는 autofill.run 에 넘어오지 않는다. 그 실패로 놓친
        # 체결(예: 2차 매수)이 영영 복구되지 않는다 — 손절선은 3차 체결
        # 후에만 켜지므로, 그 포지션은 이후 익절로만 닫힐 수 있게 되어
        # 승률이 조용히 부풀려진다(실측 재현: tests/test_close.py 참조).
        #
        # 고친 방법: `history/` 존재 여부와 무관하게, 분봉 재생 창
        # (autofill.MINUTE_WINDOW_DAYS≈7거래일) 안의 모든 거래일을 매
        # 실행마다 다시 autofill.run 에 넘긴다. `naver.fetch_minute` 이
        # 실패할 수 있는 유일한 구간이 바로 이 창 안이므로(창을 넘긴
        # 날짜는 애초에 그 함수를 안 부르고 일봉으로만 확정한다), 이
        # 범위를 다시 시도하기만 하면 어떤 날짜의 일시적 실패도 이 창이
        # 닫히기 전에 여러 번 재시도된다. `since_for()`/`orders.replay`
        # 의 since 가드(모듈 독스트링, "하루 두 번 도는 cron" 사고 방지)가
        # 이미 체결된 구간의 중복 재생을 막으므로, 이미 끝난 날짜를 다시
        # 넘겨도 안전하다 — touched() 로 거른 뒤 실제로 닿은 종목만
        # 분봉을 다시 청구하므로 비용도 거의 없다(다른 옵션 — history 쓰기를
        # autofill 성공에 묶거나, 실패를 problems 에 얹어 rc=1 로만 드러내는
        # 것 — 은 전자는 autofill.run 의 반환값이 이 특정 실패를 구분 못 해
        # 신호를 못 만들고, 후자는 사람이 손으로 개입해야만 복구돼 자동
        # 회복이 안 된다).
        #
        # 거래일 각각을 오래된 순으로 따로따로 처리한다 — 하루치 매수가
        # 다음 날의 사다리(2차·3차 지정가)를 바꾸므로 순서가 바뀌면 안
        # 된다(autofill.run 이 매 호출마다 positions.json 을 다시 읽고
        # 다시 쓰므로, 순차 호출 자체가 이 순서를 보장한다). 하루가
        # 실패해도(문제가 problems 에 쌓인다) 나머지 날짜는 계속
        # 시도한다 — 한 종목/하루의 실패가 다른 날의 체결까지 막으면
        # 안 된다는 이 파일의 기존 원칙과 같다.
        retry_window = cal.recent(days, autofill.MINUTE_WINDOW_DAYS + 1)
        for d in sorted(set(todo) | set(retry_window) | {latest}):
            if autofill.run(bars, d, days):
                problems.append(f"자동 체결 쓰기 실패: {d}")

    print(f"완료 — 새 스냅샷 {made}건")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
