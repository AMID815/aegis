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

**리뷰 2라운드(F1~F3) 반영**:

F1. 1라운드의 "페이지 하나 재시도" 만으로는 구멍이 남아 있었다 — 두 번
   연속 EmptyParseError 면 무조건 "끝"으로 확정했는데, 그건 "진짜 끝"과
   "일시 장애가 두 번 우연히 겹친 것"을 구분 못 한다. 실측: 코스피가
   37페이지에서 (장애로) 끊겨도 그때까지 4,010건이 모여 MIN_SANE(4000)을
   우연히 통과해 잘린 마스터가 그대로 커밋됐다. 게다가 재시도 1차가
   "하드 장애"고 2차가 EmptyParseError인 경우와 그 반대 순서가 서로 다른
   결론을 냈다(순서 의존 버그). 고친 내용:
   - `_fetch_page` 는 두 시도 중 **하나라도** 하드 장애(EmptyParseError가
     아닌 예외)를 겪으면, 다른 시도가 EmptyParseError로 왔더라도 "끝"으로
     확정하지 않는다(순서 무관 — 리뷰 F1 표의 네 조합을 전부 手 계산으로
     확인, tests 참조). 두 시도 **모두** EmptyParseError 일 때만 "이
     페이지는 비었다"를 확정해서 `crawl()` 에 넘긴다.
   - `crawl()` 은 페이지 1에서 "꽉 찬 페이지"의 행 수(`page_size`)를
     배운다(실측: 코스피/코스닥 모두 마지막 페이지 직전까지 전부 50행,
     마지막만 짧다 — 28/21행). 같은 크기의 페이지가 **연속 2번 이상**
     나온 직후 곧장 0행 확정이 오면 — 실측된 정상 종료 패턴(짧은 페이지
     → 0행)이 아니므로 — 끝으로 믿지 않고 `CrawlFailed` 를 낸다. 반대로
     짧은 페이지 바로 다음의 0행 확정은 그대로 끝으로 받아들인다.
     "연속 2번"인 이유: 페이지 1 하나만으로는 그 크기가 "이 사이트의
     페이지당 행 수"인지 "이 시장 전체가 그만큼밖에 없다"인지 구분할
     근거가 없다 — 두 번째 페이지에서도 같은 크기가 반복돼야 우연이
     아니라는 확신이 선다.
F2. `MIN_SANE` 테스트가 상수 하한만 확인해 상한 없는 회귀(예:
   `MIN_SANE = 999999`, 매일 게이트가 트립됨)를 못 잡았다 — `is_sane()`
   의 실제 동작(실측 총계는 통과, 알려진 회귀는 차단)으로 바꿨다.
F3. `items` 가 dict 가 아니라 list 여야 하는 이유(이 모듈이 가장 길게
   설명하는 불변식)를 실제로 `json.dumps(..., sort_keys=True)` 를 거쳐
   검증하는 테스트가 없었다 — 추가했다(tests 참조).
"""
from __future__ import annotations

import sys
import traceback

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

    다음 중 하나면 낸다:
      1) 페이지 하나에서 하드 장애가 재시도 후에도 남거나, 하드 장애와
         EmptyParseError 가(순서 무관) 섞여 "끝"인지 "장애"인지 확정할
         수 없을 때(`_fetch_page`).
      2) "꽉 찬 페이지"가 연속 2번 이상 나온 직후 곧장 0행이 확정될 때 —
         실측된 정상 종료 패턴(짧은 페이지 다음의 0행)이 아니라서 장애로
         의심된다(`crawl`, 리뷰 F1).
      3) `max_pages` 안에서 정상 종료 신호를 한 번도 못 만났을 때.

    세 경우 모두 부분 리스트를 조용히 돌려주면 "그럴듯하지만 잘린"
    마스터가 MIN_SANE 을 우연히 넘겨 그대로 커밋될 수 있다 — 그래서
    부분 결과를 버리고 예외로 명확히 알린다.

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
      - None: **두 시도 모두** EmptyParseError — "이 페이지는 비었다"가
        확정됐다(그게 정말 "끝"인지는 crawl() 이 직전 페이지 크기를 보고
        다시 판단한다, §crawl, 리뷰 F1).

    두 시도 중 **하나라도** 하드 장애(EmptyParseError 가 아닌 예외)를
    겪으면, 다른 시도가 EmptyParseError 로 왔더라도 "끝"으로 확정하지
    않고 CrawlFailed 를 낸다 — 순서와 무관하게 같은 결론을 내야 한다.
    처음엔 "1차가 하드 장애, 2차가 EmptyParseError" 만 이렇게 처리하고
    반대 순서("1차 EmptyParseError, 2차 하드 장애")는 우연히 이미
    CrawlFailed 를 냈는데, 그 비대칭 자체가 버그였다 — 이제 두 순서
    모두 CrawlFailed 다(tests 의 순서 뒤바꾼 두 테스트가 이걸 고정한다).
    """
    first_kind = None    # "empty" | "hard" | None(아직 1차 시도 전)
    first_exc = None
    for attempt in (1, 2):
        try:
            return naver.fetch_market_sum(sosok, page)
        except naver.EmptyParseError as e:
            if attempt == 1:
                first_kind, first_exc = "empty", e
                print(f"[정보] sosok={sosok} page={page}: 0행 — 재시도로 확인")
                continue
            if first_kind == "empty":
                return None            # 두 번 다 EmptyParseError = 이 페이지는 비었다(확정)
            raise CrawlFailed(
                f"sosok={sosok} page={page}: 1차={type(first_exc).__name__}, "
                f"2차=EmptyParseError — 끝인지 장애인지 확정할 수 없다") from e
        except Exception as e:
            if attempt == 1:
                first_kind, first_exc = "hard", e
                print(f"[경고] sosok={sosok} page={page}: {type(e).__name__}: {e} — 재시도")
                continue
            # attempt == 2 — 재시도 후에도 하드 장애면 1차가 무엇이었든 낸다
            raise CrawlFailed(
                f"sosok={sosok} page={page}: 재시도 후에도 실패 — "
                f"{type(e).__name__}: {e}") from e
    return None  # pragma: no cover — 위 루프가 항상 반환하거나 예외를 낸다


def crawl(sosok: int, max_pages: int = 150) -> list:
    """[(코드, 이름)] 을 **페이지 순서 그대로** 돌려준다 (= 시가총액 순).

    새 종목이 안 나올 때까지(또는 EmptyParseError 확정까지) 넘긴다 —
    페이지 수가 상장/폐지로 바뀌어도 안전하다. 2026-08-20 실측: 코스피
    51p(끝 확인용 빈 페이지 포함), 코스닥 38p — 마지막 페이지 직전까지는
    전부 50행, 마지막만 짧다(28행/21행).

    ⚠ 개수 하한을 두지 않는다 — 마지막 페이지는 원래 적다(naver.py 의
    parse_market_sum docstring 참조).

    ⚠ **EmptyParseError 확정(_fetch_page 참조)이 항상 "끝"은 아니다.**
    페이지 1에서 배운 '꽉 찬 페이지' 크기(`page_size`)와 같은 행 수인
    페이지가 **연속 2번 이상** 나온 직후 곧장 0행이 확정되면, 그건 실측된
    정상 종료 패턴이 아니다(정상 패턴은 항상 "짧은 페이지 → 0행") — 중간
    장애가 우연히 EmptyParseError 로 확정된 경우와 구분이 안 되므로 끝으로
    믿지 않고 `CrawlFailed` 를 낸다(리뷰 F1: 코스피가 37페이지에서 실패해도
    4,010건이 남아 MIN_SANE=4000 을 우연히 통과하는 사례가 실측 확인됐다).
    짧은 페이지 바로 다음의 0행 확정은 그대로 끝으로 받아들인다.

    ⚠ max_pages 안에서 정상 종료 신호를 한 번도 못 만나면 예외를 낸다 —
    조용히 잘린 리스트를 돌려주지 않는다. 코스피가 가까운 미래에
    150페이지(현재 51페이지의 3배 가까이)를 넘는 일은 없다고 보지만,
    만에 하나 닿으면 "리스트가 잘렸는데 아무도 모른다"보다 "실패로
    드러난다"가 낫다.
    """
    out, seen = [], set()
    page_size = None
    full_streak = 0     # 연속으로 '꽉 찬'(=page_size 와 같은 행 수) 페이지를 본 횟수
    for page in range(1, max_pages + 1):
        got = _fetch_page(sosok, page)
        if got is None:                 # EmptyParseError 확정
            if full_streak >= 2:
                raise CrawlFailed(
                    f"sosok={sosok} page={page}: 꽉 찬 페이지가 {full_streak}번 "
                    f"연속된 직후 0행 — 끝이 아니라 장애로 의심된다")
            return out                   # 짧은 페이지(또는 페이지 1) 다음 = 진짜 끝
        n = len(got)
        if page_size is None:           # 페이지 1에서 '꽉 찬 페이지' 크기를 배운다
            page_size = n
        full_streak = full_streak + 1 if n == page_size else 0
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
    둘 다 "숫자 작은 코드만 보이는" 자동완성을 만든다. (실제
    `json.dumps(..., sort_keys=True)` 왕복으로 이 불변식을 고정하는
    테스트는 tests/test_master.py 참조 — 리뷰 F3.)

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
        # 자연스러운 재시도). traceback.print_exc() 는 CrawlFailed 처럼
        # "알고 잡는" 예외에는 잉여 정보지만, 예상 못 한 TypeError 등
        # 미래의 리팩터 버그가 한 줄짜리 print 에 파묻혀 프레임을 잃지
        # 않게 한다 — 비용은 공짜다(리뷰 F1 부록 minor).
        print(f"[중단] 마스터 수집 실패: {type(e).__name__}: {e} — 직전 마스터 유지")
        traceback.print_exc()
        return 1
    if not is_sane(m):
        # is_sane() 은 .get("count", 0) 으로 안전하게 읽는데 여기서
        # m['count'] 로 직접 접근하면, count 키 자체가 없는 build() 결과가
        # is_sane() 은 통과(False)시키고 이 print 에서 KeyError 로 죽는
        # 비대칭이 생긴다 — 같은 방식(.get)으로 통일한다.
        print(f"[중단] 종목 {m.get('count', 0)}건 — 파싱이 무너졌다. 직전 마스터 유지")
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
        traceback.print_exc()
        return 1
    print(f"완료 {m['count']}종목")
    return 0


if __name__ == "__main__":
    sys.exit(main())
