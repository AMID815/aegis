# -*- coding: utf-8 -*-
"""장중 시세 갱신 (30분). 파생 지표는 계산하지 않는다 — 페이지 몫이다.

**손상 항목(bad)이 있어도 멈추지 않는다.** quotes.json 은 언제든 다시 만들
수 있고, 여기서 멈추면 화면만 낡는다 — intake.py(거부)·close.py(중단)와는
다른 결정이다. 대신 개수를 스냅샷에 실어 화면(§7/§8)이 말하게 한다.

**이 모듈은 넓게 잡는다.** naver.fetch_quotes 는 배치 안에서 에러를
격리하지 않는다 — 부분적으로만 성공한 스냅샷은 신선한 값과 낡은 값이
섞여, 진짜 상장폐지와 구분이 안 가기 때문이다. 그래서 이 모듈은 커밋
직전까지 벌어지는 모든 예외를 넓게 잡아 "커밋하지 않는다 = 직전 값 유지"
로 수렴시킨다 — positions 조회(스키마 불일치·CorruptJSON·API 오류 모두
포함), 시세, 달력, quotes.json 자체의 sha 조회까지.
"""
from __future__ import annotations

import datetime as dt
import sys

from . import gh, models, naver

QUOTES = "quotes.json"
POSITIONS = "positions.json"
KST = dt.timezone(dt.timedelta(hours=9))
INDEX = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}


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


def build(got: dict, asked: list, days: list, bench: dict,
          now_kst: str, is_final: bool, dropped: int = 0) -> dict:
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
        "quotes": got,
    }


def should_commit(snap: dict) -> bool:
    """전부 실패했을 때만 안 쓴다. 보유 0건은 실패가 아니다."""
    asked = snap["ok_count"] + snap["fail_count"]
    return asked == 0 or snap["ok_count"] > 0


def fetch_benchmark() -> dict:
    """지수는 있으면 좋은 것 — 하나가 실패해도 나머지·본 실행을 막지 않는다.

    `bars[max(bars)]` — 키는 `YYYYMMDD` 8자리 고정폭이라 문자열 최댓값이
    곧 최신 날짜다(naver.trading_days 와 같은 근거).

    ⚠ 장중(당일 봉이 아직 없는 시간대, §5-3)에는 이게 **어제 종가**를
    돌려준다 — fchart 의 당일 봉은 정규장 마감(15:31~32) 뒤에야 나오기
    때문이다. 반면 quotes 쪽 개별 종목 가격(naver.fetch_quotes)은 정규장
    중 실시간으로 갱신되는 값이다. 그래서 장중 스냅샷은 "개별 종목은
    방금 가격, 지수는 어제 종가"가 섞인다 — 알려진 비대칭이고, 이 모듈은
    파생 지표(수익률 등)를 계산하지 않으므로(페이지 몫) 여기서 고칠 문제가
    아니다. 지수의 장중 실시간 값을 받으려면 이 함수가 아니라 별도
    조사(폴링 엔드포인트가 지수 코드를 받는지 등)가 먼저 필요하다 — 지금
    실측된 사실("Index symbols KOSPI/KOSDAQ return fractional closes via
    fetch_bars")의 범위 밖이라 손대지 않는다.
    """
    out = {}
    for name, sym in INDEX.items():
        try:
            bars = naver.fetch_bars(sym, n=2)
            out[name] = bars[max(bars)]["close"]
        except Exception as e:      # 지수는 있으면 좋은 것 — 없다고 멈추지 않는다
            print(f"[경고] 지수 {name} 실패: {type(e).__name__}: {e}")
    return out


def main() -> int:
    try:
        state, _ = gh.read_json(POSITIONS, default=models.empty_state())
        bad = []
        state = models.normalize(state, bad)
    except Exception as e:
        # 원래는 models.RejectedError(모르는 schema)만 잡았다. 그러면
        # gh.read_json 자신이 내는 예외 — positions.json 은 IRREPLACEABLE
        # 이라 손상 시 strict 여부와 무관하게 gh.CorruptJSON, 그 외
        # 1MB 초과·API 오류의 RuntimeError, 네트워크 문제의 URLError —
        # 는 여기서 못 잡혀 main() 밖으로 그대로 새어나가 트레이스백으로
        # 죽는다. 이 모듈이 지향하는 "넓게 잡고 커밋하지 않는다"는 원칙과
        # 어긋나므로 넓혔다.
        print(f"[중단] positions 를 읽을 수 없다: {type(e).__name__}: {e}")
        return 1
    if bad:
        # **여기서는 멈추지 않는다.** quotes.json 은 언제든 다시 만들 수 있고,
        # 멈추면 화면만 낡는다. 대신 개수를 스냅샷에 실어 화면이 말하게 한다.
        print(f"[경고] 해석 불가 항목 {len(bad)}건 — 이 종목들은 시세를 붙이지 않는다")
    codes = open_codes(state)
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
    snap = build(got, codes, days, fetch_benchmark(), now_kst(),
                 is_final=False, dropped=len(bad))
    if not should_commit(snap):
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
