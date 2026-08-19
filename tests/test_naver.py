# -*- coding: utf-8 -*-
import pytest
from scripts import naver

# 2026-08-19 러너 실측 응답을 줄인 것
POLLING = """
{"pollingInterval":7000,"datas":[
 {"itemCode":"005930","stockName":"삼성전자","closePrice":"247,500",
  "marketStatus":"CLOSE","tradeStopType":{"code":"1","name":"TRADING"},
  "tradableStatus":"tradable",
  "overMarketPriceInfo":{"overPrice":"256,000"},
  "integratedPriceInfo":{"openPrice":"257,500"}},
 {"itemCode":"000660","stockName":"SK하이닉스","closePrice":"1,234,000",
  "marketStatus":"CLOSE","tradeStopType":{"code":"1","name":"TRADING"},
  "tradableStatus":"tradable"}]}
"""

FCHART = """<?xml version="1.0" encoding="EUC-KR" ?>
<protocol><chartdata symbol="005930" name="samsung" count="3" timeframe="day">
<item data="20260814|275000|275500|266000|274500|21669476" />
<item data="20260818|283000|288000|265000|268500|24464621" />
<item data="20260819|251500|254500|246500|247500|22683374" />
</chartdata></protocol>"""

MARKET_SUM = """
<a href="/item/main.naver?code=005930" class="tltle">삼성전자</a>
<a href="/item/main.naver?code=005935" class="tltle">삼성전자우</a>
<a href="/item/main.naver?code=000660" class="tltle">SK하이닉스</a>
"""

ETF = """{"result":{"etfItemList":[
 {"itemcode":"069500","itemname":"KODEX 200"},
 {"itemcode":"122630","itemname":"KODEX 레버리지"}]}}"""


def test_시세는_정규장_종가를_쓴다():
    """시간외(256,000)나 통합(257,500)이 아니라 closePrice(247,500)."""
    q = naver.parse_polling(POLLING)
    assert q["005930"]["price"] == 247500
    assert q["005930"]["name"] == "삼성전자"
    assert q["005930"]["status"] == "tradable"
    assert q["000660"]["price"] == 1234000


def test_거래정지는_상태로_드러난다():
    body = POLLING.replace('"tradableStatus":"tradable"',
                           '"tradableStatus":"halted"', 1)
    q = naver.parse_polling(body)
    assert q["005930"]["status"] == "halted"


def test_일봉을_날짜사전으로_바꾼다():
    bars = naver.parse_fchart(FCHART)
    assert bars["20260819"]["close"] == 247500
    assert bars["20260819"]["open"] == 251500
    assert bars["20260818"]["high"] == 288000
    assert list(bars) == ["20260814", "20260818", "20260819"]


def test_일봉에서_거래일_달력을_뽑는다():
    assert naver.trading_days(FCHART) == ["2026-08-14", "2026-08-18", "2026-08-19"]


def test_지수_일봉도_소수점을_읽는다():
    xml = '<item data="20260819|6528.77|6614.39|6400.81|6471.17|305840" />'
    bars = naver.parse_fchart(xml)
    assert bars["20260819"]["close"] == pytest.approx(6471.17)


def test_시가총액_페이지에서_우선주까지_뽑는다():
    items = naver.parse_market_sum(MARKET_SUM)
    assert items == {"005930": "삼성전자", "005935": "삼성전자우", "000660": "SK하이닉스"}


def test_ETF_목록을_뽑는다():
    assert naver.parse_etf(ETF) == {"069500": "KODEX 200", "122630": "KODEX 레버리지"}


def test_빈_파싱결과는_실패로_본다():
    """마크업이 바뀌면 예외 없이 0행이 나온다 — 그걸 성공으로 두면 안 된다."""
    with pytest.raises(naver.EmptyParseError):
        naver.parse_market_sum("<html>개편되었습니다</html>")
    with pytest.raises(naver.EmptyParseError):
        naver.parse_fchart("<protocol></protocol>")


# ── 코드리뷰로 추가된 테스트 ──────────────────────────────────────
#
# 실측(2026-08-19, KOSPI+KOSDAQ 493종목 폴링 배치 조회)으로 확인한 사실:
#   - 존재하지 않는 코드는 datas 배열에서 통째로 빠진다 (행 자체가 없다).
#   - 거래정지(halt) 종목도 closePrice 는 정상적으로 들어 있었다(000880, 183300).
# 그래도 배치(최대 60종목)에 섞인 한 종목의 가격 필드가 비어 있거나
# (장전 등 근거는 계획서 지시사항) 통째로 없으면, 원본 코드처럼
# row["closePrice"] 를 바로 서브스크립트하면 ValueError/KeyError 가 잡히지
# 않고 parse_polling 전체가 죽는다 — 그 배치의 나머지 59종목까지 같이
# 사라진다. 한 종목만 건너뛰고 나머지는 살리도록 고쳤다.

def test_가격필드가_없는_행은_건너뛰고_나머지는_살린다():
    body = """
    {"datas":[
     {"itemCode":"005930","stockName":"삼성전자",
      "tradableStatus":"tradable"},
     {"itemCode":"000660","stockName":"SK하이닉스","closePrice":"1,234,000",
      "tradableStatus":"tradable"}]}
    """
    q = naver.parse_polling(body)
    assert set(q) == {"000660"}
    assert q["000660"]["price"] == 1234000


def test_가격이_빈문자열이면_그_종목만_건너뛴다():
    """장전 등으로 가격 필드가 비어 있는 경우를 가정한다."""
    body = """
    {"datas":[
     {"itemCode":"005930","stockName":"삼성전자","closePrice":"",
      "tradableStatus":"tradable"},
     {"itemCode":"000660","stockName":"SK하이닉스","closePrice":"1,234,000",
      "tradableStatus":"tradable"}]}
    """
    q = naver.parse_polling(body)
    assert set(q) == {"000660"}


def test_가격이_null이면_그_종목만_건너뛴다():
    body = """
    {"datas":[
     {"itemCode":"005930","stockName":"삼성전자","closePrice":null,
      "tradableStatus":"tradable"},
     {"itemCode":"000660","stockName":"SK하이닉스","closePrice":"1,234,000",
      "tradableStatus":"tradable"}]}
    """
    q = naver.parse_polling(body)
    assert set(q) == {"000660"}


def test_전종목_가격이_깨지면_빈_파싱으로_본다():
    body = '{"datas":[{"itemCode":"005930","stockName":"삼성전자","closePrice":""}]}'
    with pytest.raises(naver.EmptyParseError):
        naver.parse_polling(body)


def test_ETF_이름이_없는_항목은_건너뛴다():
    """parse_polling 과 같은 이유 — 한 항목이 깨졌다고 1162개 전체를 죽이지 않는다."""
    body = """{"result":{"etfItemList":[
     {"itemcode":"069500"},
     {"itemcode":"122630","itemname":"KODEX 레버리지"}]}}"""
    assert naver.parse_etf(body) == {"122630": "KODEX 레버리지"}
