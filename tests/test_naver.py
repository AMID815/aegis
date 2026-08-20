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

# 실제 페이지 구조(2026-08-20 실측)를 그대로 흉내낸다 — 종목 링크 바로
# 다음이 순위/전일비 등이 아니라 곧장 현재가 <td class="number"> 다.
MARKET_SUM = """
<a href="/item/main.naver?code=005930" class="tltle">삼성전자</a></td>
<td class="number">247,500</td>
<a href="/item/main.naver?code=005935" class="tltle">삼성전자우</a></td>
<td class="number">173,700</td>
<a href="/item/main.naver?code=000660" class="tltle">SK하이닉스</a></td>
<td class="number">1,500,000</td>
"""

def _etf_body(pairs):
    """[(code,name)...] → parse_etf 입력 JSON. name 이 None 이면 그 필드를 뺀다."""
    rows = []
    for code, name in pairs:
        if name is None:
            rows.append('{"itemcode":"%s"}' % code)
        else:
            rows.append('{"itemcode":"%s","itemname":"%s"}' % (code, name))
    return '{"result":{"etfItemList":[%s]}}' % ",".join(rows)


def _padded_etf(extra_pairs=()):
    """MIN_ETF_ROWS 문턱을 넘기기 위한 채움 항목 + 검증하려는 실제 항목.

    ETF 목록은 페이징 없이 한 번에 전체를 돌려주므로(parse_market_sum 과
    달리 '원래 적은 마지막 페이지'가 없다) parse_etf 는 개수 하한을 둔다.
    테스트 픽스처가 그 하한보다 작으면 EmptyParseError 로 죽으므로, 실제
    검증하려는 항목 앞에 채움 항목을 깔아 문턱을 넘긴다.
    """
    filler = [(f"9{i:05d}", f"필러ETF{i}") for i in range(naver.MIN_ETF_ROWS)]
    return _etf_body(filler + list(extra_pairs))


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
    assert items == {
        "005930": {"name": "삼성전자", "price": 247500},
        "005935": {"name": "삼성전자우", "price": 173700},
        "000660": {"name": "SK하이닉스", "price": 1500000},
    }


def test_ETF_목록을_뽑는다():
    body = _padded_etf([("069500", "KODEX 200"), ("122630", "KODEX 레버리지")])
    items = naver.parse_etf(body)
    assert items["069500"] == "KODEX 200"
    assert items["122630"] == "KODEX 레버리지"
    assert len(items) == naver.MIN_ETF_ROWS + 2


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
    body = _padded_etf([("069500", None), ("122630", "KODEX 레버리지")])
    items = naver.parse_etf(body)
    assert "069500" not in items
    assert items["122630"] == "KODEX 레버리지"


# ── 2차 코드리뷰(C1·C2·I3·I4·M5~M9)로 추가된 테스트 ──────────────────
#
# C1: KRX 코드는 숫자만이 아니다. 2026-08-19 실측(시가총액 페이지 전체를
# [0-9A-Za-z]{6} 로 훑음): 0126Z0(삼성에피스홀딩스, 코스피 상위 60위권,
# 363,500원)처럼 영숫자 코드가 실제로 상장되어 있다. 예전 \d{6} 정규식은
# 이런 행을 그냥 빼먹었다 — 개수가 50건에서 49건으로 줄 뿐 EmptyParseError
# 는 뜨지 않아서 아무도 못 알아챘다. models.py 의 CODE_RE 도 같은 이유로
# 함께 고쳤다(intake 가 이 코드를 문 앞에서 거부하지 않도록).

def test_시가총액_페이지에서_영숫자_코드도_뽑는다():
    html = MARKET_SUM + (
        '\n<a href="/item/main.naver?code=0126Z0" class="tltle">삼성에피스홀딩스</a>\n')
    items = naver.parse_market_sum(html)
    assert items["0126Z0"]["name"] == "삼성에피스홀딩스"
    # 마지막 행이라 뒤에 가격 셀이 없다 — None 이어야 하고, 위 SK하이닉스
    # 행의 1,500,000 을 잘못 물려받으면 안 된다(옆 행 오염 방지, 아래
    # test_가격_셀이_없는_행은_옆_행_가격을_빌려오지_않는다 와 같은 계열).
    assert items["0126Z0"]["price"] is None


def test_ETF_목록도_영숫자_코드를_받는다():
    """2026-08-19 실측: ETF 1,162개 중 296개가 영숫자 itemcode 였다
    (예: 0167A0 SOL AI반도체TOP2플러스). parse_etf 는 애초에 코드 모양을
    제한하지 않으므로 숫자 6자리로 좁힐 필요가 없다는 걸 문서로 남긴다."""
    body = _padded_etf([("0167A0", "SOL AI반도체TOP2플러스")])
    items = naver.parse_etf(body)
    assert items["0167A0"] == "SOL AI반도체TOP2플러스"


def test_ETF_목록이_너무_적으면_실패로_본다():
    """페이징 없는 단일 호출이라(parse_market_sum 과 달리 '원래 적은 마지막
    페이지'가 없다) 개수가 뚝 떨어지면 그 자체가 이상 신호다."""
    body = _etf_body([("069500", "KODEX 200"), ("122630", "KODEX 레버리지")])
    with pytest.raises(naver.EmptyParseError):
        naver.parse_etf(body)


def test_ETF_행이_dict가_아니면_건너뛴다():
    filler = ",".join(
        '{"itemcode":"9%05d","itemname":"필러%d"}' % (i, i)
        for i in range(naver.MIN_ETF_ROWS))
    body = ('{"result":{"etfItemList":[%s,"069500",'
            '{"itemcode":"122630","itemname":"KODEX 레버리지"}]}}' % filler)
    items = naver.parse_etf(body)
    assert items["122630"] == "KODEX 레버리지"
    assert "069500" not in items


# C2: "0행이면 실패" 규칙은 인코딩 함정을 못 잡는다는 걸 실제 EUC-KR 바이트로
# 증명한다. "삼성전자".encode("euc-kr") 를 그대로 박아 넣었다(네트워크 없음).
_EUCKR_ROW = (b'<a href="/item/main.naver?code=005930" class="tltle">'
              b'\xbb\xef\xbc\xba\xc0\xfc\xc0\xda</a>')


def test_잘못된_디코딩은_행수로_안_잡힌다():
    """utf-8/replace 로 잘못 디코드해도 마크업(ASCII)은 안 깨지므로 정규식은
    여전히 매치한다 — 행 수만 보는 규칙으로는 이 사고를 못 잡는다는 걸
    직접 보여준다. 실제로 잡는 건 이름의 치환문자를 보는 _corrupted 다."""
    wrong = _EUCKR_ROW.decode("utf-8", "replace")
    assert naver._SUM_RE.findall(wrong)            # 행은 여전히 매치된다(0건 아님)
    with pytest.raises(naver.EmptyParseError):      # 그래도 치환문자 검사로 잡힌다
        naver.parse_market_sum(wrong)


def test_strict_디코딩이_진짜_방어선이다():
    """네트워크 계층(Task 4)이 errors="replace" 대신 strict 를 쓰면 이 바이트는
    애초에 여기까지 오지도 못한다 — 그게 진짜 방어선이라는 걸 문서로 남긴다."""
    with pytest.raises(UnicodeDecodeError):
        _EUCKR_ROW.decode("utf-8", "strict")


def test_ETF_이름이_깨지면_실패로_본다():
    """parse_market_sum 과 같은 방어선(_corrupted)이 parse_etf 에도 걸려 있다.
    개수 하한(MIN_ETF_ROWS)만으로는 이름이 깨진 걸 못 잡는다 — 채움 항목까지
    합쳐 문턱을 넉넉히 넘긴 상태에서, 이름 하나에만 치환문자를 심어도
    실패해야 한다는 걸 확인한다."""
    body = _padded_etf([("069500", "KODEX 200�")])
    with pytest.raises(naver.EmptyParseError):
        naver.parse_etf(body)


# I3: float("1e400") 은 예외 없이 inf 가 된다. json.dumps 가 그걸 Infinity 로
# 쓰면 표준 JSON 이 아니라서 브라우저 JSON.parse 가 거부해 페이지 전체가 빈다
# (models.py 의 bb5410d 와 같은 부류의 사고).

def test_비유한값은_그_봉만_버린다():
    ok = '<item data="20260818|100|100|100|100|10" />'
    bad_inf = '<item data="20260819|1e400|100|100|100|10" />'
    bars = naver.parse_fchart(ok + bad_inf)
    assert list(bars) == ["20260818"]


def test_nan도_버린다():
    xml = '<item data="20260819|nan|100|100|100|10" />'
    with pytest.raises(naver.EmptyParseError):     # 이 행 하나뿐이면 결국 0건
        naver.parse_fchart(xml)


# M5: 이전 회차에서 테스트 없이 넘어갔던 두 가지 변경을 되돌려도 실패하지
# 않는다는 걸 리뷰에서 지적받았다 — 각각을 직접 검증한다.

def test_거래량은_int로_나온다():
    bars = naver.parse_fchart(FCHART)
    assert type(bars["20260819"]["volume"]) is int


def test_거래량은_float를_거치지_않아_정밀도_손실이_없다():
    """type(volume) is int 만으로는 int(float(x)) 로 되돌려도 통과한다 —
    실제로 구분되는 지점은 2**53 을 넘는 값에서다. 현실적인 거래량(수천만 주)
    과는 무관하지만, 굳이 float 를 거칠 이유가 없다는 선택을 코드로 증명한다."""
    big = 2**53 + 1     # float 경유하면 반올림되어 +1 이 사라진다
    xml = f'<item data="20260819|100|100|100|100|{big}" />'
    bars = naver.parse_fchart(xml)
    assert bars["20260819"]["volume"] == big


def test_item이_아닌_data속성은_안_잡는다():
    xml = ('<meta data="20260101|1|1|1|1|1" />'
           '<item data="20260819|251500|254500|246500|247500|22683374" />')
    bars = naver.parse_fchart(xml)
    assert list(bars) == ["20260819"]


# M7: 행이 dict 가 아니면(마크업이 통째로 바뀌어 리스트 등이 오는 경우) 그
# 행만 건너뛰고 나머지는 살린다 — KeyError/ValueError 만 잡던 걸 넓혔다.

def test_폴링_행이_dict가_아니면_건너뛴다():
    body = ('{"datas":["005930",'
            '{"itemCode":"000660","stockName":"SK하이닉스",'
            '"closePrice":"1,234,000","tradableStatus":"tradable"}]}')
    q = naver.parse_polling(body)
    assert set(q) == {"000660"}


# M9: 정지 종목의 그날 봉은 시가·고가·저가가 0, 종가만 값이 있다(실측 000880).
# 지금은 close 만 쓰므로 무해하지만 파서가 알아서 걸러주지 않는다는 걸
# 테스트로 남긴다 — 나중에 고가·저가를 쓰는 지표가 생기면 여기부터 볼 것.

def test_정지종목_일봉은_0값이_그대로_넘어온다():
    xml = '<item data="20260819|0|0|0|83800|0" />'
    bars = naver.parse_fchart(xml)
    assert bars["20260819"] == {
        "open": 0, "high": 0, "low": 0, "close": 83800, "volume": 0}


# ── master.json 매입가 참조 과제: parse_market_sum 이 가격도 뽑는다 ──────
#
# 2026-08-20 실측: 코스피·코스닥 전체(4,299종목, 89페이지)를 훑어 가격
# 컬럼이 전부 콤마 포함 순수 숫자임을 확인했다(빈 문자열·"-" 0건, 거래정지
# 종목 000880·183300 포함). 그래도 파서는 방어적으로 짠다 — 아래 테스트들이
# 그 방어선(옆 행 오염 방지, "-"·빈 셀 → None, 클램프 금지)을 고정한다.

def test_가격_셀이_없는_행은_옆_행_가격을_빌려오지_않는다():
    """이번 행에 가격 셀이 통째로 없으면(마크업 변화를 가정) None 이어야
    한다 — 검색 범위를 다음 종목 링크 앞까지로 자르지 않고 `.*?` 로 통째로
    훑으면, 이 종목 이름 뒤에서 시작해 그 *다음* 종목의 가격 셀까지 건너뛰어
    엉뚱하게 묶일 수 있다. 그게 실제로 벌어지지 않는다는 걸 직접 확인한다."""
    html = (
        '<a href="/item/main.naver?code=000001" class="tltle">가격없음</a>\n'
        '<a href="/item/main.naver?code=000002" class="tltle">다음종목</a></td>\n'
        '<td class="number">999,999</td>\n'
    )
    items = naver.parse_market_sum(html)
    assert items["000001"] == {"name": "가격없음", "price": None}
    assert items["000002"] == {"name": "다음종목", "price": 999999}


def test_가격_셀이_대시면_None으로_둔다():
    """polling 의 integratedPriceInfo 에서 실측된 "-" 자리표시자를 이
    컬럼에서는 실측하지 못했지만, 정규식(`[\\d,\\-]*`)이 애초에 "-" 를
    허용하므로 방어적으로 처리한다 — 0 이나 다른 값으로 채우지 않는다
    (클램프 금지)."""
    html = ('<a href="/item/main.naver?code=000001" class="tltle">정지종목</a></td>\n'
            '<td class="number">-</td>\n')
    items = naver.parse_market_sum(html)
    assert items["000001"] == {"name": "정지종목", "price": None}


def test_가격_셀이_빈문자열이면_None으로_둔다():
    html = ('<a href="/item/main.naver?code=000001" class="tltle">빈셀</a></td>\n'
            '<td class="number"></td>\n')
    items = naver.parse_market_sum(html)
    assert items["000001"] == {"name": "빈셀", "price": None}


def test_이름이_깨져도_가격_None인_행이_섞여있으면_전체가_실패로_본다():
    """_corrupted 검사가 새 dict 모양({"name":..,"price":..})에서도 여전히
    이름만 보고 판정하는지 확인한다 — price 필드가 검사를 가리면 안 된다."""
    html = ('<a href="/item/main.naver?code=000001" class="tltle">' + naver._REPLACEMENT
            + '</a></td>\n<td class="number">-</td>\n')
    with pytest.raises(naver.EmptyParseError):
        naver.parse_market_sum(html)


# ── Task 5: 분봉 파서 ────────────────────────────────────────
#
# fchart 의 timeframe=minute 은 시·고·저가가 전부 null 이고 종가만 온다
# (2026-08-20 실측, 2,667개 전수 확인). 지정가 체결 판정은 그 분 안의
# 고가·저가가 있어야 가능하므로 OHLC 를 다 주는 api.stock.naver.com 을 쓴다.

MINUTE_JSON = """[
 {"localDateTime":"20260820090000","currentPrice":256500.0,"openPrice":257000.0,
  "highPrice":258500.0,"lowPrice":256500.0,"accumulatedTradingVolume":949560},
 {"localDateTime":"20260820090100","currentPrice":255000.0,"openPrice":256500.0,
  "highPrice":257000.0,"lowPrice":254500.0,"accumulatedTradingVolume":1002000}
]"""


def test_분봉_파싱():
    out = naver.parse_minute(MINUTE_JSON)
    assert out == [
        {"t": "202608200900", "high": 258500, "low": 256500},
        {"t": "202608200901", "high": 257000, "low": 254500},
    ]


def test_분봉은_시간_오름차순으로_정렬된다():
    """재생이 순서에 의존한다 — 응답 순서를 믿지 않는다."""
    body = """[
     {"localDateTime":"20260820090100","highPrice":2.0,"lowPrice":1.0},
     {"localDateTime":"20260820090000","highPrice":4.0,"lowPrice":3.0}
    ]"""
    assert [m["t"] for m in naver.parse_minute(body)] == \
        ["202608200900", "202608200901"]


def test_망가진_분봉_한_건이_전체를_죽이지_않는다():
    """polling·market_sum 과 같은 태도 — 한 항목이 이상해도 나머지는 살린다."""
    body = """[
     {"localDateTime":"20260820090000","highPrice":2.0,"lowPrice":1.0},
     {"localDateTime":"20260820090100","highPrice":"-","lowPrice":1.0},
     "쓰레기",
     {"localDateTime":"20260820090200","highPrice":6.0,"lowPrice":5.0}
    ]"""
    assert [m["t"] for m in naver.parse_minute(body)] == \
        ["202608200900", "202608200902"]


def test_분봉이_0건이면_거부한다():
    """빈 응답을 '오늘 거래 없음' 으로 조용히 넘기면 체결을 통째로 놓친다."""
    with pytest.raises(naver.EmptyParseError):
        naver.parse_minute("[]")
