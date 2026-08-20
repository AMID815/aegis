# -*- coding: utf-8 -*-
"""네이버 금융. **무인증**이라 개발 PC 에서도 호출해도 된다 (키움과 다르다).

파싱(parse_*, Task 3)과 네트워크(_fetch/fetch_*, Task 4)를 함께 담는다 —
파싱은 문자열 → 값만 하고 판단·저장은 하지 않는다는 경계는 그대로다.

인코딩 함정과 이 모듈이 실제로 막는 것 / 막지 못하는 것
----------------------------------------------------------
시가총액 페이지·ETF 목록·fchart 는 **EUC-KR** 이다. 러너는 Linux/UTF-8 이라
디코드를 명시하지 않으면 종목명이 깨진다.

**이 파일의 "0행이면 실패" 규칙은 이 문제를 막지 못한다.** EUC-KR 바이트를
utf-8/replace 로 잘못 디코드해도 ASCII 로만 이루어진 마크업(`<a href=`,
`code=`, 숫자, JSON 키)은 손상되지 않는다 — 깨지는 건 한글 이름뿐이다. 그래서
정규식은 여전히 매치하고 행 수도 그대로다(실측: 0행이 아니라 정상 행 수 그대로,
이름만 U+FFFD 로 깨졌다). "0행이면 실패"가 잡는 건 **마크업 자체가 바뀌어서
아무것도 안 뽑히는 경우**다 — 이건 실제로 유효하고 남겨둘 이유가 있다.

**실제 방어선은 디코드를 strict 로 하는 것**이다(utf-8 로 EUC-KR 바이트를
strict 디코드하면 첫 바이트에서 바로 UnicodeDecodeError). 이건 파싱 함수가
아니라 아래 `_fetch`(네트워크 계층)가 책임진다 — 거기서 `errors="replace"` 를
쓰면 이 파일의 어떤 방어도 소용없다. 여기서는 보조 방어선으로, 뽑아낸 이름에
치환문자(U+FFFD)가 섞여 있으면 그것도 실패로 올린다(아래 `_corrupted`) — strict
디코드가 어딘가에서 빠지더라도 마지막에 한 번 더 잡기 위해서다.

한 배치(polling 최대 60종목, ETF 목록 1162건)에 섞인 개별 항목 하나가
깨졌다고 배치 전체를 죽이지 않는다. 그 항목만 조용히 빼고 나머지를
살린다 — 빠진 항목은 이 모듈의 결과 dict 에서 그냥 없는 것으로 나타나므로,
호출자(아래 missing_codes 등)가 "요청했는데 없다"로 잡아낸다. 상폐·
거래정지로 응답 자체에서 통째로 빠지는 종목과 똑같은 방식으로 드러난다.

⚠ 단, 이건 배치 안에 살아남는 행이 하나라도 있을 때 얘기다. 한 배치의
모든 코드가 상폐·거래정지(closePrice="-")면 parse_polling 은 0건으로 보고
EmptyParseError 를 낸다 — missing_codes 로 조용히 드러나는 게 아니라 그
자리에서 예외가 난다. 보유 종목이 몇 개 안 되는 개인용 트래커에서는(1~2
종목이 전부 정지) 이 경우가 "60개 중 한둘만 빠지는" 경우보다 오히려
현실적일 수 있다. 그래도 결과는 괜찮다 — 호출자(quotes.main)가 이 예외를
잡아 커밋하지 않고 직전 값을 유지하므로, 정지된 종목 하나가 스냅샷 전체를
막는 눈에 보이는 실패로 이어질 뿐 잘못된 값이 커밋되지는 않는다.

이 "누락은 호출자가 대조해서 잡는다" 전제는 **polling 에만 성립한다** —
fetch_quotes 는 요청한 코드 목록(asked)이 있어서 missing_codes 로 대조가
된다. parse_market_sum/parse_etf 는 그런 대조 대상이 없다 — 목록 자체가
답이라 한두 행이 조용히 빠져도(2026-08-19 실측: `_SUM_RE` 가 숫자만 찾던
시절 코스피 2페이지에서 영숫자 코드 0126Z0 삼성에피스홀딩스 한 종목을 그냥
빼먹은 채 49행을 "정상"으로 돌려준 사고) 아무도 모른다. parse_etf 에는
그래서 최소 개수 하한(MIN_ETF_ROWS)을 둔다 — parse_market_sum 에는 두지
않는다, 이유는 아래 함수 docstring 참조.
"""
from __future__ import annotations

import json
import math
import re

UA = {"User-Agent": "Mozilla/5.0"}   # 아래 `_fetch` 가 요청 헤더로 쓴다

POLL_URL = "https://polling.finance.naver.com/api/realtime/domestic/stock/{codes}"
FCHART_URL = ("https://fchart.stock.naver.com/sise.nhn"
              "?symbol={symbol}&timeframe=day&count={n}&requestType=0")

# 분봉. **fchart 가 아니라 api.stock.naver.com 이다** — 2026-08-20 실측:
# fchart 의 timeframe=minute 은 시·고·저가가 전부 null 이고 종가만 온다
# (2,667개 전수 확인). 지정가 체결 판정은 그 분 안의 고가·저가가 있어야
# 가능하므로 OHLC 를 다 주는 이쪽을 쓴다. 응답은 **UTF-8 JSON** 이다
# (fchart 의 EUC-KR XML 과 다르다 — 인코딩을 헷갈리면 즉시 터진다).
#
# 09:00~15:30(KRX 정규장)만 온다. startDateTime 을 08:00 으로 줘도
# 381개만 왔다 — 시간외·NXT 구간은 이 엔드포인트에 없다(설계 §6).
# 창은 약 7거래일이라 그보다 오래된 날짜는 빈 응답이 온다.
MINUTE_URL = ("https://api.stock.naver.com/chart/domestic/item/{symbol}/minute"
              "?startDateTime={start}&endDateTime={end}")
SUM_URL = "https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
ETF_URL = "https://finance.naver.com/api/sise/etfItemList.nhn"

# <item> 요소만 잡는다. data="..." 속성이면 아무 태그나 잡던 걸 좁혔다 —
# 2026-08-19 실측: <chartdata>·<protocol> 어디에도 data= 속성이 없어 지금은
# 차이가 없지만, 나중에 다른 곳에 data= 속성이 붙어도 엉뚱한 걸 긁어오지 않는다.
_ITEM_RE = re.compile(r'<item\s+data="([^"]+)"')

# KRX 코드는 숫자만이 아니다. 2026-08-19 실측(코스피 시가총액 페이지 전체
# 50p 를 [0-9A-Za-z]{6} 로 훑음): 0126Z0(삼성에피스홀딩스, 코스피 상위 60위권,
# 363,500원 정상 거래), 0167A0/0162Z0(ETF) 등 영숫자 코드가 실제로 상장되어
# 있다. 관측된 알파벳은 전부 대문자였다(소문자 사례 없음). \d{6} 로 좁혀 두면
# 정상 행(polling·fchart 는 이 코드로 문제없이 응답)을 시가총액 페이지에서만
# 조용히 놓친다 — 개수가 50건에서 49건으로 줄 뿐 EmptyParseError 가 뜨지
# 않아서 아무도 못 알아챈다.
_SUM_RE = re.compile(r'<a href="/item/main\.naver\?code=([0-9A-Z]{6})"[^>]*>([^<]+)</a>')

# 현재가 컬럼. parse_market_sum 이 이 정규식을 종목 링크 뒤부터 **다음 종목
# 링크 앞까지로 범위를 잘라서**만 검색한다(아래 parse_market_sum docstring
# 참조) — 이 정규식 자체는 "이번 행 안에서 처음 만나는 숫자 셀"만 잡으면
# 되고, 옆 행과 안 섞이게 막는 책임은 호출자(검색 범위를 자르는 쪽)에 있다.
_PRICE_RE = re.compile(r'<td class="number">([\d,\-]*)</td>')

_REPLACEMENT = "�"   # 잘못된 디코드가 한글 자리에 남기는 흔적

# ETF 목록은 페이징이 없다 — 한 번에 전체를 돌려준다(2026-08-19 실측 1,162건).
# 그래서 "행이 적다"는 것 자체가 이상 신호일 수 있다. 반대로 parse_market_sum
# 은 페이지네이션이 있어서 마지막 페이지가 원래 적다(실측: 코스피 50페이지 중
# 마지막 50페이지가 28건, 코스닥 37페이지 중 마지막이 21건 — 정상이다). 그래서
# 개수 하한은 여기(ETF)에만 둔다. 100 은 1,162 실측치에서 91% 이상 빠져야
# 걸리는 보수적인 값 — 상장 ETF 가 하루아침에 이 밑으로 줄어들 일은 없다.
MIN_ETF_ROWS = 100


class EmptyParseError(Exception):
    """응답은 왔는데 아무것도(또는 믿을 만한 게) 못 뽑았다.

    마크업이 바뀌었거나("0건") — 디코드가 깨져서 이름이 치환문자로 나왔거나 —
    (ETF 한정) 개수가 있을 수 없이 적다.
    """


def _num(s):
    """가격 문자열(콤마 포함) → int. 비어있거나 None 이거나 "-"(정지 종목의
    시간외/통합가 필드에서 실측된 자리표시자) 면 ValueError.

    호출하는 쪽(parse_polling)이 종목 하나 단위로 이 예외를 잡는다 — 여기서
    잡지 않는 건 "이 함수 자체는 늘 엄격해야 한다"는 계약을 지키기 위해서다.
    """
    return int(str(s).replace(",", "").strip())


def _numf(v):
    """JSON 수치 필드 → int. `_num` 과 달리 **실수를 받는다.**

    `_num` 은 콤마 낀 문자열("247,500")용이라 `int(str(v)...)` 로 되어 있어
    `258500.0` 을 못 읽는다(`int("258500.0")` 은 ValueError). 그런데 분봉
    엔드포인트는 가격을 **실수 JSON 으로** 준다(2026-08-20 실측:
    `"highPrice":258500.0`). `_num` 을 그대로 쓰면 모든 행이 ValueError 로
    걸러져 `EmptyParseError` 가 나고, **자동 체결이 영원히 안 도는데
    아무 오류도 안 보이는** 상태가 된다.

    `_num` 쪽을 고치지 않는 이유: 그건 HTML/XML 엔드포인트 전용이고
    "늘 엄격해야 한다"는 계약이 docstring 에 명시돼 있다. 호출자가 다르면
    변환도 다른 게 맞다.

    원 단위 정수라 float→round 는 정확하다. 콤마도 흡수해둔다 — 이
    엔드포인트는 안 쓰지만 공짜다.
    """
    return round(float(str(v).replace(",", "")))


def _corrupted(names) -> bool:
    """디코드가 잘못되면 한글 이름 자리에 치환문자(U+FFFD)가 남는다.

    "0행이면 실패"만으로는 이 사고를 못 잡는다 — 마크업(ASCII)은 멀쩡히
    살아남고 한글만 깨지므로 행 수가 그대로다. strict 디코드가 진짜 방어선
    (아래 `_fetch`)이고, 이건 그게 어딘가에서 빠졌을 때의 마지막 그물이다.
    """
    return any(_REPLACEMENT in n for n in names)


def parse_polling(body: str) -> dict:
    """**closePrice(정규장 종가)** 를 쓴다.

    같은 응답에 시간외(overMarketPriceInfo.overPrice)와 통합(integratedPriceInfo)이
    같이 온다. 2026-08-19 삼성전자 실측: 247,500 / 256,000 / 257,500 — 3.4% 차이.

    거래정지 종목(000880·183300 실측)은 closePrice 는 정상이지만
    integratedPriceInfo.openPrice 등 다른 가격 필드는 문자열 `"-"` 로 온다 —
    `_num("-")` 는 ValueError. closePrice 자체가 이렇게 올 가능성까지
    실측하지는 못했지만("-" 가 이미 실제로 쓰이는 자리표시자라는 것 자체가
    근거), 배치 하나(최대 60종목)를 통째로 죽이지 않도록 종목 하나만
    건너뛴다. 행이 dict 가 아닌 경우(마크업이 통째로 바뀌어 리스트 등이
    오는 극단적인 경우)도 같이 걸러 나머지 종목은 살린다.

    여기 나오는 stockName 도 한글이지만 _corrupted() 는 걸지 않는다. 이유는
    이름에 한글이 없어서가 아니라(있다) 이 엔드포인트가 애초에 UTF-8 이라
    parse_market_sum·parse_etf 를 위협하는 EUC-KR/UTF-8 코덱 불일치가 여기선
    발생할 수 없고, 화면도 종목명을 quotes[].name 이 아니라 positions.json 의
    각 포지션 name(손입력 원본)에서 읽어서 이 필드가 깨져도 렌더링에 영향이
    없기 때문이다.
    """
    d = json.loads(body)
    out = {}
    for row in d.get("datas", []):
        try:
            code = row.get("itemCode")
            if not code:
                continue
            price = _num(row["closePrice"])
        except (KeyError, ValueError, TypeError, AttributeError):
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
    (참고: `<chartdata precision="N">` 속성이 0/2 로 이걸 authoritative 하게
    알려준다 — 지금 방식이 애매해지면 그쪽으로 바꾸면 된다. `<item>` 태그 밖의
    속성이라 지금은 안 읽는다.)

    거래량은 콤마 없는 순정수 문자열이라 float 경유 없이 바로 int() 한다.
    (float 경유해도 실측 규모 — 수천만 주 — 에서는 2**53 한계에 한참 못 미쳐
    정밀도 손실이 없음을 확인했다. 그래도 애초에 거칠 이유가 없다.)

    OHLC 가 nan/inf 면 버린다. `float("1e400")` 은 예외 없이 inf 가 되고,
    `json.dumps` 는 그걸 `Infinity` 로 쓰는데 표준 JSON 이 아니라서
    브라우저의 `JSON.parse` 가 거부한다 — 필드 하나 때문에 quotes.json 이나
    history 전체를 못 읽어 화면이 통째로 빈다(models.py 의 bb5410d 와 같은
    부류의 사고).

    거래정지 종목의 그날 봉은 시가·고가·저가가 전부 0 이고 종가만 값이
    있다(실측: `20260819|0|0|0|83800|0`). 지금은 close 만 쓰므로 무해하지만,
    나중에 고가·저가를 쓰는 지표가 생기면 이 0 이 "그날 0원에 거래됐다"로
    오독될 수 있다 — 그때 가서 처리할 것.
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
        if not all(math.isfinite(x) for x in ohlc):
            continue
        o, h, l, c = (int(x) if x.is_integer() else x for x in ohlc)
        bars[day] = {"open": o, "high": h, "low": l, "close": c, "volume": volume}
    if not bars:
        raise EmptyParseError("일봉 0건")
    return bars


def parse_minute(body: str) -> list:
    """분봉 JSON → [{"t": "YYYYMMDDHHMM", "high": int, "low": int}, ...].

    **시간 오름차순으로 정렬해서 돌려준다** — orders.replay 가 순서에
    의존하는데, 응답 순서를 믿을 근거가 없다.

    항목 하나가 망가져도(거래정지 종목의 `"-"` 자리표시자, 마크업 변경으로
    dict 가 아닌 값) 나머지는 살린다 — parse_polling·parse_market_sum 이
    이미 취하는 태도와 같다. 한 종목의 한 분 때문에 그날 체결 판정을
    통째로 잃는 게 더 나쁘다.

    0건이면 EmptyParseError 다. 빈 응답을 "오늘 거래 없음"으로 조용히
    넘기면 실제로는 API 가 바뀐 건데 체결을 영원히 못 잡는다.
    """
    rows = json.loads(body)
    out = []
    for row in rows if isinstance(rows, list) else []:
        try:
            t = str(row["localDateTime"])[:12]     # 초 단위는 버린다
            out.append({"t": t,
                        "high": _numf(row["highPrice"]),
                        "low": _numf(row["lowPrice"])})
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
    if not out:
        raise EmptyParseError("분봉 결과 0건")
    out.sort(key=lambda m: m["t"])
    return out


def trading_days(body: str) -> list:
    """일봉 날짜 = 거래일. 정적 휴장일 목록을 쓰지 않는 근거.

    YYYYMMDD 는 항상 8자리 고정폭 숫자 문자열이라 문자열 정렬이 곧 날짜순
    정렬이다 — 자릿수가 들쭉날쭉해야 깨지는데 이 필드는 그럴 일이 없다.
    """
    return [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in sorted(parse_fchart(body))]


def parse_market_sum(html: str) -> dict:
    """시가총액 페이지의 종목 링크(class="tltle")에서 코드·이름·현재가를 뽑는다.

    반환값: `{코드: {"name": 이름, "price": 가격 또는 None}}`. parse_polling
    이 이미 쓰는 "코드 → 필드 dict" 모양을 그대로 따른다 — 나중에 필드가
    더 늘어도 위치 기반 튜플 언패킹이 깨지지 않는다.

    2026-08-19 실측(코스피 1페이지, 50행)으로 정규식이 표(우선주·영숫자
    코드 포함)만 정확히 잡고 내비게이션 등 다른 code= 링크는 섞이지 않음을
    확인했다.

    ⚠ 개수 하한을 두지 않는다 — 마지막 페이지는 원래 적다. 실측: 코스피
    50페이지 중 마지막(50페이지)이 28건, 코스닥 37페이지 중 마지막(37페이지)이
    21건. 여기에 "40건 미만이면 실패" 같은 하한을 걸면 master.py(Task 9)가
    페이지를 넘기다 정확히 그 마지막 정상 페이지에서 EmptyParseError 를
    맞는다 — 페이지 밖(51·52페이지 등)은 이미 0건으로 와서(실측 확인) 기존
    "0건이면 실패" 규칙만으로 충분히 걸린다. 대신 디코드 손상(이름이
    치환문자로 깨짐)은 행 수와 무관하게 잡는다 — 그게 이 페이지에서 실제로
    일어난 사고(위 모듈 docstring)다.

    가격 컬럼 (2026-08-20 실측 — app.js 매입가 오타 가드가 신규 매수에도
    걸리게 하는 과제)
    ------------------------------------------------------------------
    종목 링크 바로 다음의 첫 `<td class="number">` 가 현재가다. 코스피·
    코스닥 **전체**(4,299종목, 89페이지)를 훑어 전수 확인했다 — 값은
    전부 콤마 포함 순수 숫자였고 빈 문자열·"-" 는 0건이었다. 실측 당시
    polling 상 tradableStatus=halt 였던 두 종목(000880·183300)도 이
    표에서는 마지막 체결가가 숫자로 그대로 나왔다 — polling 의
    integratedPriceInfo 필드에서만 보이는 "-" 자리표시자(parse_polling
    docstring 참조)는 이 표에서는 관측되지 않았다. ETF(예: 069500 KODEX
    200)도 같은 컬럼 위치에서 polling 값과 정확히 일치했다.

    그래도 방어적으로 파싱한다 — 신규상장 당일 등 미관측 상황을 포함해
    이 컬럼에서 무언가 못 읽으면(셀이 없거나 "-"거나 콤마만 있거나)
    **price 를 None 으로 둔다, 0 이나 추정값으로 채우지 않는다**(설계
    "클램프 금지" 원칙 — app.js 가 그 종목만 가드 없이 넘어가게 한다).
    이름은 여전히 살린다 — 가격 하나 못 읽었다고 자동완성에서 그 종목
    자체를 빼버리면 원래 문제(신규 매수는 참고가가 없다)가 그대로 남는다.

    같은 정규식(`_SUM_RE`)으로 먼저 코드·이름 위치를 전부 찾고, 각 매치의
    끝부터 **다음 매치가 시작하는 자리(또는 문서 끝)까지만** `_PRICE_RE`
    로 검색한다. 이름 뒤에서 시작해 다음 `<td class="number">` 까지
    통째로 `.*?` 로 훑는 정규식 한 방으로 처리하면, 이번 행에 가격 셀이
    없는 마크업 변화가 생겼을 때 그 `.*?` 가 그대로 다음 행의 가격 셀까지
    건너뛰어 **엉뚱한 종목의 가격을 이 종목 것으로 잘못 묶을 수 있다** —
    이 파일이 가장 경계하는 부류의 사고(조용히 틀린 값이 섞이는 것, 위
    0126Z0 사례)를 오타 가드 구현 자체에서 새로 만들 순 없다. 검색
    범위를 다음 종목 링크 앞까지로 자르면, 이번 행에 가격 셀이 없을 때
    그냥 못 찾을 뿐(price=None)이고 옆 행 값을 잘못 가져오는 경우가
    구조적으로 없다.
    """
    matches = list(_SUM_RE.finditer(html))
    if not matches:
        raise EmptyParseError("시가총액 페이지 0건")
    items = {}
    for i, m in enumerate(matches):
        code, name = m.group(1), m.group(2).strip()
        window_end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        price_m = _PRICE_RE.search(html, m.end(), window_end)
        price = None
        if price_m:
            try:
                price = _num(price_m.group(1))
            except ValueError:
                price = None      # "-"·빈 문자열 등 — 클램프하지 않고 None 으로 둔다
        items[code] = {"name": name, "price": price}
    if _corrupted(v["name"] for v in items.values()):
        raise EmptyParseError("시가총액 페이지 이름이 깨졌다 — 인코딩 오류로 판단")
    return items


def parse_etf(body: str) -> dict:
    """ETF 목록 JSON → {코드: 이름}.

    itemcode·itemname 중 하나라도 없는 항목(또는 딕셔너리가 아닌 행)은 그것만
    건너뛴다 — parse_polling 과 같은 이유로, 1,162건 중 하나가 깨졌다고 전체를
    죽이지 않는다.

    페이징 없이 한 번에 전체를 돌려주므로(parse_market_sum 과 달리 "마지막이
    원래 적다"는 예외가 없다) 개수 하한(MIN_ETF_ROWS)을 둔다 — 여기서 조용히
    몇 건만 빠지면(parse_market_sum 이 0126Z0 을 놓쳤던 것과 같은 방식) 대조할
    "요청 목록"이 없어서 아무도 못 잡는다.
    """
    lst = json.loads(body).get("result", {}).get("etfItemList", [])
    items = {}
    for r in lst:
        try:
            code = r.get("itemcode")
            name = r.get("itemname")
        except (AttributeError, TypeError):
            continue
        if not code or not name:
            continue
        items[code] = name
    if not items:
        raise EmptyParseError("ETF 목록 0건")
    if _corrupted(items.values()):
        raise EmptyParseError("ETF 목록 이름이 깨졌다 — 인코딩 오류로 판단")
    if len(items) < MIN_ETF_ROWS:
        raise EmptyParseError(f"ETF 목록이 너무 적다({len(items)}건 < {MIN_ETF_ROWS}) — 마크업이 바뀐 것으로 본다")
    return items


# ── 네트워크 ────────────────────────────────────────────────
import urllib.request

# polling 콤마 배치 크기. 2026-08-19 실측(가짜 6자리 코드로 URL 을 늘려가며
# 진짜 요청을 보냄): 상한은 "개수"가 아니라 URL 길이다. 서버는 모르는 코드를
# 그냥 조용히 빼고 200 을 준다(코드가 4,299건 상장 종목 범위를 넘어가는
# n=140 이상에서도 매번 정상 응답, datas 개수만 실제 상장분만큼 늘어남).
# n=1000(코드 6자리 기준 url_len≈7,061)까지 정상, n=1001(≈7,068자)부터
# 400 Bad Request, n=1165(≈8,216자)부터 414 Request-URI Too Large — 두
# 단계로 막힌다(양쪽 경계 모두 이분탐색으로 좁혀 확인, 재측정으로 재확인함).
# CHUNK=60(url_len≈481)은 이 상한의 약 1/16 이라 크게 여유롭다. 실제 보유
# 종목 수(수십 단위)를 감안하면 더 키울 실익이 적어 그대로 둔다 — 원래
# 주석의 "대조군이 80을 쓴다"는 남의 프로젝트 값을 근거 삼은 추측이었고,
# 이제는 이 파일 자체의 실측으로 대체한다.
CHUNK = 60

EUCKR = "cp949"     # euc_kr 은 한글 79%를 못 읽는다 (설계 §10-3)


def _fetch(url: str, enc: str) -> str:
    """`enc` 는 필수다(기본값 없음). 이 함수는 4가지 URL 을 다루는데 그중
    3개(FCHART/SUM/ETF)가 CP949 이고 UTF-8 은 POLL_URL 하나뿐이다 — 기본값을
    두면 "3/4 확률로 틀린 기본값"이 되어, 나중에 (예: master.py, Task 9) 이
    함수를 처음 쓰는 사람이 인코딩을 깜빡해도 조용히 넘어간다. strict 디코드
    덕에 그런 실수는 첫 실행에서 바로 UnicodeDecodeError 로 터지긴 하지만
    (아래), 애초에 그 함정을 없애는 쪽이 공짜로 더 안전하다.

    **strict 디코드만 쓴다.** `errors="replace"` 를 쓰면 EUC-KR 본문을 UTF-8 로
    읽어도 예외 없이 지나가고(ASCII 마크업은 멀쩡하므로) 한글만 깨진 채 커밋된다.
    실측 2026-08-19: replace 는 50행 중 42행 이름이 깨진 채 '성공', strict 는
    UnicodeDecodeError. 인코딩 함정의 유일한 방어선이다.

    HTTP 에러(404/500 등 `HTTPError`, DNS 실패 등 `URLError`)는 여기서 잡지
    않고 그대로 전파한다 — "이 실패로 커밋을 막을지"는 이 파일이 아니라
    호출자(quotes.py 등)의 판단이다. `type(e).__name__: {e}` 로 찍으면
    `HTTPError: HTTP Error 404: Not Found` 처럼 상태 코드까지는 나오므로
    Actions 로그에서 어떤 종류의 실패인지는 알 수 있다(어떤 URL 이었는지는
    나오지 않지만, fetch_* 호출 지점 자체가 몇 안 되므로 실용적으로는
    충분하다고 판단했다 — 별도 래핑은 하지 않는다).

    재시도는 하지 않는다. 이 스크립트는 30분마다 도는 스케줄이라 한 번
    실패해도 다음 실행이 사실상 재시도이고(자연 치유), close.py 가 마감
    확정 시 다시 백필한다 — 여기서 재시도 루프를 추가하면 실패를 감추는
    복잡도만 늘고 실익은 없다.
    """
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode(enc)          # strict — replace 금지


def fetch_quotes(codes: list) -> dict:
    out = {}
    for i in range(0, len(codes), CHUNK):
        part = codes[i:i + CHUNK]
        out.update(parse_polling(_fetch(POLL_URL.format(codes=",".join(part)), "utf-8")))
    return out


def missing_codes(asked: list, got: dict) -> list:
    """요청 수와 응답 수를 대조하지 않으면 사라진 종목을 아무도 모른다."""
    return [c for c in asked if c not in got]


def fetch_bars(symbol: str, n: int = 60) -> dict:
    return parse_fchart(_fetch(FCHART_URL.format(symbol=symbol, n=n), EUCKR))


def fetch_minute(symbol: str, day: str) -> list:
    """하루치 분봉. `day` 는 "YYYY-MM-DD".

    창이 약 7거래일이라 그보다 오래된 날짜는 빈 응답이 온다 —
    EmptyParseError 로 나가고, 호출자(autofill)가 그 종목을 건너뛴다.
    """
    d = day.replace("-", "")
    return parse_minute(_fetch(
        MINUTE_URL.format(symbol=symbol, start=f"{d}000000", end=f"{d}235959"),
        "utf-8"))


def fetch_trading_days(n: int = 250) -> list:
    """삼성전자 일봉 = KRX 정규장 거래일.

    삼성전자 하나만 쓰는 이유: 거래정지 종목도 그날 봉 자체는 나온다(시가·
    고가·저가는 0, 종가만 값 — parse_fchart docstring 실측). trading_days 는
    날짜(parts[0])만 읽고 가격은 보지 않으므로, 삼성전자가 정지돼도 그날
    거래일이라는 사실 자체는 여전히 봉으로 나와 문제가 없다. 완전 상장폐지처럼
    봉 자체가 안 나오는 시나리오는 실측 대상이 없고(코스피 시총 1위, 상폐
    위험이 사실상 없음), 설령 하루 빠져도 다음 실행(30분 주기)에서 누적
    일봉 250개 중 그 하루만 비는 정도라 두 번째 종목을 곁들이는 비용을
    들일 이유가 없다고 판단했다.
    """
    return trading_days(_fetch(FCHART_URL.format(symbol="005930", n=n), EUCKR))


def fetch_market_sum(sosok: int, page: int) -> dict:
    return parse_market_sum(_fetch(SUM_URL.format(sosok=sosok, page=page), EUCKR))


def fetch_etf() -> dict:
    return parse_etf(_fetch(ETF_URL, EUCKR))
