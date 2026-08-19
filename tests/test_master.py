# -*- coding: utf-8 -*-
"""master.py: 종목 마스터 수집 (Task 9, 리뷰 2라운드 반영판).

공급된 테스트는 그대로 두고, 아래를 추가했다 — 구현 전 비평(critique)에서
찾은 결함을 고정한다:

1. **부분 크롤을 숨기지 않는다.** 공급 코드는 `crawl()` 이 일시 장애든
   markup 붕괴든 페이지 하나에서 예외를 만나면 `break` 하고 **그때까지
   모은 부분 리스트를 정상값처럼** 돌려줬다. `MIN_SANE`(공급값 2000)은
   코스피 하나만 30페이지쯤에서 끊겨도(≈1,500) 코스닥(≈1,800)과 더하면
   가볍게 넘는다 — "삼성전자보다 뒤에 상장된 회사 전부가 빠진" 마스터가
   조용히 통과해 커밋된다.
2. **코스피/코스닥 실패는 build() 가 삼키지 않는다.** ETF(`_etf()`)는
   원래도 "있으면 좋은 것"이라 실패를 삼키지만(공급
   `test_ETF_실패해도_나머지는_남는다`), 코스피·코스닥은 마스터의 본체다.
3. **`gh.read_json`/`gh.write_json` 을 main() 이 무방비로 부르지 않는다.**
4. **`MIN_SANE` 을 2000 → 4000 으로 올렸다.**
5. **ETF 중복 실측**: `fetch_etf()` 가 돌려주는 1,162건 전부가 이미
   코스피+코스닥 시가총액 크롤(4,299건) 안에 있었고, 이름도 전부
   일치했다(불일치 0건).

`quotes.now_kst()` 를 그대로 쓴다(의존 방향 재검토 결과) — close.py 가
이미 같은 이유로 quotes 를 참조하는 선례가 있고, quotes.py 는 이 저장소
안에서만 도는 표준 라이브러리 전용 모듈이라(외부 패키지 없음) 결합
비용이 실질적으로 없다.

**리뷰 2라운드(F1~F3) 반영**:

F1. 1라운드의 "페이지 하나 재시도"만으로는 구멍이 남아 있었다.
   `_fetch_page` 가 EmptyParseError 두 번을 "끝"으로 확정하는 건, "진짜
   끝"과 "일시 장애가 두 번 우연히 겹친 것"을 구분 못 한다 — 실측: 코스피가
   37페이지에서 (장애로) 끊겨도 4,010건이 모여 MIN_SANE(4000)을 우연히
   통과했다. 게다가 재시도 1차가 하드 장애·2차가 EmptyParseError 인 경우와
   그 반대 순서가 서로 다른 결론을 냈다(순서 의존 버그, 아래
   `test_재시도_순서가_바뀌어도_결과가_같다_*` 두 테스트가 고정한다).
   고친 내용은 scripts/master.py 의 `_fetch_page`/`crawl` docstring 참조
   (요약: 두 시도 중 하나라도 하드 장애면 순서 무관 CrawlFailed, 그리고
   crawl() 이 page 1 에서 배운 '꽉 찬 페이지' 크기가 연속 2번 이상 나온
   직후 곧장 0행이 오면 끝으로 믿지 않는다 — 실측된 정상 종료 패턴은
   항상 "짧은 페이지 → 0행"이기 때문이다).

   이 변경으로 `test_일시적으로_빈_페이지도_재시도하면_회복된다` 의
   픽스처를 고쳤다 — 원래는 페이지 2를 "꽉 찬 페이지"로 둬서(1행짜리
   합성 픽스처지만 page_size 와 같은 크기), 페이지 1~2 가 연속으로
   '꽉 참'을 만족해 F1 의 새 규칙상 정당하게 CrawlFailed 가 나야 하는
   상황이 돼버렸다. "일시 장애에서 재시도로 회복된다"는 원래 취지를
   지키려면 마지막 실데이터 페이지가 짧아야 하므로, 페이지 2 를 짧은
   페이지(1행 < page_size=2행)로 바꿨다.
F2. `assert master.MIN_SANE >= 4000` 은 상한이 없는 회귀(`MIN_SANE =
   999999`, 매일 게이트가 트립됨)를 통과시킨다 — 정작 위험한 쪽(false
   trip)을 안 잡는다. `is_sane()` 의 실제 동작(실측 총계는 통과, 알려진
   영숫자 코드 누락 회귀는 차단)을 직접 확인하는 걸로 바꿨다.
F3. `build()` docstring 이 "items 는 dict 가 아니라 list" 를 여덟 줄로
   설명하면서도, `json.dumps(..., sort_keys=True)`(gh.write_json 이 실제
   로 쓰는 것과 같은 직렬화)를 왕복하는 테스트가 없었다. dict 로
   되돌아가는 회귀가 생기면 이 불변식이 깨지는데, 그걸 잡는 테스트가
   하나도 없으면 "가장 많이 설명된 불변식이 가장 안 지켜지는" 역설이
   생긴다 — 추가했다.

Minor: `_etf()` 의 `[경고]` 출력을 확인하는 테스트가 없었다 — ETF 장애는
count 를 낮추지 않으므로(실측 100% 중복) 그 print 가 유일한 신호다 —
추가했다.
"""
import json

import pytest

from scripts import master


# ---------------------------------------------------------------------------
# 공급된 테스트 (그대로)
# ---------------------------------------------------------------------------

def test_새_종목이_없을때까지_페이지를_넘긴다(monkeypatch):
    페이지 = {
        (0, 1): {"005930": "삼성전자"},
        (0, 2): {"000660": "SK하이닉스"},
        (0, 3): {"000660": "SK하이닉스"},     # 새 게 없다 → 멈춘다
    }
    monkeypatch.setattr(master.naver, "fetch_market_sum",
                        lambda sosok, page: 페이지.get((sosok, page), {}))
    out = master.crawl(sosok=0, max_pages=10)
    assert out == [("005930", "삼성전자"), ("000660", "SK하이닉스")]


def test_페이지_순서가_보존된다(monkeypatch):
    """순서가 곧 관련도다 — 시가총액 큰 회사가 앞에 와야 자동완성이 쓸모 있다."""
    페이지 = {(0, 1): {"005930": "삼성전자", "000660": "SK하이닉스"},
              (0, 2): {"247540": "에코프로비엠"}}
    monkeypatch.setattr(master.naver, "fetch_market_sum",
                        lambda sosok, page: 페이지.get((sosok, page), {}))
    out = master.crawl(sosok=0, max_pages=10)
    assert [c for c, _ in out] == ["005930", "000660", "247540"]


def test_페이지가_비면_멈춘다(monkeypatch):
    def 가짜(sosok, page):
        if page == 1:
            return {"005930": "삼성전자"}
        raise master.naver.EmptyParseError("끝")
    monkeypatch.setattr(master.naver, "fetch_market_sum", 가짜)
    assert master.crawl(sosok=0, max_pages=10) == [("005930", "삼성전자")]


def test_코스피_코스닥_ETF를_이_순서로_합친다(monkeypatch):
    monkeypatch.setattr(master, "crawl",
                        lambda sosok, max_pages=150:
                        [("005930", "삼성전자")] if sosok == 0 else [("196170", "알테오젠")])
    monkeypatch.setattr(master.naver, "fetch_etf",
                        lambda: {"069500": "KODEX 200"})
    out = master.build()
    assert out["count"] == 3
    assert out["items"] == [["005930", "삼성전자"],
                            ["196170", "알테오젠"],
                            ["069500", "KODEX 200"]]


def test_중복_코드는_처음_것만_남는다(monkeypatch):
    """ETF 가 코스피 목록에도 있으면 앞(시가총액 순)이 이긴다."""
    monkeypatch.setattr(master, "crawl",
                        lambda sosok, max_pages=150:
                        [("069500", "KODEX 200")] if sosok == 0 else [])
    monkeypatch.setattr(master.naver, "fetch_etf", lambda: {"069500": "다른이름"})
    out = master.build()
    assert out["items"] == [["069500", "KODEX 200"]]


def test_ETF_실패해도_나머지는_남는다(monkeypatch):
    monkeypatch.setattr(master, "crawl",
                        lambda sosok, max_pages=150:
                        [("005930", "삼성전자")] if sosok == 0 else [])
    monkeypatch.setattr(master.naver, "fetch_etf",
                        lambda: (_ for _ in ()).throw(RuntimeError("ETF 장애")))
    assert master.build()["count"] == 1


def test_결과가_너무_적으면_실패로_본다(monkeypatch):
    """마크업이 바뀌면 조용히 몇 건만 나온다 — 그걸 커밋하면 자동완성이 죽는다."""
    monkeypatch.setattr(master, "crawl", lambda sosok, max_pages=150: [("005930", "삼성전자")])
    monkeypatch.setattr(master.naver, "fetch_etf", lambda: {})
    assert master.is_sane(master.build()) is False


# ---------------------------------------------------------------------------
# 1라운드 추가 테스트
# ---------------------------------------------------------------------------

def test_일시_장애는_한번_재시도_후_성공하면_계속_진다(monkeypatch):
    """페이지 1에서 한 번 걸려도, 재시도로 풀리면 나머지 페이지를 그대로
    이어서 크롤한다 — 이미 모은 게 없다고 통째로 포기하지 않는다."""
    시도 = {"count": 0}

    def 가짜(sosok, page):
        if page == 1 and 시도["count"] == 0:
            시도["count"] += 1
            raise TimeoutError("일시 장애")
        if page == 1:
            return {"005930": "삼성전자"}
        raise master.naver.EmptyParseError("끝")

    monkeypatch.setattr(master.naver, "fetch_market_sum", 가짜)
    out = master.crawl(sosok=0, max_pages=10)
    assert out == [("005930", "삼성전자")]


def test_일시적으로_빈_페이지도_재시도하면_회복된다(monkeypatch):
    """EmptyParseError(행 0건)가 항상 '끝'을 뜻하진 않는다 — 서버가
    일시적으로 빈 페이지를 준 경우도 파싱 결과는 똑같이 0건으로 보인다.
    재시도에서 실제 데이터가 나오면 그걸 끝으로 오판해 크롤을 조기
    종료하면 안 된다.

    (F1 반영: 마지막 실데이터 페이지(2)를 페이지 1보다 짧게 둔다 — F1 의
    "꽉 찬 페이지가 연속되면 그다음 0행을 의심한다" 규칙과 맞물려, 짧은
    페이지 다음의 0행만 정당하게 끝으로 인정되기 때문이다.)"""
    시도 = {"count": 0}
    데이터 = {1: {"005930": "삼성전자", "000660": "SK하이닉스"},  # 꽉 찬 페이지(2행)
              2: {"247540": "에코프로비엠"}}                        # 짧은 페이지(1행)

    def 가짜(sosok, page):
        if page == 2 and 시도["count"] == 0:
            시도["count"] += 1
            raise master.naver.EmptyParseError("일시적으로 비어보임")
        if page in 데이터:
            return 데이터[page]
        raise master.naver.EmptyParseError("진짜 끝")

    monkeypatch.setattr(master.naver, "fetch_market_sum", 가짜)
    out = master.crawl(sosok=0, max_pages=10)
    assert out == [("005930", "삼성전자"), ("000660", "SK하이닉스"), ("247540", "에코프로비엠")]


def test_재시도해도_실패하면_부분리스트_대신_예외를_낸다(monkeypatch):
    """페이지 3에서 장애가 재시도 후에도 계속되면, 1~2페이지에서 이미
    모은 걸 조용히 잘라 정상값처럼 돌려주면 안 된다 — 그게 그대로
    MIN_SANE 을 우연히 넘겨 잘린 마스터가 커밋될 수 있다."""
    def 가짜(sosok, page):
        if page < 3:
            return {f"00000{page}": f"종목{page}"}
        raise TimeoutError("영구 장애")

    monkeypatch.setattr(master.naver, "fetch_market_sum", 가짜)
    with pytest.raises(master.CrawlFailed):
        master.crawl(sosok=0, max_pages=10)


def test_max_pages_안에서_끝을_못_찾으면_예외를_낸다(monkeypatch):
    """모든 페이지가 매번 새 종목을 낸다면(=끝 신호를 한 번도 못 만났다)
    잘린 리스트를 "이게 전부"로 조용히 돌려주면 안 된다."""
    monkeypatch.setattr(master.naver, "fetch_market_sum",
                        lambda sosok, page: {f"{page:06d}": f"종목{page}"})
    with pytest.raises(master.CrawlFailed):
        master.crawl(sosok=0, max_pages=5)


def test_코스피_크롤_실패는_숨기지_않고_build를_그대로_실패시킨다(monkeypatch):
    """ETF 는 없어도 되는 부가 정보라 실패를 삼키지만(공급
    test_ETF_실패해도_나머지는_남는다), 코스피는 마스터의 본체다. 실패를
    조용히 빈 리스트로 대체하면 코스닥만으로 MIN_SANE 을 우연히 넘겨
    '삼성전자가 없는' 마스터가 커밋될 수 있다 — build() 는 그 실패를
    그대로 전파해야 한다."""
    def 크롤(sosok, max_pages=150):
        if sosok == 0:
            raise master.CrawlFailed("코스피 실패")
        return [("196170", "알테오젠")]

    monkeypatch.setattr(master, "crawl", 크롤)
    monkeypatch.setattr(master.naver, "fetch_etf", lambda: {"069500": "KODEX 200"})
    with pytest.raises(master.CrawlFailed):
        master.build()


def test_build_실패시_main은_gh를_건드리지_않고_1을_반환한다(monkeypatch):
    """crawl() 이 CrawlFailed 를 내면(코스피/코스닥 크롤이 끝내 실패)
    main() 은 gh.read_json/write_json 을 아예 부르지 않고 깨끗하게
    물러나야 한다 — 직전 마스터를 유지한다."""
    monkeypatch.setattr(master, "build",
                        lambda: (_ for _ in ()).throw(master.CrawlFailed("실패")))
    monkeypatch.setattr(master.gh, "read_json",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("gh 호출됨")))
    monkeypatch.setattr(master.gh, "write_json",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("gh 호출됨")))
    assert master.main() == 1


def test_모자란_결과는_main에서도_gh를_건드리지_않는다(monkeypatch):
    monkeypatch.setattr(master, "build",
                        lambda: {"count": 5, "items": [], "generated_kst": "x"})
    monkeypatch.setattr(master.gh, "read_json",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("gh 호출됨")))
    monkeypatch.setattr(master.gh, "write_json",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("gh 호출됨")))
    assert master.main() == 1


def test_gh_읽기_실패해도_크래시하지_않는다(monkeypatch):
    """sha 조회(gh.read_json)가 네트워크·5xx 로 실패해도 트레이스백으로
    죽지 않고 rc=1 로 물러난다 — 다음 실행이 자연스러운 재시도다."""
    monkeypatch.setattr(master, "build", lambda: {
        "generated_kst": "x", "count": 5000, "items": [["005930", "삼성전자"]]})
    monkeypatch.setattr(master.gh, "read_json",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("네트워크 오류")))
    assert master.main() == 1


def test_gh_쓰기_실패해도_크래시하지_않는다(monkeypatch):
    """write_json 이 409·5xx 로 실패해도 트레이스백으로 죽지 않는다."""
    monkeypatch.setattr(master, "build", lambda: {
        "generated_kst": "x", "count": 5000, "items": [["005930", "삼성전자"]]})
    monkeypatch.setattr(master.gh, "read_json", lambda *a, **k: (None, "sha1"))
    monkeypatch.setattr(master.gh, "write_json",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("409")))
    assert master.main() == 1


def test_main_정상_경로는_읽고_쓴다(monkeypatch):
    monkeypatch.setattr(master, "build", lambda: {
        "generated_kst": "2026-08-20T00:00:00+09:00", "count": 4300,
        "items": [["005930", "삼성전자"]]})
    written = {}
    monkeypatch.setattr(master.gh, "read_json", lambda *a, **k: (None, "sha1"))

    def 쓰기(path, body, sha, message):
        written["path"] = path
        written["sha"] = sha
        written["message"] = message

    monkeypatch.setattr(master.gh, "write_json", 쓰기)
    assert master.main() == 0
    assert written["path"] == master.MASTER
    assert written["sha"] == "sha1"
    assert "4300" in written["message"]


# ---------------------------------------------------------------------------
# 2라운드 추가 테스트 (F1~F3 + minor)
# ---------------------------------------------------------------------------

def test_재시도_순서가_바뀌어도_결과가_같다_타임아웃_다음_빈페이지(monkeypatch):
    """1차 시도가 하드 장애(타임아웃), 2차가 EmptyParseError 인 경우도
    끝으로 확정하지 않는다 — 순서에 따라 결론이 달라지면 안 된다(F1)."""
    시도2 = {"count": 0}

    def 가짜(sosok, page):
        if page == 1:
            return {"005930": "삼성전자"}
        if page == 2:
            if 시도2["count"] == 0:
                시도2["count"] += 1
                raise TimeoutError("일시 장애")
            raise master.naver.EmptyParseError("끝(이라고 주장)")
        raise master.naver.EmptyParseError("끝")

    monkeypatch.setattr(master.naver, "fetch_market_sum", 가짜)
    with pytest.raises(master.CrawlFailed):
        master.crawl(sosok=0, max_pages=10)


def test_재시도_순서가_바뀌어도_결과가_같다_빈페이지_다음_타임아웃(monkeypatch):
    """반대 순서(1차 EmptyParseError, 2차 타임아웃)도 마찬가지로 끝으로
    확정하지 않는다 — 위 테스트와 대칭이다(F1)."""
    시도2 = {"count": 0}

    def 가짜(sosok, page):
        if page == 1:
            return {"005930": "삼성전자"}
        if page == 2:
            if 시도2["count"] == 0:
                시도2["count"] += 1
                raise master.naver.EmptyParseError("일시적으로 비어보임")
            raise TimeoutError("일시 장애")
        raise master.naver.EmptyParseError("끝")

    monkeypatch.setattr(master.naver, "fetch_market_sum", 가짜)
    with pytest.raises(master.CrawlFailed):
        master.crawl(sosok=0, max_pages=10)


def test_짧은_페이지_다음의_0행_확정은_끝으로_받아들인다(monkeypatch):
    """짧은 페이지(=page_size 보다 적은 행) 다음의 0행 확정은 실측된
    정상 종료 패턴이다 — 코스피 마지막 실제 페이지(28행 < 50행)처럼."""
    페이지 = {1: {"a": "1", "b": "2"},   # 꽉 찬 페이지(2행, page_size 로 학습)
              2: {"c": "3"}}              # 짧은 페이지(1행)

    def 가짜(sosok, page):
        if page in 페이지:
            return 페이지[page]
        raise master.naver.EmptyParseError("끝")

    monkeypatch.setattr(master.naver, "fetch_market_sum", 가짜)
    out = master.crawl(sosok=0, max_pages=10)
    assert [c for c, _ in out] == ["a", "b", "c"]


def test_꽉_찬_페이지가_연속된_직후_0행이면_장애로_의심해_예외를_낸다(monkeypatch):
    """리뷰 F1 — 코스피가 37페이지에서 실패해도 그때까지 모은 4,010건이
    MIN_SANE(4000)을 우연히 통과해 잘린 마스터가 커밋되는 사고가 실측
    확인됐다. 짧은 페이지 없이 꽉 찬 페이지가 2번 이상 연속된 직후 곧장
    0행이 오면(=끝의 정상 패턴이 아니다) 끝으로 믿지 않는다."""
    def 가짜(sosok, page):
        if page <= 3:
            return {f"{page:06d}a": "종목", f"{page:06d}b": "종목"}  # 매 페이지 2행(꽉 참)
        raise master.naver.EmptyParseError("끝(이라고 주장)")

    monkeypatch.setattr(master.naver, "fetch_market_sum", 가짜)
    with pytest.raises(master.CrawlFailed):
        master.crawl(sosok=0, max_pages=10)


def test_is_sane은_실측_총계는_통과시키고_영숫자_회귀는_차단한다():
    """F2 — `assert master.MIN_SANE >= 4000` 은 상한이 없어 `MIN_SANE =
    999999` 같은(매일 게이트가 트립되는) 회귀도 통과시킨다. is_sane() 의
    실제 동작을 확인한다: 2026-08-20 실측 총계(4,299)는 통과하고,
    naver.py 가 실측한 영숫자 코드 375건(8.7%) 누락 회귀(4,299-375=3,924)
    는 차단해야 한다."""
    assert master.is_sane({"count": 4299}) is True
    assert master.is_sane({"count": 3924}) is False


def test_직렬화해도_시가총액_순서가_유지된다(monkeypatch):
    """F3 — build() 의 존재 이유(items 는 dict 가 아니라 list)를 실제
    gh.write_json 이 쓰는 직렬화(json.dumps(..., sort_keys=True))를 거쳐
    검증한다. dict 로 되돌아가는 회귀가 있으면 sort_keys=True 가 코드순
    재정렬해 삼성전자(005930)가 맨 앞에 남지 못한다."""
    monkeypatch.setattr(master, "crawl",
                        lambda sosok, max_pages=150:
                        [("005930", "삼성전자"), ("000660", "SK하이닉스"),
                         ("005935", "삼성전자우")] if sosok == 0 else [])
    monkeypatch.setattr(master.naver, "fetch_etf", lambda: {})
    m = master.build()
    round_tripped = json.loads(json.dumps(m, ensure_ascii=False, sort_keys=True))
    assert round_tripped["items"][0] == ["005930", "삼성전자"]
    assert [c for c, _ in round_tripped["items"]] == ["005930", "000660", "005935"]


def test_ETF_실패는_경고_로그를_남긴다(monkeypatch, capsys):
    """ETF 실패는 count 를 낮추지 않는다(실측: ETF 는 이미 100% 코스피/
    코스닥 크롤에 포함) — 그 [경고] 출력이 유일한 신호이므로 실제로
    찍히는지 확인한다."""
    monkeypatch.setattr(master, "crawl",
                        lambda sosok, max_pages=150:
                        [("005930", "삼성전자")] if sosok == 0 else [])
    monkeypatch.setattr(master.naver, "fetch_etf",
                        lambda: (_ for _ in ()).throw(RuntimeError("ETF 장애")))
    master.build()
    out = capsys.readouterr().out
    assert "[경고]" in out and "ETF" in out
