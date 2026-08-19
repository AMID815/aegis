# -*- coding: utf-8 -*-
"""naver.py 네트워크 계층(Task 4). 여기서는 절대 실제 네트워크를 타지 않는다 —
`_fetch`(또는 그보다 안쪽의 `urllib.request.urlopen`)를 항상 monkeypatch 한다.
러너(GitHub Actions)에서 결정적으로 돌아야 하기 때문이다.

실제 네트워크 측정치(배치 상한·인코딩·UA 필요 여부)는 이 파일이 아니라 구현
커밋 메시지/PR 설명에 남긴다 — 테스트는 "결정된 동작"만 고정한다.
"""
import urllib.error

import pytest

from scripts import naver


def test_코드를_묶어서_부른다(monkeypatch):
    """polling 은 콤마 배치가 된다. 60개씩 나눈다.

    2026-08-19 실측(재측정으로 재확인): 진짜 상한은 개수가 아니라 URL 길이다
    — n=1000(코드 6자리 기준 url_len≈7,061)까지 정상 응답, n=1001(≈7,068자)
    부터 400 Bad Request, n=1165(≈8,216자)부터 414 Request-URI Too Large —
    두 단계로 막힌다. CHUNK=60(url_len≈481)은 그 상한의 1/16 수준이라 이 값을
    올릴 실익이 없다(실 보유 종목 수는 수십 단위) — 그래서 그대로 둔다.
    """
    불린주소 = []
    불린인코딩 = []

    def 가짜(url, enc="utf-8"):
        불린주소.append(url)
        불린인코딩.append(enc)
        codes = url.rsplit("/", 1)[-1].split(",")
        rows = ",".join(
            '{"itemCode":"%s","stockName":"n","closePrice":"1","tradableStatus":"tradable"}' % c
            for c in codes)
        return '{"datas":[%s]}' % rows

    monkeypatch.setattr(naver, "_fetch", 가짜)
    codes = [f"{i:06d}" for i in range(140)]
    q = naver.fetch_quotes(codes)
    assert len(q) == 140
    assert len(불린주소) == 3           # 60 + 60 + 20
    assert 불린인코딩 == ["utf-8", "utf-8", "utf-8"]   # polling 은 UTF-8(EUCKR 아님)


def test_종목이_없으면_부르지_않는다(monkeypatch):
    monkeypatch.setattr(naver, "_fetch",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("호출됨")))
    assert naver.fetch_quotes([]) == {}


def test_요청한_종목이_빠지면_알려준다(monkeypatch):
    """상폐·거래정지는 에러가 아니라 '그 종목만 빠진 200' 으로 온다."""
    monkeypatch.setattr(naver, "_fetch", lambda url, enc="utf-8":
                        '{"datas":[{"itemCode":"005930","stockName":"삼성전자",'
                        '"closePrice":"247,500","tradableStatus":"tradable"}]}')
    q = naver.fetch_quotes(["005930", "999999"])
    assert set(q) == {"005930"}
    assert naver.missing_codes(["005930", "999999"], q) == ["999999"]


def test_가격이_깨진_종목도_missing_codes로_잡힌다(monkeypatch):
    """closePrice 가 "-"(정지 종목의 자리표시자)라 parse_polling 이 그 행만
    건너뛰어도, missing_codes 는 상폐·거래정지로 응답에서 통째로 빠진 경우와
    똑같이 그 코드를 "빠졌다"로 잡아야 한다 — 호출자 입장에서는 둘을 구분할
    필요가 없다(둘 다 "이번엔 시세를 못 얻었다")."""
    monkeypatch.setattr(naver, "_fetch", lambda url, enc="utf-8":
                        '{"datas":[{"itemCode":"005930","stockName":"삼성전자",'
                        '"closePrice":"247,500","tradableStatus":"tradable"},'
                        '{"itemCode":"000660","stockName":"SK하이닉스",'
                        '"closePrice":"-","tradableStatus":"halt"}]}')
    q = naver.fetch_quotes(["005930", "000660"])
    assert set(q) == {"005930"}
    assert naver.missing_codes(["005930", "000660"], q) == ["000660"]


def test_fetch_bars는_EUCKR로_fchart를_불러_파싱한다(monkeypatch):
    captured = {}

    def 가짜(url, enc="utf-8"):
        captured["url"] = url
        captured["enc"] = enc
        return ('<?xml version="1.0" encoding="EUC-KR" ?>'
                 '<protocol><chartdata symbol="005930"><item data="20260819|1|2|0|3|100" />'
                 '</chartdata></protocol>')

    monkeypatch.setattr(naver, "_fetch", 가짜)
    bars = naver.fetch_bars("005930", n=10)
    assert "symbol=005930" in captured["url"]
    assert "count=10" in captured["url"]
    assert captured["enc"] == naver.EUCKR
    assert bars["20260819"]["close"] == 3


def test_fetch_trading_days는_삼성전자_일봉을_거래일로_쓴다(monkeypatch):
    """'삼성전자 일봉 = KRX 정규장 거래일' 규칙 그대로: symbol=005930 고정."""
    captured = {}

    def 가짜(url, enc="utf-8"):
        captured["url"] = url
        return ('<protocol><chartdata><item data="20260818|1|2|0|3|100" />'
                 '<item data="20260819|1|2|0|3|100" /></chartdata></protocol>')

    monkeypatch.setattr(naver, "_fetch", 가짜)
    days = naver.fetch_trading_days(5)
    assert "symbol=005930" in captured["url"]
    assert "count=5" in captured["url"]
    assert days == ["2026-08-18", "2026-08-19"]


def test_fetch_market_sum은_sosok_page를_그대로_전달하고_EUCKR로_부른다(monkeypatch):
    captured = {}

    def 가짜(url, enc="utf-8"):
        captured["url"] = url
        captured["enc"] = enc
        return '<a href="/item/main.naver?code=005930" class="tltle">삼성전자</a>'

    monkeypatch.setattr(naver, "_fetch", 가짜)
    items = naver.fetch_market_sum(sosok=1, page=3)
    assert "sosok=1" in captured["url"]
    assert "page=3" in captured["url"]
    assert captured["enc"] == naver.EUCKR
    assert items == {"005930": "삼성전자"}


def test_fetch_etf는_ETF_URL을_EUCKR로_부른다(monkeypatch):
    captured = {}

    def 가짜(url, enc="utf-8"):
        captured["url"] = url
        captured["enc"] = enc
        filler = ",".join(
            '{"itemcode":"9%05d","itemname":"필러%d"}' % (i, i)
            for i in range(naver.MIN_ETF_ROWS))
        return '{"result":{"etfItemList":[%s]}}' % filler

    monkeypatch.setattr(naver, "_fetch", 가짜)
    items = naver.fetch_etf()
    assert captured["url"] == naver.ETF_URL
    assert captured["enc"] == naver.EUCKR
    assert len(items) == naver.MIN_ETF_ROWS


class _가짜응답:
    """urllib.request.urlopen 이 돌려주는 컨텍스트 매니저를 흉내낸다."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_strict_디코드만_쓴다_replace는_금지(monkeypatch):
    """이 모듈 전체의 핵심 방어선. EUC-KR/CP949 바이트를 utf-8 로 strict
    디코드하면 예외가 나야 하고(방어선이 작동), cp949 로 디코드하면 정상
    복원돼야 한다. `errors="replace"` 를 쓰면 이 테스트가 잡아낸다 —
    strict 디코드는 예외를 내지만 replace 는 조용히 성공해 버리므로.

    "갂성전자" 를 쓴다("삼성전자" 가 아니라) — 설계 §10-3 이 요구하는 건
    "cp949 를 쓴다"이지 "euc_kr 이라도 상관없다"가 아니다. 그런데 상장 종목
    이름은 전부 KS X 1001(euc_kr 이 읽는 부분집합) 안에 있어서, "삼성전자"
    로는 EUCKR 을 "euc_kr" 로 바꿔도 이 테스트가 못 잡는다. "갂"은 KS X 1001
    밖의 음절이라 cp949 는 읽고 euc_kr 은 못 읽는다 — 이 한 글자가
    cp949/euc_kr 을 실제로 갈라놓는다(2026-08-19 실측 재확인)."""
    raw = "갂성전자".encode("cp949")

    def 가짜_urlopen(req, timeout=None):
        return _가짜응답(raw)

    monkeypatch.setattr(naver.urllib.request, "urlopen", 가짜_urlopen)

    with pytest.raises(UnicodeDecodeError):
        naver._fetch("http://x", "utf-8")

    assert naver._fetch("http://x", naver.EUCKR) == "갂성전자"


def test_UA_헤더와_20초_타임아웃을_요청에_담아_보낸다(monkeypatch):
    """가짜 urlopen 의 `timeout` 기본값을 20 으로 두면(_fetch 가 실제로 넘기는
    값과 같은 값) _fetch 가 timeout 을 아예 안 넘겨도 이 스텁이 대신 20 을
    채워 넣어 테스트가 통과해 버린다 — 검증이 헛것이 된다. 기본값을 None
    으로 둬서, _fetch 가 timeout 인자를 빠뜨리면 실제로 그렇게 드러나게 한다.
    (하드코딩된 20초 없이는 재시도-없음 결정의 절반이 근거를 잃는다 — 무한정
    걸리는 요청이 Actions 잡을 통째로 물고 늘어질 수 있다.)"""
    captured = {}

    def 가짜_urlopen(req, timeout=None):
        captured["req"] = req
        captured["timeout"] = timeout
        return _가짜응답(b"ok")

    monkeypatch.setattr(naver.urllib.request, "urlopen", 가짜_urlopen)
    naver._fetch("http://x", "utf-8")
    assert captured["req"].get_header("User-agent") == naver.UA["User-Agent"]
    assert captured["timeout"] == 20


def test_HTTP_에러는_삼키지_않고_그대로_전파한다(monkeypatch):
    """_fetch 는 판단하지 않는다 — 404/500 은 호출자(quotes.py 등)가 잡아서
    "이번엔 커밋하지 않는다"로 처리한다(그 판단은 이 파일의 책임이 아니다)."""

    def 가짜_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr(naver.urllib.request, "urlopen", 가짜_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        naver._fetch("http://x", "utf-8")
