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
"""
from __future__ import annotations

import sys

from . import trading_calendar as cal
from . import gh, models, naver, quotes

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
    """
    key = day.replace("-", "")
    closes = {code: b[key]["close"] for code, b in bars.items() if key in b}
    if not closes:
        return None
    return {"date": day, "closes": closes, "positions": state.get("positions", [])}


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
    codes = quotes.open_codes(state)

    try:
        days = naver.fetch_trading_days(250)
    except Exception as e:
        print(f"[중단] 달력 실패: {type(e).__name__}: {e}")
        return 1
    if cal.too_short(days, need=WINDOW + 2):
        print(f"[중단] 달력이 짧다({len(days)}일) — 잘못 메울 바에 쉰다")
        return 1

    todo = missing_days(days, WINDOW, gh.list_dir("history"))
    if not todo:
        print("메울 날짜 없음")

    # 이번 실행 안에서 벌어진 "문제"를 전부 여기 쌓는다 — 부분 성공 자체를
    # 막지는 않되(그게 이 모듈의 핵심), 종료코드는 정직하게 실패로 낸다.
    # 각 항목이 이번 실행에서 뭔가를 완전히 끝내지 못했다는 신호일 뿐, 다음
    # 실행(하루 두 번)이 자연히 재시도하므로 데이터가 위험해지지는 않는다.
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
    if fetch_failed:
        problems.append(f"일봉 실패 {len(fetch_failed)}건")

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
    got = {}
    if final:
        got = {c: {"price": v,
                   "name": next((p["name"] for p in state["positions"]
                                 if p["code"] == c), c),
                   "status": "tradable"}
               for c, v in final["closes"].items()}
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
    print(f"완료 — 새 스냅샷 {made}건")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
