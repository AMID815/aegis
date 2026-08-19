# -*- coding: utf-8 -*-
"""네이버 금융. **무인증**이라 개발 PC 에서도 호출해도 된다 (키움과 다르다).

인코딩 함정: 시가총액 페이지·ETF 목록·fchart 는 **EUC-KR** 이다.
러너는 Linux/UTF-8 이라 명시하지 않으면 종목명이 깨지는데, 예외가 안 나고
'성공'으로 끝나서 깨진 파일이 그대로 커밋된다. 그래서 0행이면 실패로 올린다.

이 파일은 **순수 파싱만** 담당한다(Task 3). 네트워크 호출(_fetch/fetch_*)은
별도 커밋(Task 4)에서 얹는다 — 여기서는 문자열 → 값만 한다.

한 배치(polling 최대 60종목, ETF 목록 1162건)에 섞인 개별 항목 하나가
깨졌다고 배치 전체를 죽이지 않는다. 그 항목만 조용히 빼고 나머지를
살린다 — 빠진 항목은 이 모듈의 결과 dict 에서 그냥 없는 것으로 나타나므로,
호출자(Task 4 의 missing_codes 등)가 "요청했는데 없다"로 잡아낸다. 상폐·
거래정지로 응답 자체에서 통째로 빠지는 종목과 똑같은 방식으로 드러난다.
0건이면(배치 전체가 깨졌으면) 그때는 EmptyParseError 로 알린다 — 그것까지
조용히 삼키면 인코딩 함정과 똑같은 사고(예외 없이 빈 파일 커밋)가 난다.
"""
from __future__ import annotations

import json
import re

POLL_URL = "https://polling.finance.naver.com/api/realtime/domestic/stock/{codes}"
FCHART_URL = ("https://fchart.stock.naver.com/sise.nhn"
              "?symbol={symbol}&timeframe=day&count={n}&requestType=0")
SUM_URL = "https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
ETF_URL = "https://finance.naver.com/api/sise/etfItemList.nhn"

# <item> 요소만 잡는다. 예전에는 data="..." 속성이면 아무 태그나 잡았는데
# (2026-08-19 실측: <chartdata>·<protocol> 어디에도 data= 속성이 없어 실제로는
# 문제가 없었지만) <item> 으로 못박아 두면 나중에 네이버가 다른 곳에 data=
# 속성을 붙여도 엉뚱한 걸 긁어오지 않는다.
_ITEM_RE = re.compile(r'<item\s+data="([^"]+)"')
_SUM_RE = re.compile(r'<a href="/item/main\.naver\?code=(\d{6})"[^>]*>([^<]+)</a>')


class EmptyParseError(Exception):
    """응답은 왔는데 아무것도 못 뽑았다 = 마크업이 바뀌었다(또는 인코딩이 깨졌다)."""


def _num(s):
    """가격 문자열(콤마 포함) → int. 비어있거나 None 이면 ValueError.

    호출하는 쪽(parse_polling)이 종목 하나 단위로 이 예외를 잡는다 — 여기서
    잡지 않는 건 "이 함수 자체는 늘 엄격해야 한다"는 계약을 지키기 위해서다.
    """
    return int(str(s).replace(",", "").strip())


def parse_polling(body: str) -> dict:
    """**closePrice(정규장 종가)** 를 쓴다.

    같은 응답에 시간외(overMarketPriceInfo.overPrice)와 통합(integratedPriceInfo)이
    같이 온다. 2026-08-19 삼성전자 실측: 247,500 / 256,000 / 257,500 — 3.4% 차이.

    실측(493종목 배치 조회, 2건의 halt 포함)으로는 closePrice 가 없는 행을
    보지 못했다 — 존재하지 않는 코드는 datas 에서 행 자체가 빠지고, 거래정지
    종목도 closePrice 는 정상이었다. 그래도 장전처럼 가격 필드가 비어 있을
    가능성은 남아 있어서, 그 종목 하나만 건너뛰고 나머지 59종목은 살린다.
    """
    d = json.loads(body)
    out = {}
    for row in d.get("datas", []):
        code = row.get("itemCode")
        if not code:
            continue
        try:
            price = _num(row["closePrice"])
        except (KeyError, ValueError):
            continue
        out[code] = {
            "price": price,
            "name": row.get("stockName", ""),
            "status": row.get("tradableStatus", "unknown"),
            "market": row.get("marketStatus", ""),
        }
    if not out:
        raise EmptyParseError("polling 결과 0건")
    return out


def parse_fchart(body: str) -> dict:
    """'YYYYMMDD|시가|고가|저가|종가|거래량' → {날짜: {...}}.

    종목은 원 단위 정수, 지수는 소수점이 있다 — 값 자체가 정수인지로 판단한다.
    필드마다 따로 판단하므로 지수가 우연히 정각(예: 6500.0)에 마감하면 그 필드만
    int 로 나오는 흠은 있지만, JSON 도 JS 도 247500 과 247500.0 을 같은 수로
    다루므로 해가 없다. 반대로 늘 float 로 못박으면 원화 정수 가격마다 가짜
    소수점(".0")이 커밋되는 모든 JSON 파일에 영원히 남는다 — 그게 더 나쁘다.

    거래량은 콤마 없는 순정수 문자열이라 float 경유 없이 바로 int() 한다.
    (float 경유해도 실측 규모 — 수천만 주 — 에서는 2**53 한계에 한참 못 미쳐
    정밀도 손실이 없음을 확인했다. 그래도 애초에 거칠 이유가 없다.)
    """
    bars = {}
    for raw in _ITEM_RE.findall(body):
        parts = raw.split("|")
        if len(parts) < 6:
            continue
        day = parts[0]
        try:
            ohlc = [float(x) for x in parts[1:5]]
            volume = int(parts[5])
        except ValueError:
            continue
        o, h, l, c = (int(x) if x.is_integer() else x for x in ohlc)
        bars[day] = {"open": o, "high": h, "low": l, "close": c, "volume": volume}
    if not bars:
        raise EmptyParseError("일봉 0건")
    return bars


def trading_days(body: str) -> list:
    """일봉 날짜 = 거래일. 정적 휴장일 목록을 쓰지 않는 근거.

    YYYYMMDD 는 항상 8자리 고정폭 숫자 문자열이라 문자열 정렬이 곧 날짜순
    정렬이다 — 자릿수가 들쭉날쭉해야 깨지는데 이 필드는 그럴 일이 없다.
    """
    return [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in sorted(parse_fchart(body))]


def parse_market_sum(html: str) -> dict:
    """시가총액 페이지의 종목 링크(class="tltle")에서 코드·이름을 뽑는다.

    2026-08-19 실측(코스피 1페이지, 50행)으로 정규식이 표(우선주 포함)만
    정확히 잡고 내비게이션 등 다른 code= 링크는 섞이지 않음을 확인했다.
    """
    items = {c: n.strip() for c, n in _SUM_RE.findall(html)}
    if not items:
        raise EmptyParseError("시가총액 페이지 0건")
    return items


def parse_etf(body: str) -> dict:
    """ETF 목록 JSON → {코드: 이름}. itemcode·itemname 중 하나라도 없는
    항목은 그것만 건너뛴다 — parse_polling 과 같은 이유로, 1162건 중 하나가
    깨졌다고 전체를 죽이지 않는다."""
    lst = json.loads(body).get("result", {}).get("etfItemList", [])
    items = {}
    for r in lst:
        code = r.get("itemcode")
        name = r.get("itemname")
        if not code or not name:
            continue
        items[code] = name
    if not items:
        raise EmptyParseError("ETF 목록 0건")
    return items
