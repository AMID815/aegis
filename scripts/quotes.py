# -*- coding: utf-8 -*-
"""장중 시세 갱신 (30분). 파생 지표는 계산하지 않는다 — 페이지 몫이다.

**손상 항목(bad)이 있어도 멈추지 않는다.** quotes.json 은 언제든 다시 만들
수 있고, 여기서 멈추면 화면만 낡는다 — intake.py(거부)·close.py(중단)와는
다른 결정이다. 대신 개수를 스냅샷에 실어 화면(§7/§8)이 말하게 한다.

**단, "보유 0건"과 "전부 격리(dropped)돼서 0건으로 보인 것"은 다르다.**
전자는 실패가 아니라서 커밋해야 하고(달력·시각 갱신), 후자를 그대로
통과시키면 정상 quotes.json 이 빈 스냅샷으로 덮이고 fresh as_of_kst 가
§7 의 stale 배지를 조용히 재운다 — 이 모듈이 막으려는 바로 그 사고(§8).
`should_commit` 이 이 둘을 가른다.

**이 모듈은 넓게 잡는다.** naver.fetch_quotes 는 배치 안에서 에러를
격리하지 않는다 — 부분적으로만 성공한 스냅샷은 신선한 값과 낡은 값이
섞여, 진짜 상장폐지와 구분이 안 가기 때문이다. 그래서 이 모듈은 커밋
직전까지 벌어지는 실패를 넓게 잡아 "커밋하지 않는다 = 직전 값 유지"로
수렴시킨다 — positions 조회, 시세, 달력, quotes.json 자체의 sha 조회까지.
단 positions 조회(넓게)와 정규화(좁게, RejectedError 하나뿐)는 서로 다른
try 로 나눈다 — 한 블록에 몰아두면 normalize() 자신의 버그(TypeError 등)
까지 "positions 를 읽을 수 없다"로 뭉개져 코드 버그가 코드 버그로
보이지 않는다.
"""
from __future__ import annotations

import datetime as dt
import sys

from . import gh, models, naver

QUOTES = "quotes.json"
POSITIONS = "positions.json"
KST = dt.timezone(dt.timedelta(hours=9))
INDEX = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}

# models.normalize() 가 최상위 구조 자체를 못 읽었을 때(positions 가 list
# 아님 등) dropped 에 싣는 합성 마커. 개별 항목 손상과 구분하는 데 쓴다 —
# 아래 main() 참조.
WHOLE_FILE_MARKER = "(파일 전체)"


def now_kst() -> str:
    """모든 대기 뒤에 찍는다 — 대기 전 시각을 쓰면 표기가 거짓이 된다."""
    return dt.datetime.now(KST).replace(microsecond=0).isoformat()


def open_codes(state: dict) -> list:
    """보유 중(open) 종목 코드만, 중복 없이(입력 순서 보존).

    positions 는 배열이라 같은 코드가 두 번 열릴 수 있다(예: 7월 매수 +
    8월 매수 — id 는 다르고 둘 다 open). 중복을 그대로 두면 그 코드가
    응답에서 빠졌을 때 missing_codes 가 asked 리스트를 그대로 훑어서
    같은 코드가 missing 에 두 번 실리고 fail_count 가 부풀어 오른다
    (구현계획.md 코드리뷰 이월 항목, Task 7 담당).

    `p["code"]` 는 bare subscript 다 — `state` 가 models.normalize() 를
    거쳤다면 code 키 없는(또는 형식이 틀린) 항목은 이미 dropped 로
    격리되어 여기 도달하지 않으므로 항상 존재가 보장된다(main() 의
    호출 경로). 이 함수 자체는 그 보장에 기대는 얇은 헬퍼일 뿐이라
    normalize 를 거치지 않은 값을 직접 넘기면(예: 이 함수를 단독으로
    테스트할 때처럼) 진짜로 code 가 없는 항목에서 KeyError 로 죽는다 —
    조용히 빈 문자열을 끼워넣는 것보다 그게 낫다: 이 함수가 기대하는
    입력 모양이 깨졌다는 신호이지 삼켜서 좋을 값이 아니다.
    """
    codes = [p["code"] for p in state.get("positions", [])
             if p.get("status") == "open"]
    return list(dict.fromkeys(codes))


def live_codes(state: dict) -> list:
    """오늘 시세·일봉이 필요한 종목 — **보유 중(open) + 자동매수 대기(pending)**.

    `open_codes` 를 그대로 쓰면 안 되는 이유(2026-08-21 실측 사고):

    close.py 는 이 목록으로 일봉을 받고, autofill.run 은 그 `bars` 에서 대기
    종목의 그날 저가를 찾아 지정가 도달을 판정한다. 대기 종목이 목록에
    없으면 `bars.get(code)` 가 None 이라 그 자리에서 `continue` —
    **자동매수가 한 번도 안 걸린다.** 라이브에서 실제로 그랬다(금호전기
    001210 이 대기 중인데 조회 종목이 빈 배열이었다). 화면의 "대기 표
    현재가가 늘 비어 있다"는 증상은 같은 원인의 겉모습일 뿐이고, 진짜
    피해는 기능이 통째로 안 돈 것이었다.

    종결(closed)·만료(expired)는 뺀다 — 오늘 시세가 필요 없고, 상폐된
    종목이 매번 조회를 실패시켜 fail_count 를 부풀리는 것도 막는다
    (open_codes 가 원래 지키던 것과 같은 이유).

    `open_codes` 는 지우지 않고 남긴다. "지금 실제로 들고 있는 것"이라는
    다른 뜻이 필요한 자리가 앞으로 생길 수 있고, 이름과 뜻이 어긋난 채로
    범위만 넓히는 것보다 두 이름을 각자 정직하게 두는 쪽이 낫다.
    """
    codes = [p["code"] for p in state.get("positions", [])
             if p.get("status") in (models.OPEN, models.PENDING)]
    return list(dict.fromkeys(codes))


def build(got: dict, asked: list, days: list, bench: dict,
          now_kst: str, is_final: bool, dropped: int = 0,
          bench_history: dict | None = None,
          benchmark_failed: list | None = None) -> dict:
    # 매개변수 이름 `now_kst` 가 모듈 전역 함수 `now_kst()` 를 이 함수
    # 몸통 안에서 가린다. 지금은 무해하다 — 아래에서 함수를 호출하지
    # 않고 이미 계산된 문자열 값을 그대로 담기만 한다(호출자인 main() 이
    # "모든 대기 뒤에" now_kst() 를 미리 불러 넘긴다). 나중에 이 함수
    # 안에서 시각을 다시 구해야 하는 코드가 추가되면 이 이름이 함정이
    # 된다는 점만 남겨둔다.
    missing = naver.missing_codes(asked, got)
    return {
        "as_of_kst": now_kst,
        "is_final": is_final,
        "ok_count": len(got),
        "fail_count": len(missing),
        "missing": missing,
        "positions_dropped": dropped,   # 화면이 이걸 보고 경고를 띄운다
        "trading_days": days,
        "benchmark": bench,
        # 최신 레벨(benchmark)만으로는 §6-2 가 든 이유("같은 기간 지수
        # 수익률")를 계산할 수 없다 — 그 계산에 필요한 과거 값을 같이
        # 싣는다. trading_days 와 같은 YYYY-MM-DD 키라 날짜로 바로
        # 대조된다. 요청 수는 늘지 않는다(fetch_benchmark 참조).
        "benchmark_history": bench_history or {},
        # 로그는 아무도 안 본다 — 화면이 말하게 한다(§8). 지수 하나가
        # 계속 실패해도 요약 박스에서 "숫자 하나가 조용히 빠진 것"으로만
        # 보이면 아무도 못 알아챈다.
        "benchmark_failed": benchmark_failed or [],
        "quotes": got,
    }


def should_commit(snap: dict) -> bool:
    """전부 실패했을 때만 안 쓴다. 보유 0건은 실패가 아니다 — 단, 그 0건이
    "진짜 무보유"가 아니라 "정규화 과정에서 전부 격리(dropped)돼서 0건으로
    보인 것"이면 실패로 취급한다. 두 경우 모두 ok_count==fail_count==0 이라
    ok_count/fail_count 만으로는 구분이 안 된다 — positions_dropped 를
    같이 봐야 한다."""
    asked = snap["ok_count"] + snap["fail_count"]
    if asked == 0:
        return snap["positions_dropped"] == 0
    return snap["ok_count"] > 0


def _iso_day(d: str) -> str:
    """`YYYYMMDD` → `YYYY-MM-DD`. naver.trading_days 가 만드는 것과 같은
    포맷 — 나중에 이 값을 trading_days 와 날짜로 대조하려면(§6-2, Task 12
    가 보유기간 지수 수익률을 계산할 때) 형식이 같아야 한다."""
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def fetch_benchmark() -> tuple:
    """지수는 있으면 좋은 것 — 하나가 실패해도 나머지·본 실행을 막지 않는다.

    `bars[max(bars)]` — 키는 `YYYYMMDD` 8자리 고정폭이라 문자열 최댓값이
    곧 최신 날짜다(naver.trading_days 와 같은 근거).

    ⚠ 장중(당일 봉이 아직 없는 시간대, §5-3)에는 이게 **어제 종가**를
    돌려준다 — fchart 의 당일 봉은 정규장 마감(15:31~32) 뒤에야 나오기
    때문이다. 반면 quotes 쪽 개별 종목 가격(naver.fetch_quotes)은 정규장
    중 실시간으로 갱신되는 값이다. 그래서 장중 스냅샷은 "개별 종목은
    방금 가격, 지수는 어제 종가"가 섞인다 — 알려진 비대칭이고, 이 모듈은
    파생 지표(수익률 등)를 계산하지 않으므로(페이지 몫) 여기서 고칠 문제가
    아니다.

    **n=250 을 쓰는 이유**: naver.fetch_bars 는 한 번의 요청으로 최근 n일치
    전체를 돌려준다 — n=2 를 n=250 으로 올려도 요청 수는 그대로다(0 증가).
    §6-2 는 벤치마크를 두는 이유로 "같은 기간 지수 수익률이 없으면 '장이
    좋아서 번 것'과 '스크리너가 좋아서 번 것'을 구분할 수 없다"를 들었는데,
    최신 레벨 하나만으로는 그 계산 자체가 불가능하다(과거 값이 없다) —
    history 를 같이 실어 이 모듈이 아니라 이걸 쓰는 쪽(Task 12)이 임의의
    보유기간에 대해 계산할 수 있게 한다. 크기는 250일 × 지수 2개 ≈ 5KB —
    1MB 상한에 비하면 무시할 만하다.

    반환값은 (values, history, failed) 세 개:
    - values: {"KOSPI": 최신 레벨, ...} — 기존과 동일, 화면 요약 박스용
    - history: {"KOSPI": {"2026-08-19": 6471.17, ...}, ...} — YYYY-MM-DD 키
    - failed: 실패한 지수 이름 리스트 — 로그로만 남기면 §8 이 무색해진다
      ("로그는 아무도 안 본다" — 화면이 말하게 한다)
    """
    values: dict = {}
    history: dict = {}
    failed: list = []
    for name, sym in INDEX.items():
        try:
            bars = naver.fetch_bars(sym, n=250)
            values[name] = bars[max(bars)]["close"]
            history[name] = {_iso_day(d): b["close"] for d, b in bars.items()}
        except Exception as e:      # 지수는 있으면 좋은 것 — 없다고 멈추지 않는다
            print(f"[경고] 지수 {name} 실패: {type(e).__name__}: {e}")
            failed.append(name)
    return values, history, failed


def main() -> int:
    bad: list = []
    try:
        state, _ = gh.read_json(POSITIONS, default=models.empty_state())
    except Exception as e:
        # positions.json 은 IRREPLACEABLE 이라 손상 시 strict 여부와 무관하게
        # gh.CorruptJSON, 그 외 1MB 초과·API 오류의 RuntimeError, 네트워크
        # 문제의 URLError 까지 — 이 조회 하나에서 나올 수 있는 실패 종류가
        # 넓다. 이 블록은 그래서 넓게 잡는다. (원래는 이 호출이 아래
        # normalize() 와 한 try 에 묶여 models.RejectedError 만 잡았다 —
        # 그러면 여기서 나는 예외들은 전혀 못 잡혀 main() 밖으로 그대로
        # 새어나가 트레이스백으로 죽었다.)
        print(f"[중단] positions.json 조회 실패: {type(e).__name__}: {e}")
        return 1
    try:
        state = models.normalize(state, bad)
    except models.RejectedError as e:
        # normalize() 가 실제로 던지는 건 이거 하나뿐이다(모르는 schema).
        # 위 조회 블록과 일부러 분리해서 여기는 좁게 잡는다 — 한 블록에
        # 몰아 넓게 잡으면, normalize() 자신의 버그(예상 못 한 TypeError
        # 등)까지 "positions 를 읽을 수 없다"로 뭉개져서 코드 버그가 코드
        # 버그로 드러나지 않는다.
        print(f"[중단] positions.json 스키마를 알 수 없다: {e}")
        return 1
    if bad:
        # **여기서는 멈추지 않는다.** quotes.json 은 언제든 다시 만들 수 있고,
        # 멈추면 화면만 낡는다. 대신 개수를 스냅샷에 실어 화면이 말하게 한다.
        #
        # 단, bad 가 최상위 구조 손상의 합성 마커 하나("(파일 전체)")인
        # 경우는 "해석 불가 항목 1건"이라고 찍으면 안 된다 — 그건 보유
        # 10건짜리 파일이 통째로 안 읽혀 전부 사라진 사고를 "기록 1건을
        # 못 읽었다"로 축소 보고하는 것이다(정규화된 state 는 이미
        # empty_state() 라 이 실행에서 보유가 전부 안 보인다).
        if len(bad) == 1 and bad[0].get("id") == WHOLE_FILE_MARKER:
            note = bad[0].get("note", "")
            print(f"[경고] positions.json 최상위 구조를 읽지 못했다 — 보유 전체가 가려짐: {note}")
        else:
            print(f"[경고] 해석 불가 항목 {len(bad)}건 — 이 종목들은 시세를 붙이지 않는다")
    codes = live_codes(state)
    try:
        got = naver.fetch_quotes(codes)
    except Exception as e:
        print(f"[중단] 시세 실패: {type(e).__name__}: {e}")
        return 1                      # 커밋하지 않는다 = 직전 값 유지
    try:
        days = naver.fetch_trading_days(250)
    except Exception as e:
        print(f"[중단] 달력 실패: {type(e).__name__}: {e}")
        return 1
    bench, bench_history, bench_failed = fetch_benchmark()
    snap = build(got, codes, days, bench, now_kst(),
                 is_final=False, dropped=len(bad),
                 bench_history=bench_history, benchmark_failed=bench_failed)
    if not should_commit(snap):
        if snap["ok_count"] + snap["fail_count"] == 0:
            print(f"[중단] 보유가 전부 격리됨(positions_dropped={snap['positions_dropped']}) — 직전 값 유지")
        else:
            print(f"[중단] 전부 실패 ({snap['fail_count']}건) — 직전 값 유지")
        return 1
    try:
        _, sha = gh.read_json(QUOTES)
    except Exception as e:
        # 원래는 이 호출이 어떤 try 안에도 없었다 — quotes.json 이 1MB를
        # 넘기거나(사실상 없음), sha 조회 자체가 409·5xx·네트워크 오류로
        # 실패하면 시세는 다 받아놓고도 여기서 트레이스백으로 죽었다.
        # 이 시점까지 온 이상 이미 신선한 시세를 손에 쥐고 있으니 아깝지만,
        # 커밋하지 않고 깨끗하게 물러나는 게 옳다 — 다음 30분 뒤 실행이
        # 자연스러운 재시도다.
        print(f"[중단] quotes.json 조회 실패: {type(e).__name__}: {e}")
        return 1
    gh.write_json(QUOTES, snap, sha, f"quotes: {snap['as_of_kst']}")
    print(f"완료 ok={snap['ok_count']} fail={snap['fail_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
