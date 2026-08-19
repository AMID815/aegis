# -*- coding: utf-8 -*-
"""master.py: 종목 마스터 수집 (Task 9, 리뷰 반영판).

공급된 테스트는 그대로 두고, 아래를 추가했다 — 구현 전 비평(critique)에서
찾은 결함을 고정한다:

1. **부분 크롤을 숨기지 않는다.** 공급 코드는 `crawl()` 이 일시 장애든
   markup 붕괴든 페이지 하나에서 예외를 만나면 `break` 하고 **그때까지
   모은 부분 리스트를 정상값처럼** 돌려줬다. `MIN_SANE`(공급값 2000)은
   코스피 하나만 30페이지쯤에서 끊겨도(≈1,500) 코스닥(≈1,800)과 더하면
   가볍게 넘는다 — "삼성전자보다 뒤에 상장된 회사 전부가 빠진" 마스터가
   조용히 통과해 커밋된다. 그래서:
   - 일시 장애(`Exception`)는 **같은 페이지를 한 번 재시도**한다(naver.py
     의 "재시도 안 함" 근거 — 30분 주기가 곧 재시도 — 는 여기 적용 안
     된다, 이 스크립트는 **하루 1회**라 실패 하나가 24시간을 날린다).
     재시도도 실패하면 부분 리스트 대신 `CrawlFailed` 를 낸다.
   - `EmptyParseError`(행 0건)도 재시도 대상에 넣는다 — "0건"이 항상
     "끝에 닿았다"를 뜻하진 않는다. 서버가 일시적으로 빈 페이지를 준
     경우도 파싱 결과는 똑같이 0건이라 구분이 안 된다. 재시도에서
     데이터가 나오면 끝으로 오판하지 않는다. 크롤은 어차피 끝에서 정확히
     한 번 이 예외를 만나므로, 매 크롤마다 요청 1건이 늘 뿐이다.
   - `max_pages` 안에서 "정상 종료" 신호(EmptyParseError 확정 또는 '새
     게 없다')를 한 번도 못 만나면 — 즉 리스트 크기 자체를 못 믿게 되면
     — 역시 조용히 자르지 않고 `CrawlFailed` 를 낸다.
2. **코스피/코스닥 실패는 build() 가 삼키지 않는다.** ETF(`_etf()`)는
   원래도 "있으면 좋은 것"이라 실패를 삼키지만(공급
   `test_ETF_실패해도_나머지는_남는다`), 코스피·코스닥은 마스터의 본체다
   — 실패를 빈 리스트로 대체하면 "본체가 통째로 빠졌는데 남은 것만으로
   하한을 우연히 넘겨 커밋되는" 바로 그 사고가 재발한다. 그래서
   `crawl()` 이 낸 `CrawlFailed` 는 `build()` 를 그대로 뚫고 나간다.
3. **`gh.read_json`/`gh.write_json` 을 main() 이 무방비로 부르지 않는다.**
   quotes.py·close.py 가 이미 겪고 고친 것과 같은 결함 — 네트워크 문제·
   409·1MB 초과 등으로 이 호출이 실패하면 트레이스백으로 죽는 대신 진단을
   찍고 rc=1 로 물러나야 한다(다음 실행이 자연스러운 재시도).
4. **`MIN_SANE` 을 2000 → 4000 으로 올렸다.** 2026-08-20 실측(코스피
   2,478 + 코스닥 1,821 = 4,299, ETF 1,162건은 전부 이미 이 4,299 안에
   포함 — 아래 5번)을 근거로 잡았다. 2000 은 실측치의 절반 이하라 총
   붕괴만 잡고, naver.py 모듈 docstring 이 실측한 "정규식이 영숫자 코드를
   놓쳐 375건(8.7%)이 조용히 빠지는" 부류의 회귀는 못 잡는다. 4000(실측의
   ~93%)이면 그 부류의 회귀를 실제로 잡으면서도, 일일 상장/폐지로 인한
   자연스러운 등락(하루 수 건~수십 건 수준)에는 false trip 이 나지 않을
   여유가 충분하다.
5. **ETF 중복 실측**: 실제 네트워크로 확인한 결과(구현 커밋 메시지 참조)
   `fetch_etf()` 가 돌려주는 1,162건 **전부**가 이미 코스피+코스닥
   시가총액 크롤(4,299건) 안에 있었고, 이름도 전부 일치했다(불일치 0건).
   즉 오늘 기준 `_etf()` 는 새 코드를 하나도 안 보탠다 — 그래도 "시가총액
   페이지에 아직 안 올라온 신규 ETF" 를 건지는 안전망으로서 설계된 순서
   (코스피→코스닥→ETF, 중복은 앞이 이김)는 무해하고 유효하므로 그대로
   둔다.

`quotes.now_kst()` 를 그대로 쓴다(의존 방향 재검토 결과) — close.py 가
이미 같은 이유로 quotes 를 참조하는 선례가 있고, quotes.py 는 이 저장소
안에서만 도는 표준 라이브러리 전용 모듈이라(외부 패키지 없음) 결합
비용이 실질적으로 없다. 3줄짜리 타임스탬프 헬퍼를 master.py 에 따로
복제하면 "KST 지금이 뭐냐"는 정의가 두 곳으로 갈라져 오히려 DRY 를
해친다.
"""
import pytest

from scripts import gh, master, naver


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
# 추가 테스트 — 위 docstring 1~5 번 항목을 고정한다
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
    종료하면 안 된다."""
    시도 = {"count": 0}
    데이터 = {1: {"005930": "삼성전자"}, 2: {"000660": "SK하이닉스"}}

    def 가짜(sosok, page):
        if page == 2 and 시도["count"] == 0:
            시도["count"] += 1
            raise master.naver.EmptyParseError("일시적으로 비어보임")
        if page in 데이터:
            return 데이터[page]
        raise master.naver.EmptyParseError("진짜 끝")

    monkeypatch.setattr(master.naver, "fetch_market_sum", 가짜)
    out = master.crawl(sosok=0, max_pages=10)
    assert out == [("005930", "삼성전자"), ("000660", "SK하이닉스")]


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


def test_MIN_SANE은_실측_4299의_대부분을_요구한다():
    """2026-08-20 실측 총 4,299건(코스피 2,478 + 코스닥 1,821, ETF 는
    전부 중복) 대비, 375건(8.7%)짜리 회귀(예: parse_market_sum 이 영숫자
    코드를 다시 놓치는 사고)가 실제로 걸리는 하한인지 확인한다."""
    assert master.MIN_SANE >= 4000


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
