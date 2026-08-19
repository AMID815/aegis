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

    2026-08-19 실측: 진짜 상한은 개수가 아니라 URL 길이다 — n=1000(코드
    6자리 기준 url_len≈7061)까지 정상 응답, n=1001(url_len≈7068)부터
    HTTPError 414. CHUNK=60(url_len≈481)은 그 상한의 1/16 수준이라
    이 값을 올릴 실익이 없다(실 보유 종목 수는 수십 단위) — 그래서 그대로 둔다.
    """
    불린주소 = []

    def 가짜(url, enc="utf-8"):
        불린주소.append(url)
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
    strict 디코드는 예외를 내지만 replace 는 조용히 성공해 버리므로."""
    raw = "삼성전자".encode("cp949")

    def 가짜_urlopen(req, timeout=20):
        return _가짜응답(raw)

    monkeypatch.setattr(naver.urllib.request, "urlopen", 가짜_urlopen)

    with pytest.raises(UnicodeDecodeError):
        naver._fetch("http://x", "utf-8")

    assert naver._fetch("http://x", naver.EUCKR) == "삼성전자"


def test_UA_헤더를_요청에_담아_보낸다(monkeypatch):
    captured = {}

    def 가짜_urlopen(req, timeout=20):
        captured["req"] = req
        captured["timeout"] = timeout
        return _가짜응답(b"ok")

    monkeypatch.setattr(naver.urllib.request, "urlopen", 가짜_urlopen)
    naver._fetch("http://x")
    assert captured["req"].get_header("User-agent") == naver.UA["User-Agent"]
    assert captured["timeout"] == 20


def test_HTTP_에러는_삼키지_않고_그대로_전파한다(monkeypatch):
    """_fetch 는 판단하지 않는다 — 404/500 은 호출자(quotes.py 등)가 잡아서
    "이번엔 커밋하지 않는다"로 처리한다(그 판단은 이 파일의 책임이 아니다)."""

    def 가짜_urlopen(req, timeout=20):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr(naver.urllib.request, "urlopen", 가짜_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        naver._fetch("http://x")
