# -*- coding: utf-8 -*-
"""종목명 자동완성용 마스터. 하루 1회 갱신 (close 워크플로에 얹는다).

페이지 수를 믿지 않고 **새 종목이 안 나올 때까지** 넘긴다 — 상장/폐지로
페이지 수가 바뀌어도 안전하다. 2026-08-20 실측(마지막 빈 페이지 포함해
끝까지 다시 돌림): 코스피 51p(2,478종목), 코스닥 38p(1,821종목),
ETF 1,162개 — 단 ETF 는 **전부** 코스피+코스닥 크롤 안에 이미 있었다
(이름도 전부 일치, 불일치 0건). 총 4,299종목, master.json 실측 크기
207,470바이트(1MB 상한의 약 20%).

구현계획.md 의 공급 코드에서 아래를 고쳤다(각 지점에 주석 있음) — 근거는
tests/test_master.py 모듈 docstring 참조:

1. `crawl()` 이 일시 장애·markup 붕괴를 만나면 그때까지 모은 **부분
   리스트를 정상값처럼** 돌려주던 것을 고쳤다. `MIN_SANE`(공급값 2000)은
   코스피 하나가 30페이지쯤에서 끊겨도 코스닥과 더하면 가볍게 넘어서,
   "삼성전자보다 뒤에 상장된 회사가 전부 빠진" 마스터가 조용히 커밋될 수
   있었다. 이제 페이지 하나가 실패하면(EmptyParseError 포함 — 0건이
   항상 "끝"을 뜻하진 않는다) 같은 페이지를 한 번 재시도하고, 그래도
   실패하면 부분 리스트 대신 `CrawlFailed` 를 낸다. `max_pages` 안에서
   정상 종료 신호를 한 번도 못 만나도 마찬가지다(§`crawl` 참조).
2. `build()` 가 코스피/코스닥 실패까지 삼키지 않는다. ETF(`_etf()`)는
   "있으면 좋은 것"이라 여전히 실패를 삼키지만, 코스피·코스닥은 본체라
   `CrawlFailed` 를 그대로 전파한다.
3. `MIN_SANE` 을 2000 → 4000 으로 올렸다. 실측 4,299 의 약 93% — 375건
   (8.7%)짜리 회귀(naver.py 실측: 정규식이 영숫자 코드를 놓치는 사고)를
   실제로 잡으면서, 일일 상장/폐지 등락에는 여유가 있다.
4. `main()` 이 `gh.read_json`/`gh.write_json` 을 무방비로 부르지 않는다
   — 네트워크·409·1MB 초과 등으로 실패하면 트레이스백 대신 진단을 찍고
   rc=1 로 물러난다(quotes.py·close.py 가 이미 겪고 고친 것과 같은 결함).
"""
from __future__ import annotations

import sys

from . import gh, naver, quotes

MASTER = "master.json"

# 실측 4,299(2026-08-20, 코스피 2,478 + 코스닥 1,821, ETF 는 전부 중복)의
# 약 93%. naver.py 가 실측한 "정규식이 영숫자 코드 375건(8.7%)을 놓치는"
# 부류의 회귀를 실제로 잡는 하한이면서, 하루 단위 상장/폐지 등락으로
# 조용히 트립되지 않을 여유(약 300건)를 남긴다. 2000 은 이 대비 너무
# 낮아 총 붕괴만 잡고 부분 붕괴는 놓친다(tests/test_master.py 참조).
MIN_SANE = 4000


class CrawlFailed(Exception):
    """크롤이 끝까지 확실하게 못 갔다.

    1) 페이지 하나에서 일시 장애가 재시도 후에도 계속되거나, 2) max_pages
    안에서 정상 종료 신호(EmptyParseError 확정 또는 '새 게 없다')를 한 번도
    못 만났을 때 낸다. 두 경우 모두 부분 리스트를 조용히 돌려주면
    "그럴듯하지만 잘린" 마스터가 MIN_SANE 을 우연히 넘겨 그대로 커밋될 수
    있다 — 그래서 부분 결과를 버리고 예외로 명확히 알린다.

    ETF(`_etf()`)는 이 예외를 쓰지 않는다 — ETF 실패는 원래도 허용된
    열화다(공급 test_ETF_실패해도_나머지는_남는다 참조, 그리고 실측상
    ETF 는 이미 코스피/코스닥 크롤에 전부 포함돼 있어 잃을 것도 적다).
    """


def _fetch_page(sosok: int, page: int):
    """naver.fetch_market_sum 한 번 + 실패 시 같은 페이지를 한 번 재시도.

    naver._fetch 는 "재시도 안 함"이 원칙이다(30분 주기가 곧 재시도라서,
    naver.py 모듈 docstring 참조) — 이 스크립트는 **하루 1회**라 그 근거가
    적용되지 않는다. 여기서 실패하면 24시간을 날린다.

    반환값:
      - dict: 정상 데이터(빈 dict 포함 — '새 게 없다' 정지 판단은
        crawl() 이 한다).
      - None: 이 페이지가 "끝"으로 **확정**됐다(EmptyParseError 가
        재시도 후에도 그대로 남았다).

    EmptyParseError 도 재시도 대상에 넣는다. parse_market_sum 은 "행이
    0건"일 때 이 예외를 내는데, 그게 항상 "끝을 지났다"를 뜻하진 않는다
    — 서버가 일시적으로 빈 페이지를 준 경우도 파싱 결과는 똑같이 0건으로
    보여 구분이 안 된다. 크롤은 설계상 끝에서 정확히 한 번 이 예외를
    만나 종료하므로, 여기서 한 번 더 확인해도 크롤 하나당 요청이 1건
    늘 뿐이다 — "일시적으로 빈 페이지를 진짜 끝으로 오판"할 확률을
    줄이는 값싼 보험이다.
    """
    for attempt in (1, 2):
        try:
            return naver.fetch_market_sum(sosok, page)
        except naver.EmptyParseError:
            if attempt == 2:
                return None
        except Exception as e:
            if attempt == 2:
                raise CrawlFailed(
                    f"sosok={sosok} page={page}: 재시도 후에도 실패 — "
                    f"{type(e).__name__}: {e}") from e
            print(f"[경고] sosok={sosok} page={page}: {type(e).__name__}: {e} — 재시도")
    return None  # pragma: no cover — 위 루프가 항상 반환하거나 예외를 낸다


def crawl(sosok: int, max_pages: int = 150) -> list:
    """[(코드, 이름)] 을 **페이지 순서 그대로** 돌려준다 (= 시가총액 순).

    새 종목이 안 나올 때까지(또는 EmptyParseError 확정까지) 넘긴다 —
    페이지 수가 상장/폐지로 바뀌어도 안전하다. 2026-08-20 실측: 코스피
    51p(끝 확인용 빈 페이지 포함), 코스닥 38p.

    ⚠ 개수 하한을 두지 않는다 — 마지막 페이지는 원래 적다(naver.py 의
    parse_market_sum docstring 참조, 실측: 코스피 28건, 코스닥 21건).

    ⚠ max_pages 안에서 정상 종료 신호를 한 번도 못 만나면 예외를 낸다 —
    조용히 잘린 리스트를 돌려주지 않는다(`CrawlFailed` 참조). 코스피가
    가까운 미래에 150페이지(현재 51페이지의 3배 가까이)를 넘는 일은
    없다고 보지만, 만에 하나 닿으면 "리스트가 잘렸는데 아무도 모른다"
    보다 "실패로 드러난다"가 낫다.
    """
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        got = _fetch_page(sosok, page)
        if got is None:                 # EmptyParseError 확정 = 끝
            return out
        before = len(out)
        for code, name in got.items():
            if code not in seen:
                seen.add(code)
                out.append((code, name))
        if len(out) == before:          # 새 게 없다 = 마지막 페이지를 지났다
            return out
    raise CrawlFailed(f"sosok={sosok}: max_pages({max_pages})에 닿았는데 끝을 못 찾았다")


def build() -> dict:
    """**items 는 dict 가 아니라 리스트다** — 순서가 곧 관련도이기 때문이다.

    시가총액 페이지는 큰 회사부터 나온다. 그 순서를 그대로 보존하면 자동완성이
    삼성전자를 먼저 보여준다. dict 로 두면 두 군데서 순서가 깨진다:
      1. `gh.write_json` 의 `sort_keys=True` 가 코드순으로 다시 정렬한다
      2. JS 의 `Object.entries` 는 정수형 키("247540")를 앞으로 당긴다 —
         앞자리 0 이 붙은 "005930" 은 뒤로 밀린다
    둘 다 "숫자 작은 코드만 보이는" 자동완성을 만든다.

    코스피/코스닥 크롤은 여기서 순서대로(아직 병렬 아님) 직접 부른다 —
    ETF 와 달리 실패를 여기서 잡지 않는다: `crawl()` 이 낸 `CrawlFailed`
    는 그대로 이 함수 밖으로 전파된다. 코스피가 실패했는데 코스닥+ETF
    만으로 조용히 마스터를 만들면, 그 결과가 우연히 MIN_SANE 을 넘어
    "본체(코스피 전체)가 빠졌는데 통과하는" 사고가 재발한다 — 실패를
    숨기지 않는 게 이 함수가 지키는 원칙이다. 코스피가 먼저 실패하면
    코스닥·ETF 조회 자체를 시도하지 않는 이점도 있다(불필요한 네트워크
    호출을 줄인다).
    """
    kospi = crawl(sosok=0)
    kosdaq = crawl(sosok=1)
    etf = _etf()
    items, seen = [], set()
    for group in (kospi, kosdaq, etf):      # 코스피 → 코스닥 → ETF
        for code, name in group:
            if code not in seen:
                seen.add(code)
                items.append([code, name])
    return {"generated_kst": quotes.now_kst(), "count": len(items), "items": items}


def _etf() -> list:
    try:
        return list(naver.fetch_etf().items())
    except Exception as e:
        print(f"[경고] ETF 실패: {type(e).__name__}: {e}")
        return []


def is_sane(m: dict) -> bool:
    return m.get("count", 0) >= MIN_SANE


def main() -> int:
    try:
        m = build()
    except Exception as e:
        # crawl() 의 CrawlFailed 뿐 아니라 예상 못 한 다른 예외까지 넓게
        # 잡는다 — 이 시점엔 아직 gh 를 전혀 안 건드렸으니 잃을 것도 없다.
        # 트레이스백으로 죽는 대신 진단을 남기고 물러난다(다음 실행이
        # 자연스러운 재시도).
        print(f"[중단] 마스터 수집 실패: {type(e).__name__}: {e} — 직전 마스터 유지")
        return 1
    if not is_sane(m):
        print(f"[중단] 종목 {m['count']}건 — 파싱이 무너졌다. 직전 마스터 유지")
        return 1
    try:
        _, sha = gh.read_json(MASTER)
        gh.write_json(MASTER, m, sha, f"master: {m['count']}종목")
    except Exception as e:
        # quotes.py·close.py 가 이미 겪고 고친 것과 같은 결함 — 이 호출을
        # 어떤 try 에도 안 두면 네트워크·409·1MB 초과 등으로 트레이스백이
        # 난다. 여기까지 온 이상 신선한 데이터는 손에 쥐고 있으니 아깝지만,
        # 커밋하지 않고 깨끗하게 물러나는 게 옳다 — 다음 실행이 재시도한다.
        print(f"[중단] master.json 갱신 실패: {type(e).__name__}: {e} — 직전 마스터 유지")
        return 1
    print(f"완료 {m['count']}종목")
    return 0


if __name__ == "__main__":
    sys.exit(main())
