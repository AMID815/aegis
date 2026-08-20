# -*- coding: utf-8 -*-
"""positions.json 의 모양을 지킨다. 수익률은 여기서 계산하지 않는다 (페이지 몫).

normalize() 는 positions.json 의 신뢰 경계다. 스키마 버전이 다르면 거부하고,
개별 항목이 깨졌으면 조용히 고쳐 쓰지 않고 버린 뒤 dropped 로 보고한다.
파일에 쓰는 쪽(장래의 스크립트)은 dropped 가 비어있지 않으면 쓰기를 거부해야 한다.
"""
from __future__ import annotations

import copy
import datetime
import math
import re

from . import orders as _orders

SCHEMA = 1
# KRX 는 숫자 6자리만 쓰지 않는다 — 2026-08-19 실측(87페이지 전수): 삼성에피스
# 홀딩스 0126Z0, SOL AI반도체TOP2플러스 0167A0 등 영숫자 코드가 4,299건 중
# 375건(8.7%) — K/L 접미 우선주(예: 03473K SK우, 37550K/37550L DL이앤씨우)와
# SPAC 약 50건 포함. 숫자만 받으면 naver.parse_market_sum 이 뽑아온 코드를
# intake 가 문 앞에서 거부하게 된다. 관측된 알파벳은 전부 대문자(소문자 0건,
# 87페이지 전수 확인) — 그래서 [0-9A-Z] 로 좁혔지 [0-9A-Za-z] 로 넓히지 않았다.
#
# `$` 가 아니라 `\Z` 로 끝을 앵커한다. `$` 는 문자열 끝의 개행 바로 앞에서도
# 매치한다 — 원본 정규식은 이 사실을 놓쳐서 "005930\n" 같은 값도 그대로
# 통과시켰고, id 에 개행이 박히는 사고로 이어졌다(Task 6 이 파싱할 이슈
# 본문은 개행이 흔하다). DATE_RE 는 이후 datetime.date.fromisoformat 이
# 한 번 더 걸러줘서 실질적인 구멍은 없었지만, 같은 종류의 앵커 실수를
# 남겨둘 이유가 없어 함께 고쳤다.
CODE_RE = re.compile(r"^[0-9A-Z]{6}\Z")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")
OPEN, CLOSED, PENDING, EXPIRED = "open", "closed", "pending", "expired"
# 지정가 관찰의 기본 관찰 기간(거래일) — 사용자가 3에서 5로 조정했다
# (2026-08-21). 상수 하나로 뽑아둔 이유: normalize() 도 이제(CHANGE 2,
# 아래 _watch_sane/normalize 참조) days 가 없는 옛 기록에 같은 기본값을
# 채워 넣는다 — apply_watch(쓰기 시점 기본값)와 normalize(읽기 시점 채움)
# 가 서로 다른 숫자를 하드코딩하면 조용히 어긋난다.
WATCH_DAYS_DEFAULT = 5


class RejectedError(Exception):
    """입력이 규칙에 맞지 않아 반영하지 않았다."""


class AlreadyApplied(RejectedError):
    """중복 id — 이미 반영된 매수. 값을 "고쳐서 다시 제출"해야 하는 일반
    RejectedError 와는 성격이 다르다 — 이 요청은 틀린 게 아니라 이미 끝난
    것이라, 호출자(intake.py)가 종료코드를 다르게 매길 수 있게 별도
    클래스로 뗀다(코드리뷰 I3). pid 를 속성으로 들고 있어 메시지를 다시
    파싱하지 않아도 된다."""

    def __init__(self, pid: str):
        self.pid = pid
        super().__init__(f"이미 있는 기록: {pid}")


def empty_state() -> dict:
    return {"schema": SCHEMA, "positions": []}


def _price(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise RejectedError(f"가격이 숫자가 아님: {v!r}")
    if isinstance(v, float) and not math.isfinite(v):   # int 는 항상 유한하다 — float 만 검사
        raise RejectedError(f"가격이 유한하지 않음: {v!r}")
    p = round(v)          # 원 단위 정수. 절단(int)이 아니라 반올림 — 계통적 편향 방지
    if p <= 0:
        raise RejectedError(f"가격이 0 이하: {v!r}")
    return p


def _code(v):
    if not isinstance(v, str) or not CODE_RE.match(v):
        raise RejectedError(f"종목코드 형식 오류: {v!r}")
    return v


def _date(v):
    if not isinstance(v, str) or not DATE_RE.match(v):
        raise RejectedError(f"날짜 형식 오류(YYYY-MM-DD): {v!r}")
    try:
        datetime.date.fromisoformat(v)
    except ValueError:
        raise RejectedError(f"존재하지 않는 날짜: {v!r}")
    return v


def _text(v, n, *, default="", strict=False):
    """문자열 필드 하나를 검증한다. strict 면 n자 초과를 자르지 않고 거부한다."""
    if v is None or v == "":
        return default
    if not isinstance(v, str):
        raise RejectedError(f"문자열이 아님: {v!r}")
    if strict and len(v) > n:
        raise RejectedError(f"길이 초과({n}자): {v!r}")
    return v[:n]


def _orders_sane(ords: dict, buys: list) -> bool:
    """저장된 지정가 사다리가 쓸 수 있는 모양인가 — normalize 전용 검사.

    `_price` 를 쓰지 않고 직접 보는 이유: `_price` 는 반올림해서 **고쳐
    돌려준다**. 여기서는 고치면 안 된다 — 저장된 값이 소수라는 것 자체가
    손편집 흔적이고, normalize 의 계약은 "고치지 말고 격리"다
    (buys[0].price 를 다루는 방식과 같다).

    비어 있는 `{}` 는 여기 오지 않는다(호출부가 거른다) — 아직 사다리가
    안 잡힌 정상 기록이다.
    """
    for k in ("buy2", "buy3"):
        v = ords.get(k)
        # bool 은 파이썬에서 int 다 — True 가 1원짜리 주문가로 통과한다.
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            return False
    if ords["buy3"] >= ords["buy2"]:
        return False   # 물타기는 아래로만 간다
    if buys and isinstance(buys[0], dict):
        first = buys[0].get("price")
        if isinstance(first, int) and ords["buy2"] >= first:
            return False   # 2차가 1차보다 높으면 매수 즉시 체결된다
    if "customized" in ords and not isinstance(ords["customized"], bool):
        return False
    return True


def _watch_days(v):
    """지정가 관찰의 기한(거래일 수) — 없으면 기본 WATCH_DAYS_DEFAULT(5),
    있으면 1~60 사이의 진짜 정수만 받는다.

    상한 60 은 "60거래일이면 분 단위로 정확하다"는 보장이 아니다 —
    분봉 재생 창은 약 7거래일뿐이고, 그 뒤로도 autofill 은 일봉만으로
    계속 판정할 수 있지만(분봉이 없으면 그 종목만 건너뛴다) 분 단위
    정밀도를 잃는다. 60 은 그 사실을 인지한 넉넉한 안전 상한일 뿐이다.

    bool 은 파이썬에서 int 의 서브클래스라 `isinstance(True, int)` 가
    참이다 — 명시적으로 막지 않으면 `days: true` 가 1거래일짜리 관찰로
    조용히 통과한다.
    """
    if v is None:
        return WATCH_DAYS_DEFAULT
    if isinstance(v, bool) or not isinstance(v, int):
        raise RejectedError(f"관찰 기간이 정수가 아님: {v!r}")
    if not (1 <= v <= 60):
        raise RejectedError(f"관찰 기간이 범위를 벗어남(1~60): {v!r}")
    return v


def _watch_sane(w) -> bool:
    """저장된 지정가 관찰(watch)이 쓸 수 있는 모양인가 — normalize 전용 검사.

    `_orders_sane` 의 buy2/buy3 검사와 같은 스타일(정수·양수·bool 아님)을
    쓴다 — `watch.price` 는 apply_watch_fill 이 그대로 체결가로 쓰고,
    `watch.days` 는 이 기록이 언제 만료되는지(apply_expire 의 판단 근거)를
    통제한다. 손편집된 값이 조용히 통과하면 전자는 가격을, 후자는
    "영원히 안 만료됨" 같은 사고를 만든다 — `_orders_sane` 옆 주석이 든
    이유와 같다.

    `expired_on`(apply_expire 가 덧붙이는 필드) 은 여기서 검사하지 않는다
    — `_orders_sane` 이 `customized` 를 별도로만 보듯, 이 함수는 만료
    여부와 무관하게 항상 있어야 하는 필드(price/date, 그리고 있다면 days)만 본다.

    **`days` 가 아예 없는 것은 여기서 통과시킨다(CHANGE 2).** `days` 는
    이 브랜치가 새로 만든 필드라, 그 이전에 만들어진 pending/expired
    기록은 `watch` 에 `{price, date}` 두 키만 있고 `days` 자체가 없다.
    그건 "손상"이 아니라 "그때는 없었던 필드"다 — 격리하면 실제로
    대기 중인 주문이 오늘부로 화면과 autofill 에서 통째로 사라진다.
    호출부(normalize)가 이 함수를 통과한 뒤 기본값(WATCH_DAYS_DEFAULT)을
    채워 넣는다. 반대로 `days` 가 **있는데** 모양이 틀리면(0/음수/60초과/
    bool/문자열/소수) 여전히 손편집 흔적이므로 그대로 격리한다 — "없음"과
    "있는데 틀림"을 하나로 합쳐 전부 막거나 전부 통과시키지 말 것. 합치면
    전자는(옛 정상 기록 격리) CHANGE 2 가 고친 배포 사고가 재현되고,
    후자는(손편집된 값이 조용히 기본값으로 둔갑) 이 함수가 존재하는
    이유(만료 통제)가 무너진다.
    """
    if not isinstance(w, dict):
        return False
    price = w.get("price")
    if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
        return False
    try:
        _date(w.get("date"))
    except RejectedError:
        return False
    days = w.get("days")
    if days is not None and (
            isinstance(days, bool) or not isinstance(days, int) or not (1 <= days <= 60)):
        return False
    return True


def _buy_sane(b) -> bool:
    """매수 기록 하나가 쓸 수 있는 모양인가 — normalize 전용 검사.

    `buys[0]`(손입력 관측)과 `buys[1:]`(자동 체결)을 **같은 기준**으로 본다.
    예전에는 [0] 만 봤는데, [1:] 의 가격도 평균가 계산에 그대로 들어가고
    거기서 익절선·손절선이 나온다 — 검증 수준이 다를 이유가 없다.

    실측(2026-08-20): price 키가 없거나 dict 가 아니면 autofill.run 의
    filled_prices() 가 KeyError/TypeError 로 터져 **그날 자동 체결 전체를
    중단**시킨다(그 호출은 네트워크를 감싼 try/except 밖에 있다). 문자열·
    소수·음수 가격은 조용히 평균가를 오염시킨다.

    `_price` 를 그대로 쓰지 않고 결과를 대조하는 이유는 기존 buys[0] 검사와
    같다 — `_price` 는 반올림해서 **고쳐** 돌려주는데, 저장된 값이 소수라는
    것 자체가 손편집 흔적이므로 고치지 말고 격리해야 한다.
    """
    if not isinstance(b, dict):
        return False
    try:
        _date(b.get("date"))
        price_v = b.get("price")
        if _price(price_v) != price_v:
            return False
    except RejectedError:
        return False
    return True


def normalize(raw, dropped=None) -> dict:
    """읽어온 것을 믿지 않는다. 모양이 틀린 항목은 조용히 버리고 dropped 에 기록한다.

    schema 가 있는데 현재 버전과 다르면 절반만 고쳐 쓰지 않고 통째로 거부한다.
    dropped 를 넘기지 않으면(기본값 None) 예전처럼 조용히 격리만 한다.

    최상위 구조 자체가 이상하면(dict 가 아니거나 positions 가 list 가
    아니거나 — 손편집으로 배열을 통째로 붙여넣거나 키 이름을 오타내는 등)
    빈 상태를 돌려주는 건 그대로다. 하지만 그 사실을 dropped 에도 반드시
    남긴다 — 안 남기면 호출자(intake.py)의 "버려진 게 있으면 쓰지 않는다"
    가드가 못 보고 지나쳐서, 기존 항목 전체가 새 항목 하나로 조용히
    덮어써진다(코드리뷰 C1 — 예: positions 배열만 잘라 고친 뒤 파일
    전체인 줄 알고 덮어쓰기).

    schema/positions 이외의 최상위 키(예: cash, updated_at, watchlist —
    아직 아무도 안 쓰지만 손으로 남긴 주석성 필드나 미래 버전이 추가할
    필드일 수 있다)는 검증하지 않되 **보존**한다. position dict 내부의
    낯선 키를 이미 그대로 실어 나르는 기존 정책(각 항목을 deepcopy 해서
    통째로 들고 간다)과 대칭이다 — 이해 못 한다고 지워버리면 손편집이
    유일한 복구 경로인 이 파일에서 사람이 남긴 값이 말없이 사라진다
    (코드리뷰 G2). 단, 이 보존은 schema 와 positions 가 둘 다 유효할 때만
    적용된다 — 최상위 구조 자체가 이상한 앞의 두 조기 return 은 대상이
    아니다. 거기서는 "이게 진짜 데이터인지 오타인지"조차 이 함수가 판단할
    근거가 없다(예: "position"(오타) 키 하나만 있는 파일이 의도된 필드인지
    "positions" 오타인지는 알 수 없다) — 그 경우는 intake.py 의 최상위
    구조 가드가 애초에 이 함수를 부르기 전에 막는다.
    """
    if not isinstance(raw, dict):
        if dropped is not None:
            # 개별 항목 단위로 "무엇을 버렸는지" 말할 수 없는 경우라, 파일
            # 전체를 가리키는 합성 마커를 넣는다. 호출자는 p.get("id") or
            # p.get("code") 로 dropped 항목을 읽으므로 dict 모양을 유지한다.
            dropped.append({"id": "(파일 전체)",
                            "note": f"최상위가 dict 아님: {type(raw).__name__}"})
        return empty_state()
    schema = raw.get("schema")
    if schema is not None and schema != SCHEMA:
        raise RejectedError(f"알 수 없는 schema: {schema!r}")
    items = raw.get("positions")
    if not isinstance(items, list):
        if dropped is not None:
            # 위와 같은 이유. "positions" 키가 없거나(오타) list 가 아니면
            # 실제로는 멀쩡할 수 있는 기존 항목들이 통째로 안 보이게 된다.
            dropped.append({"id": "(파일 전체)",
                            "note": f"positions 가 list 아님: {type(items).__name__}"})
        return empty_state()
    good = []
    for p in items:
        if not isinstance(p, dict):
            if dropped is not None:
                # 호출자(intake.py)는 dropped 항목을 p.get("id") or
                # p.get("code") 로 읽는다 — dict 가 아닌 걸 그대로 넣으면
                # (예: positions 배열 안에 배열이 한 겹 더 들어간 손편집
                # 실수) 그 호출부가 AttributeError 로 죽어서, 의도한
                # "해석 불가 항목 N건 — 파일에 손대지 않는다"(rc=3) 대신
                # 워크플로가 예기치 못한 오류로 떨어진다. dropped 항목은
                # 항상 dict 모양이어야 한다는 불변식(위 "(파일 전체)"
                # 마커에서 이미 지킨 것과 같은 불변식)을 여기서도 지킨다
                # (코드리뷰 G3).
                dropped.append({"id": "(알 수 없음)", "note": f"dict 아닌 항목: {p!r}"})
            continue
        p = copy.deepcopy(p)   # 호출자가 들고 있는 원본 객체를 건드리지 않는다
        try:
            _code(p.get("code"))
        except RejectedError:
            if dropped is not None:
                dropped.append(p)
            continue
        # pending(지정가 관찰)과 expired(그 관찰이 기한을 넘겨 만료됨)는
        # 둘 다 아직 안 산 기록이라 buys 가 비어 있다 — 그걸 손상으로 보고
        # 격리하면 대기 주문/만료 기록이 통째로 사라진다. 반대로 둘 다
        # 아닌데 비어 있으면 여전히 손상이다(얼마에 샀는지조차 모르는 기록).
        never_bought = p.get("status") in (PENDING, EXPIRED)
        buys = p.get("buys")
        if not isinstance(buys, list):
            if dropped is not None:
                dropped.append(p)
            continue
        if not never_bought and not buys:
            if dropped is not None:
                dropped.append(p)
            continue
        # buys[0](손입력 관측)만 보면 buys[1:](자동 체결 — autofill.run 이
        # 매일 덧붙이는 buy2/buy3 기록)이 새는 구멍이 된다. 그 가격도 같은
        # 평균가 계산에 들어가 익절선·손절선을 낳으므로, 리스트 전체를
        # 같은 기준(_buy_sane)으로 본다 — 자세한 이유는 _buy_sane 참조.
        if not all(_buy_sane(b) for b in buys):
            if dropped is not None:
                dropped.append(p)
            continue
        # status 는 setdefault 이전, 원본 그대로 검사한다. dropped 페이로드에 id 등
        # 합성된 키가 섞여 들어가면 "파일에 있던 것"이라는 보고 취지가 깨진다.
        if p.get("status", OPEN) not in (OPEN, CLOSED, PENDING, EXPIRED):   # 거래정지/상장폐지는 시세 쪽 파생 상태이지 여기 값이 아니다
            if dropped is not None:
                dropped.append(p)
            continue
        # watch 는 pending/expired 일 때만 의미가 있다(체결되고 나면
        # apply_watch_fill 이 status 는 OPEN 으로 바꾸지만 watch 필드
        # 자체는 남겨둔다 — "무엇을 지정했었는지"의 기록으로). 이미 체결된
        # 기록의 낡은 watch 는 더 이상 아무 것도 통제하지 않으므로(가격도
        # 기한도 다시 쓰이지 않는다) 여기서 검증하지 않는다 — 검증하면,
        # 이 필드가 생기기 전(days 없이 {price, date} 두 키만 있던 시절)에
        # 이미 체결까지 끝난 옛 기록들이 오늘부로 전부 격리당한다.
        # 반대로 pending/expired 는 watch.price 가 그대로 체결가로 쓰이고
        # (apply_watch_fill) watch.days 가 만료 여부를 가르므로(apply_expire
        # 호출부, autofill.run) 손편집된 값을 여기서 반드시 걸러야 한다 —
        # `_orders_sane` 을 이미 체결된 기록에만 적용하는 것과 대칭이다.
        if never_bought and not _watch_sane(p.get("watch")):
            if dropped is not None:
                dropped.append(p)
            continue
        if never_bought:
            # CHANGE 2 — watch.days 가 이 브랜치 이전엔 없던 필드라, 그때
            # 만들어진 pending/expired 기록은 watch 에 {price, date} 두
            # 키만 있다. 위 _watch_sane 이 "없음"을 이미 손상과 구분해
            # 통과시켰으니, 여기서 기본값을 채운다 — **격리 대신 채움**이다.
            # observed_at/auto/orders 등 다른 선택 필드에 이미 쓰는
            # setdefault 관례와 같은 태도다: normalize() 는 "손상은 격리,
            # 있어야 할 값이 없으면 기본값으로 채운다"이지 "고쳐 쓴다"가
            # 아니다 — days 가 **있는데** 틀린 값(0/음수/60초과/bool/
            # 문자열/소수)은 위에서 이미 격리됐으므로 여기 안 온다. 이
            # 채움을 지우고 다시 격리로 되돌리지 말 것 — 그러면 이 필드
            # 도입 이전의 모든 pending/expired 기록이 하루아침에 화면과
            # autofill 에서 사라지는 배포 사고가 재현된다(지시문 CHANGE 2
            # 가 고치려는 바로 그 사고).
            p["watch"] = {**p["watch"], "days": p["watch"].get("days", WATCH_DAYS_DEFAULT)}
        exits = p.get("exits", [])
        if not isinstance(exits, list):   # buys 와 같은 이유: 있는데 리스트가 아니면 격리
            if dropped is not None:
                dropped.append(p)
            continue
        adjustments = p.get("adjustments", [])
        if not isinstance(adjustments, list):   # 아직 아무도 참조하지 않지만 exits 와 대칭으로 검증한다
            if dropped is not None:
                dropped.append(p)
            continue
        # ── 가상 지정가 주문 필드 (설계 §2) ──────────────────────────────
        # buys/exits 와 같은 태도: 있는데 모양이 틀리면 조용히 고치지 않고
        # 격리한다. 특히 `auto` 는 불리언이 아니면 반드시 막아야 한다 —
        # 문자열 "false" 는 파이썬에서 **참**이라, 예외 지정이 조용히
        # 무시되면 사용자가 막았다고 믿는 종목이 자동 매매된다.
        # ── orders 내용까지 본다 (2026-08-20 리뷰) ──────────────────────
        # buys[0].price 는 소수까지 잡아내면서("손으로 고친 흔적") orders 의
        # 가격은 그냥 통과시키고 있었다. 그런데 그 값은 **같은 돈 계산**에
        # 쓰인다 — orders.replay 가 체결가로 그대로 기록한다.
        #
        # 실측(2026-08-20): 문자열 가격은 replay 에서 TypeError, 키 누락은
        # KeyError 로 **그날 자동 체결 전체를 중단**시킨다(autofill.run 의
        # touched() 가 fetch_minute 의 try/except 밖에 있다). 더 나쁜 건
        # 조용한 쪽 — 1차가보다 높은 사다리를 넣으면 10만원짜리 종목이
        # 58만원에 손절됐다고 기록되고, 음수 사다리는 2차·3차가 영영 안
        # 걸려 손절이 아예 안 켜진다(익절로만 닫혀 승률이 부풀려진다).
        #
        # 쓰기 쪽(apply_orders)이 이미 막지만, normalize 가 지키는 건
        # **손편집된 파일을 읽는 경로**다 — 그게 이 함수의 존재 이유다.
        ords = p.get("orders", {})
        if not isinstance(ords, dict):
            if dropped is not None:
                dropped.append(p)
            continue
        if ords and not _orders_sane(ords, p.get("buys") or []):
            if dropped is not None:
                dropped.append(p)
            continue
        if "auto" in p and not isinstance(p["auto"], bool):
            if dropped is not None:
                dropped.append(p)
            continue
        # pending 은 buys 가 비어 있어 매수일로 id 를 못 만든다 — watch.date 를 쓴다.
        _idbase = (p["buys"][0]["date"] if p.get("buys")
                   else (p.get("watch") or {}).get("date", "0000-00-00"))
        p.setdefault("id", f"{_idbase.replace('-', '')}-{p['code']}")
        p.setdefault("name", p["code"])
        p.setdefault("signal_date", None)
        p.setdefault("exits", [])
        p.setdefault("adjustments", [])
        p.setdefault("status", OPEN)
        p.setdefault("source", "수동")
        p.setdefault("memo", "")
        p.setdefault("orders", {})
        # 옛 기록은 관측 시각을 모른다 — None 이면 그날 15:30 관측으로
        # 간주해 다음 거래일부터 판정한다(설계 §5, autofill.after 가 처리).
        p.setdefault("observed_at", None)
        # 기본은 자동. 예외는 명시적으로 auto:false 를 넣어야만 된다.
        p.setdefault("auto", True)
        good.append(p)
    # schema/positions 이외의 키를 보존한다 — 위 docstring 참조(코드리뷰
    # G2). deepcopy 하는 이유는 position 항목과 같다: 반환값이 raw 의
    # 내부 객체를 그대로 공유하면 안 된다.
    extras = {k: copy.deepcopy(v) for k, v in raw.items() if k not in ("schema", "positions")}
    return {"schema": SCHEMA, "positions": good, **extras}


def apply_buy(state: dict, req: dict) -> dict:
    code = _code(req.get("code"))
    date = _date(req.get("date"))
    price = _price(req.get("price"))
    pid = f"{date.replace('-', '')}-{code}"
    state = normalize(state)
    if any(p["id"] == pid for p in state["positions"]):
        raise AlreadyApplied(pid)
    sig = req.get("signal_date") or None
    if sig:
        sig = _date(sig)
        if sig > date:
            raise RejectedError(f"시그널일이 매수일보다 늦음: signal={sig} buy={date}")
    # 관측 시점에 2차·3차 지정가를 **절대가격으로 확정**한다(설계 §7).
    # 비율로 매번 다시 계산하면, 나중에 1차가를 amend 로 고쳤을 때 이미
    # 체결된 물타기의 근거 가격이 소급해서 바뀐다.
    ladder = {**_orders.plan(price), "customized": False}
    # 여기서 만든 것을 normalize 가 격리하면 최악이다 — 쓰기는 성공하는데
    # 다음 읽기에서 그 기록이 사라져 손편집으로만 복구된다. 실측
    # (2026-08-20): 1차가 12원 이하면 반올림 때문에 buy2 >= 1차가 이거나
    # buy3 >= buy2 가 되어 _orders_sane 을 통과하지 못한다. 그런 종목은
    # 문 앞에서 거부한다.
    if not _orders_sane(ladder, [{"date": date, "price": price}]):
        raise RejectedError(
            f"1차가가 너무 낮아 지정가 사다리를 만들 수 없음: {price}원")
    state["positions"].append({
        "id": pid,
        "code": code,
        "name": _text(req.get("name"), 40, default=code),
        "source": _text(req.get("source"), 20, default="수동", strict=True),
        "signal_date": sig,
        "buys": [{"date": date, "price": price}],
        "exits": [],
        "adjustments": [],
        "status": OPEN,
        "orders": ladder,
        "observed_at": _text(req.get("observed_at"), 20, default="") or None,
        "auto": True,
        "memo": _text(req.get("memo"), 200, default=""),
    })
    return state


def apply_watch(state: dict, req: dict) -> dict:
    """지정가 관찰 — 그 가격에 닿을 때 1차 매수가 체결되는 대기 기록.

    아직 아무것도 안 샀으므로 `buys` 는 비어 있고 `status` 는 "pending"
    이다. 체결되면 apply_watch_fill 이 1차 매수로 바꾸고 그 시점에
    2차·3차 지정가를 확정한다(설계 §7).

    "며칠 이내에 N원에 닿으면 자동 매수" — `days`(거래일 수, 기본 WATCH_DAYS_DEFAULT=5)가
    그 "며칠 이내에"다. 기한은 여기서 계산하지 않는다 — `watch.date` 와
    `watch.days` 를 그대로 저장해두고, 매일 판정은 autofill.run 이
    trading_calendar.watch_deadline 으로 한다(달력일이 아니라 거래일로
    세야 하므로, 이 함수 시점엔 아직 그 뒤로 며칠이 거래일인지 알 수
    없다 — 판정을 미루는 게 아니라 애초에 여기서 할 수 있는 계산이
    아니다).
    """
    code = _code(req.get("code"))
    date = _date(req.get("date"))
    price = _price(req.get("price"))
    days = _watch_days(req.get("days"))
    # 체결 시점에 만들 사다리가 normalize 를 통과 못 하면, 체결은 되는데
    # 그 기록이 다음 읽기에서 사라진다(apply_buy 와 같은 위험). 여기서 막는다.
    if not _orders_sane({**_orders.plan(price), "customized": False},
                        [{"date": date, "price": price}]):
        raise RejectedError(f"목표가가 너무 낮아 지정가 사다리를 만들 수 없음: {price}원")
    pid = f"{date.replace('-', '')}-{code}"
    state = normalize(state)
    if any(p["id"] == pid for p in state["positions"]):
        raise AlreadyApplied(pid)
    state["positions"].append({
        "id": pid, "code": code,
        "name": _text(req.get("name"), 40, default=code),
        "source": _text(req.get("source"), 20, default="수동", strict=True),
        "signal_date": None,
        "buys": [], "exits": [], "adjustments": [],
        "status": PENDING,
        "watch": {"price": price, "date": date, "days": days},
        "orders": {}, "observed_at": None, "auto": True,
        "memo": _text(req.get("memo"), 200, default=""),
    })
    return state


def apply_watch_fill(state: dict, pid: str, day: str, t: str) -> dict:
    """대기 주문이 체결됐다 — 1차 매수로 바꾸고 2차·3차를 확정한다.

    `observed_at` 을 체결 시각으로 둔다. 이 기록의 "관측"은 지정가에 닿은
    그 순간이므로, 이후 재생은 거기서부터 시작해야 맞다(설계 §5) — 같은
    실행에서 곧바로 이어지는 물타기·익절 판정이 체결 이전 분봉을 보면
    안 된다.
    """
    state = normalize(state)
    match = next((p for p in state["positions"] if p["id"] == pid), None)
    if match is None:
        raise RejectedError(f"대상 없음: {pid!r}")
    if match["status"] != PENDING:
        raise RejectedError(f"대기 상태가 아님: {pid!r}")
    price = _price(match["watch"]["price"])
    match["buys"] = [{"date": _date(day), "price": price,
                      "kind": "buy1", "t": t, "auto": True}]
    match["orders"] = {**_orders.plan(price), "customized": False}
    match["observed_at"] = f"{day}T{t[8:10]}:{t[10:12]}"
    match["status"] = OPEN
    return state


def apply_expire(state: dict, pid: str, day: str) -> dict:
    """대기 주문이 기한(watch.days 거래일)을 넘겨 안 닿았다 — 매수 없이
    끝난다.

    "이 스크리너의 신호가 목표가에 안 닿았다"는 그 자체로 유효한 결과다
    (지시문 결정 4) — 지우면 스크리너 비교가 그 실패를 못 본 척하게
    된다. 그래서 지우지 않고 `status` 만 EXPIRED 로 바꾼다. `buys` 는
    계속 비어 있다(끝내 안 샀다) — 화면(rows())이 이 상태를 승률·평균
    수익률·미결 어디에도 안 들어가게 따로 뺀다.

    `watch.expired_on` 에 만료가 확정된 날짜를 남긴다 — price/date/days
    는 그대로 둔다(무엇을 노렸다가 놓쳤는지가 계속 읽혀야 한다). 이
    함수를 부르는 쪽(autofill.run)에게 "만료도 쓰기"라는 사실을 그대로
    노출한다 — 그래야 그 실패가 다른 쓰기 실패와 같은 problems 경로로 들어간다.
    """
    state = normalize(state)
    match = next((p for p in state["positions"] if p["id"] == pid), None)
    if match is None:
        raise RejectedError(f"대상 없음: {pid!r}")
    if match["status"] != PENDING:
        raise RejectedError(f"대기 상태가 아님: {pid!r}")
    match["watch"] = {**match["watch"], "expired_on": _date(day)}
    match["status"] = EXPIRED
    return state


def apply_sell(state: dict, req: dict) -> dict:
    code = _code(req.get("code"))
    date = _date(req.get("date"))
    price = _price(req.get("price"))
    state = normalize(state)
    opens = [p for p in state["positions"] if p["code"] == code and p["status"] == OPEN]
    if not opens:
        raise RejectedError(f"보유 중이 아님: {code}")
    # 오래된 것부터 종결한다. 동일 종목·동일 매수일 동시보유는 apply_buy 가 id 중복으로
    # 막으므로 날짜가 같아 순위가 갈리는 경우는 도달 불가하다. 그래도 수기 편집으로
    # 생기면 file order(=positions 리스트 순서)가 이긴다 — 결정적 동작을 보장하기 위함.
    target = min(opens, key=lambda p: p["buys"][0]["date"])
    buy_date = target["buys"][0]["date"]
    if date < buy_date:
        raise RejectedError(f"매도일이 매수일보다 이름: sell={date} buy={buy_date}")
    target["exits"].append({
        "date": date, "price": price, "reason": _text(req.get("reason"), 40, default="")})
    target["status"] = CLOSED
    return state


def _target(state: dict, req: dict):
    """id + was 로 기록 하나를 지목한다 — apply_amend 와 같은 계약.

    `was`(코드) 대조가 없으면 페이지가 낡은 목록을 들고 있을 때 엉뚱한
    기록을 고칠 수 있다(apply_amend docstring 의 id 재사용 경로 참조).
    """
    pid = req.get("id")
    match = next((p for p in state["positions"] if p["id"] == pid), None)
    if match is None:
        raise RejectedError(f"대상 없음: {pid!r}")
    if match["code"] != req.get("was"):
        raise RejectedError(
            f"코드 불일치(was): 저장={match['code']!r} 요청={req.get('was')!r}")
    return match


def apply_orders(state: dict, req: dict) -> dict:
    """2차·3차 지정가를 직접 지정한다. `customized: true` 가 남는다.

    표시를 남기는 이유: 통계에서 "규칙대로 굴린 기록"과 "손본 기록"을
    갈라 봐야 한다(설계 §7). 안 그러면 나중에 "이 스크리너가 난 건가 내가
    손봐서 난 건가"를 구분할 수 없다.

    검증은 `_orders_sane` 과 **같은 규칙**이어야 한다 — 여기서 통과시킨
    값을 normalize 가 격리하면 저장은 되는데 못 읽는 기록이 생긴다.
    """
    state = normalize(state)
    match = _target(state, req)
    if not match["buys"]:
        raise RejectedError(f"아직 매수 전이라 주문가를 못 잡음: {match['id']!r}")
    first = match["buys"][0]["price"]
    buy2 = _price(req.get("buy2"))
    buy3 = _price(req.get("buy3"))
    # 물타기는 아래로만 간다. 위로 잡으면 매수 즉시 체결되어 "물타기"가
    # 아니라 그냥 같은 가격에 세 번 산 기록이 된다.
    if buy2 >= first:
        raise RejectedError(f"2차가가 1차가보다 높음: {buy2} >= {first}")
    if buy3 >= buy2:
        raise RejectedError(f"3차가가 2차가보다 높음: {buy3} >= {buy2}")
    new = {"buy2": buy2, "buy3": buy3, "customized": True}
    if match.get("orders") == new:
        raise AlreadyApplied(match["id"])
    match["orders"] = new
    return state


def apply_auto(state: dict, req: dict) -> dict:
    """자동 예외 토글. `auto: false` 면 이 종목은 전부 수동이 된다.

    자동매도뿐 아니라 자동매수(2차·3차)도 같이 멈춘다(설계 §8) — 손절은
    거부하면서 물은 자동으로 타는 어중간한 상태를 만들지 않는다.
    """
    state = normalize(state)
    match = _target(state, req)
    v = req.get("auto")
    if not isinstance(v, bool):
        # 문자열 "false" 는 파이썬에서 참이다 — 조용히 통과시키면 사용자가
        # 막았다고 믿는 종목이 자동 매매된다.
        raise RejectedError(f"auto 가 불리언이 아님: {v!r}")
    if match.get("auto", True) == v:
        raise AlreadyApplied(match["id"])
    match["auto"] = v
    return state


# amend 값 필드 화이트리스트(F1). 값 필드가 전부 선택(패치니까)이라, 오타난
# 키는 검증할 대상 자체가 없어 조용히 무시되고 "아무것도 안 바뀜" →
# AlreadyApplied(rc=4) 로 끝난다 — 가장 흔한 실수(buy:{...} 중첩을 깜빡하고
# 최상위에 price 를 적는 것)가 "이미 반영되어 있습니다"로 조용히 닫혀서
# 사용자가 파일이 이미 맞다고 믿고 손편집으로 돌아가게 만든다. amend 가
# 없애려는 바로 그 루프라 buy/sell 처럼 "필수 필드 없으면 크게 거부"가 안
# 통하는 이 연산에서는 화이트리스트로 대신 막는다. extract() 가 이미
# "json 블록이 여럿이면 추측하지 않고 거부"하는 태도를 취하고 있어서
# 일관적이다.
_AMEND_FIELDS = frozenset({
    "op", "id", "was", "was_price", "code", "name", "source", "memo",
    "signal_date", "buy", "exit", "observed_at"})
_AMEND_BUY_FIELDS = frozenset({"price", "date"})
_AMEND_EXIT_FIELDS = frozenset({"price", "date", "reason"})


def apply_amend(state: dict, req: dict, changed_id: list | None = None) -> dict:
    """기존 기록 하나를 고친다 — **패치**다, 교체가 아니다(Task 15, 구현계획.md).

    페이로드에 없는 키는 안 바뀐다. `exits` 를 언급하지 않으면 `exits` 는
    그대로 남는다 — 교체로 만들면 매도 기록이 통째로 사라지는 경로가 생긴다.

    `changed_id` 에 빈 리스트를 넘기면 반영 후 이 기록의 최종 `id` 를
    담아준다 — intake.py 가 커밋 메시지를 조립할 때 "무엇이 바뀌었는지"를
    상태 리스트 앞뒤를 비교해 추측하지 않고 이 채널로 직접 받게 하기
    위함이다(`normalize(raw, dropped=None)` 의 out-parameter 관례와 같다).

    설계 그대로 지키는 규칙:
    1. `was` 가 대상 기록의 **현재** `code` 와 다르면 거부한다. `id` 만으로
       지목하면 페이지가 낡은 목록을 들고 있을 때(또는 이슈를 열어두고
       나중에 제출할 때) 엉뚱한 기록을 고칠 수 있다.
    2. `id` 는 (매입일+코드) 로 재계산한다. 새 `id` 가 자신이 아닌 다른
       기록의 것과 겹치면 거부한다(중복 생성 금지).
    3. `exit` 는 이미 `exits` 가 있는(=종결된) 기록에만 줄 수 있다 —
       `amend` 로 매도를 새로 만들지 않는다. 그건 `sell` 의 일이다.
    4. 정규화된 값까지 비교해서 아무것도 안 바뀌면 `AlreadyApplied` —
       빈 커밋을 만들지 않는다. "247500" 과 "247500.0" 처럼 `_price` 가
       정규화하면 같아지는 값은 "바뀐 것"으로 치지 않는다.
    5. 값 검증은 `buy`/`sell` 과 완전히 같은 헬퍼(`_code`/`_date`/`_price`/
       `_text`)를 쓴다. `amend` 만 느슨하면 가드를 우회하는 뒷문이 된다.

    설계 문서에 없어서 이 구현이 코드리뷰로 추가한 것들:
    - **모르는 필드는 거부한다** (`_AMEND_FIELDS` 화이트리스트, `buy`/`exit`
      내부도 각각 `_AMEND_BUY_FIELDS`/`_AMEND_EXIT_FIELDS` 로). 이유는 위
      모듈 상수 옆 주석 참조 — "조용히 무시 → 이미 반영됨(rc=4)"이 손편집
      복귀 루프로 이어지는 걸 막는다.
    - `code` 를 고치면서 `name` 을 안 주면 거부한다. 안 그러면 종목만
      바뀌고 표시 이름은 이전 종목 이름으로 남아 기록이 거짓말을 한다.
    - 패치를 전부 적용한 뒤, 최종 매수일이 최종 매도일보다 늦으면 거부한다
      — `apply_sell` 이 매도 **시점**에 지키는 순서를, amend 가 나중에
      `buy.date`/`exit.date` 를 따로 옮겨 우회하지 못하게 한다.
    - **저장된 값 자체가 손상됐는지도 확인한다.** `normalize()` 는 `exits`
      가 *list 인지* 만 보고 원소 모양은 안 보며, `signal_date` 는 아예
      검사하지 않는다(있으면 손 안 댐). `apply_buy`/`apply_sell` 은 저장된
      이 두 필드를 읽지 않아 지금까지 드러나지 않았던 노출인데, amend 는
      이 값들을 이번 요청이 건드리든 안 건드리든(메모만 고치는 요청이라도)
      항상 순서 비교에 쓴다 — 손편집이 심어놓은 손상(문자열 원소, `date`
      키 없는 exits 항목, 숫자 `signal_date` 등)이 그대로면 `TypeError`/
      `KeyError` 가 새어나가 intake.py 의 에러 계약(2/3/4)을 벗어난다.
      구조적으로는 `normalize()` 가 이걸 `dropped` 로 걸러 모든 연산에서
      rc=3 이 되게 하는 게 더 정확한 자리다(이미 하는 "exits 가 list 인지"
      검사와 대칭) — 하지만 그건 기존 동작을 바꾸는 더 큰 변경이라 이번
      병합에는 안 담는다. 여기서는 amend 가 실제로 읽는 값만 지역적으로,
      `RejectedError`(rc=2)로 막는다.
    - **`was_price`(선택).** `id` 는 `YYYYMMDD-코드` 라서 `match["code"]`
      는 사실 `id` 접미사 그 자체다 — `was` 단독으로는 "같은 코드, 다른
      날짜에 산 기록"을 구분 못 한다. 구체적으로: 어떤 기록의 `buy.date`
      를 amend 로 옮기면 옛 (날짜+코드) 조합의 id 가 비고, 그 뒤 같은
      코드로 정말 새 매수가 그 정확한 조합을 다시 채우면, 그 사이 떠 있던
      낡은 amend 이슈(옛 id 를 겨눈)가 제출됐을 때 `was`(코드) 는 여전히
      일치해서 **엉뚱한(새) 기록을 고치는 사고**로 이어진다(실측 재현됨).
      `id` 로부터 유도되지 않는 값(매입가)을 선택 필드로 받아 저장값과
      대조하면 이 재사용 사고를 실용적으로 막는다 — 새 매수가 우연히
      같은 코드+날짜+가격을 전부 재현할 확률은 사실상 없다. 안 보내도
      (손으로 쓴 페이로드) 여전히 동작한다 — 페이지(가격을 이미 렌더링해서
      알고 있다)는 항상 보내야 한다.

    `signal_date` 도 최상위 키로 고칠 수 있다 — 설계 페이로드 예시에는
    없지만, 매수 시 검증하는 필드를 amend 로는 못 고치는 게 오히려
    비대칭이라 넣었다. `apply_buy` 와 같은 규칙(매수일보다 늦으면 거부)을
    그대로 적용한다.

    `adjustments` 는 건드리지 않는다 — 지금 이 필드를 쓰는 쪽이 없고
    (아무도 안 씀), 페이지도 이 필드가 있는 기록은 가격 파생값 계산 자체를
    건너뛴다. amend 페이로드에 이 필드의 모양이 정의돼 있지 않은데 여기서
    임의로 스키마를 만들면 아무도 합의하지 않은 걸 새로 만드는 셈이다.

    ── 이 연산이 못 고치는 것(잔여 한계) ──────────────────────────────────
    - `status` 는 amend 로 못 바꾼다. `exits` 도 amend 로 새로 못 만들고
      (그건 `sell` 의 일) 못 지운다. 그래서 app.js 가 이미 가정하고 있는
      두 불일치 상태 — `status="closed"` 인데 `exits=[]`, 그리고 `exits`
      는 있는데 `status="open"` — 는 여전히 손편집으로만 고칠 수 있다.
      완전히 스푸리어스한(있어서는 안 될) 기록을 지우는 것도 마찬가지다.
      즉 amend 는 "손편집이 완전히 사라졌다"를 보장하지 않는다 — 가장
      흔한 사고(값 오타)만 없앤다.
    - `was_price` 는 id 재사용 사고의 실용적인 확률을 낮추지만 구조적으로
      0 은 아니다(우연히 같은 코드+날짜+가격의 새 매수가 있으면 뚫린다).
    - 매도일 순서 가드는 `exits[0]` 만 본다. 정상 경로는 `buys`/`exits`
      모두 원소가 최대 1개라 문제없지만, 손편집으로 exits 가 여러 개면
      (지금 어떤 연산도 만들 수 없는 모양) 재정렬을 놓칠 수 있다 — v1
      범위 밖으로 남겨둔다.
    - "exit 는 종결된 기록에만" 을 판단할 때 `status` 가 아니라 `exits` 가
      비었는지로 판단한다. 정상 경로에선 둘이 항상 같이 바뀌어(apply_sell)
      차이가 없다. `status` 기준으로 바꾸면 `status="closed"` 인데
      `exits=[]` 인 손편집 기록에서 `new["exits"][0]` 이 없어 IndexError
      가 나므로, "패치할 exits[0] 이 실제로 있는가"를 보는 지금 기준을
      의도적으로 유지한다.
    """
    unknown = set(req) - _AMEND_FIELDS
    if unknown:
        raise RejectedError(f"모르는 필드: {sorted(unknown)}")

    target_id = req.get("id")
    was = req.get("was")
    was_price = req.get("was_price")
    state = normalize(state)
    matches = [i for i, p in enumerate(state["positions"]) if p["id"] == target_id]
    if not matches:
        raise RejectedError(f"고칠 대상 없음: {target_id!r}")
    if len(matches) > 1:
        # 정상 경로로는 절대 안 생긴다 — id 유일성은 이 함수(충돌 검사)와
        # apply_buy(중복 id 거부)가 항상 지킨다. 손편집으로 두 기록이 같은
        # id 를 갖게 됐다면 "먼저 찾은 걸 고친다"는 조용한 오동작 대신
        # 드러나게 거부한다(파일이 이미 손상됐다는 신호이기도 하다).
        raise RejectedError(f"id 가 중복 저장되어 있어 고칠 수 없음(파일 손상 의심): {target_id!r}")
    idx = matches[0]
    match = state["positions"][idx]
    if match["code"] != was:
        raise RejectedError(
            f"코드 불일치(was) — 저장된 값과 다름: 저장={match['code']!r} 요청={was!r}")
    if was_price is not None:
        try:
            was_price_norm = _price(was_price)
        except RejectedError as exc:
            raise RejectedError(f"was_price 형식 오류: {exc}") from exc
        if was_price_norm != match["buys"][0]["price"]:
            raise RejectedError(
                "매입가 불일치(was_price) — 저장된 값과 다름: "
                f"저장={match['buys'][0]['price']!r} 요청={was_price_norm!r}")

    # 저장된 exits/signal_date 자체가 손상됐는지 확인한다(F2) — 위 docstring
    # "저장된 값 자체가 손상됐는지도 확인한다" 참조. 이 요청이 exit/
    # signal_date 를 안 건드려도 아래 순서 비교가 항상 이 값들을 읽는다.
    for e in match["exits"]:
        if not isinstance(e, dict):
            raise RejectedError(f"저장된 exits 항목이 손상됨(dict 아님): {e!r}")
        try:
            _date(e.get("date"))
            _price(e.get("price"))
        except RejectedError as exc:
            raise RejectedError(f"저장된 exits 항목이 손상됨: {exc}") from exc
    if match["signal_date"] is not None:
        try:
            _date(match["signal_date"])
        except RejectedError as exc:
            raise RejectedError(f"저장된 signal_date 가 손상됨: {exc}") from exc

    if "code" in req and "name" not in req:
        # 패치 규칙을 곧이곧대로 따르면 code 만 바뀌고 name 은 이전 종목
        # 이름으로 남는다 — "고친다"는 취지에 어긋나는 거짓 기록이 된다.
        raise RejectedError("code 를 고치려면 name 도 함께 줘야 함 — 이름이 낡은 채로 남는다")

    new = copy.deepcopy(match)   # match(=state 내부 참조)를 직접 건드리지 않는다

    if "code" in req:
        new["code"] = _code(req["code"])
    if "name" in req:
        new["name"] = _text(req.get("name"), 40, default=new["code"])
    if "source" in req:
        new["source"] = _text(req.get("source"), 20, default="수동", strict=True)
    if "memo" in req:
        new["memo"] = _text(req.get("memo"), 200, default="")
    if "signal_date" in req:
        sig = req.get("signal_date") or None
        new["signal_date"] = _date(sig) if sig else None
    if "observed_at" in req:
        new["observed_at"] = _text(req.get("observed_at"), 20, default="") or None

    buy_patch = req.get("buy")
    if buy_patch is not None:
        if not isinstance(buy_patch, dict):
            raise RejectedError(f"buy 가 객체가 아님: {buy_patch!r}")
        unknown_buy = set(buy_patch) - _AMEND_BUY_FIELDS
        if unknown_buy:
            raise RejectedError(f"buy 안에 모르는 필드: {sorted(unknown_buy)}")
        if "price" in buy_patch:
            new["buys"][0]["price"] = _price(buy_patch["price"])
        if "date" in buy_patch:
            new["buys"][0]["date"] = _date(buy_patch["date"])

    exit_patch = req.get("exit")
    if exit_patch is not None:
        if not isinstance(exit_patch, dict):
            raise RejectedError(f"exit 가 객체가 아님: {exit_patch!r}")
        unknown_exit = set(exit_patch) - _AMEND_EXIT_FIELDS
        if unknown_exit:
            raise RejectedError(f"exit 안에 모르는 필드: {sorted(unknown_exit)}")
        if not new["exits"]:
            raise RejectedError("종결되지 않은 기록에는 exit 를 줄 수 없음 — 매도는 sell 의 일")
        if "price" in exit_patch:
            new["exits"][0]["price"] = _price(exit_patch["price"])
        if "date" in exit_patch:
            new["exits"][0]["date"] = _date(exit_patch["date"])
        if "reason" in exit_patch:
            new["exits"][0]["reason"] = _text(exit_patch.get("reason"), 40, default="")

    buy_date = new["buys"][0]["date"]
    if new["signal_date"] and new["signal_date"] > buy_date:
        raise RejectedError(
            f"시그널일이 매수일보다 늦음: signal={new['signal_date']} buy={buy_date}")
    if new["exits"] and new["exits"][0]["date"] < buy_date:
        raise RejectedError(
            f"매도일이 매수일보다 이름: sell={new['exits'][0]['date']} buy={buy_date}")

    new_id = f"{buy_date.replace('-', '')}-{new['code']}"
    if new_id != match["id"] and any(
            p["id"] == new_id for i, p in enumerate(state["positions"]) if i != idx):
        raise RejectedError(f"이미 있는 id 로 바뀜(중복 생성 금지): {new_id!r}")
    new["id"] = new_id

    if new == match:
        raise AlreadyApplied(match["id"])

    state["positions"][idx] = new
    if changed_id is not None:
        changed_id.append(new["id"])
    return state


def apply_delete(state: dict, req: dict) -> dict:
    """기록 하나를 완전히 지운다 — 이 시스템에서 **유일한 파괴적 연산**이다.

    지금까지 스퍼리어스한(있어서는 안 될) 기록을 지우는 유일한 경로는
    손편집이었다(apply_amend 독스트링의 "잔여 한계" 참조) — 이 함수가
    처음으로 그걸 정식 연산으로 만든다.

    페이로드: `{"op": "delete", "id": ..., "was": <code>, "was_price": <int>}`

    대상은 `_target()` 으로 고른다(id + was 코드 대조) — apply_orders/
    apply_auto 와 계약이 같고, 여기서 두 번째 조회를 새로 만들지 않는다.

    **`was_price` 는 여기서 필수다 — `apply_amend` 는 선택으로 둔다.**
    `id` 는 `날짜+코드` 라서, `was`(코드) 대조는 사실 id 자신의 접미사를
    다시 확인하는 것뿐이라 단독으로는 약하다(apply_amend 독스트링의 id
    재사용 경로 참조). 구체적으로: 어떤 기록의 `buy.date` 가 amend 로
    옮겨지면 옛 (날짜+코드) id 가 비고, 그 자리를 정말 새 매수가 다시
    채우면, 그 사이 떠 있던 낡은 delete 요청(옛 id 를 겨눈)이 `was` 만으로
    통과해 **엉뚱한(새) 기록을 지워버릴 수 있다.** `apply_amend` 는 이
    위험을 문서화하고도 `was_price` 를 선택으로 둔다 — 잘못 고쳐도
    되돌릴 수 있으니까(다시 amend 하면 된다). 삭제는 되돌릴 수 없다 —
    지워진 값 자체가 사라진다. 그래서 amend 와 같은 위험을 여기서는
    감수하지 않고 `was_price` 를 강제한다.

    대조할 가격의 출처는 기록의 모양에 따라 다르다:
      - 정상 기록(매수가 있음, buys 가 비어있지 않음) → `buys[0]["price"]`.
      - `pending`/`expired`(아직 안 샀거나 끝내 안 산 기록, buys 가 계속
        비어 있다) → `watch["price"]` — 이 두 상태엔 "매입가" 자체가 없다
        (목표가만 있다).

    지운다는 건 `state["positions"]` 배열에서 완전히 빼는 것이다 —
    tombstone(예: `status: "deleted"`)을 남기지 않는다. 남기면 그 행이
    화면 표(보유/종결)와 통계 필터(승률·평균수익률·미결 집계 등) 어디에도
    안 맞아 영원히 특수 케이스를 만든다 — 사용자가 원한 건 "지우기"이지
    "숨기고 표시만 남기기"가 아니다.

    대상이 없으면 `RejectedError`. **`AlreadyApplied` 는 없다** — 이미
    지워진 것을 다시 지우는 요청과 애초에 없던 것을 지우는 요청은 이
    함수 입장에서 구분할 방법이 없다(둘 다 "id 를 못 찾음"으로 온다).
    다른 연산들의 `AlreadyApplied`(orders/auto/amend)는 "다시 보내도
    안전하다"(재제출이 실수로 두 번 가도 결과가 같다)는 게 전제인데,
    삭제에는 그 전제가 없다 — 엉뚱한 id 로 잘못 보낸 삭제 요청도 조용히
    "이미 처리됨"으로 넘기면 그 실수를 알아챌 방법이 사라진다.
    """
    was_price = req.get("was_price")
    if was_price is None:
        raise RejectedError(
            "was_price 가 필요함 — 삭제는 되돌릴 수 없어 amend 보다 엄격하게 대조한다")
    try:
        was_price_norm = _price(was_price)
    except RejectedError as exc:
        raise RejectedError(f"was_price 형식 오류: {exc}") from exc

    state = normalize(state)
    match = _target(state, req)

    # 정상 기록은 buys[0].price, pending/expired 는 watch.price 로 대조한다
    # — 이 두 상태는 아직 안 샀거나 끝내 안 사서 "매입가" 개념 자체가 없다.
    stored_price = (match["watch"]["price"] if match["status"] in (PENDING, EXPIRED)
                    else match["buys"][0]["price"])
    if was_price_norm != stored_price:
        raise RejectedError(
            "매입가 불일치(was_price) — 저장된 값과 다름: "
            f"저장={stored_price!r} 요청={was_price_norm!r}")

    state["positions"] = [p for p in state["positions"] if p["id"] != match["id"]]
    return state


# 체결 종류 → exits.reason 에 남길 한글 라벨. 화면은 이 문자열로 자동/수동을
# 구분하지 않는다(exits[].auto 를 본다) — 라벨은 사람이 읽기 위한 것이다.
_FILL_REASON = {"take_profit": "자동익절", "stop_loss": "자동손절"}


def apply_fills(state: dict, pid: str, fills: list, day: str,
                minute_verified: bool = True) -> dict:
    """분봉 재생(orders.replay)의 결과를 기록 하나에 반영한다.

    `fills` 는 **발생 순서대로** 온다. 갭하락으로 같은 분에 2차·3차·손절이
    한꺼번에 나는 경우(설계 §4-1)를 그 순서 그대로 기록한다 — 나중에
    "왜 하루에 세 건이 찍혔나"를 읽을 수 있어야 한다.

    체결이 하나도 없으면 `AlreadyApplied` — 빈 커밋을 만들지 않는다
    (apply_amend 와 같은 계약).

    `minute_verified=False` 는 분봉 창(약 7거래일)을 넘겨 일봉으로만
    판정한 경우다(설계 §9). 그날 손절선·익절선을 둘 다 스쳤다면 순서를
    알 수 없어 **손절로 기록**하는데(승률을 부풀리지 않는 쪽), 그 사실을
    이 플래그로 남겨 통계에서 걸러 볼 수 있게 한다.

    `weighting` 을 매도 기록에 함께 저장한다 — 지금은 항상 "shares"
    (동일 수량 가정)지만, 나중에 "amount"(동일 금액, 조화평균)로 바꿔도
    **이미 체결된 과거 기록의 평균가가 소급해서 바뀌면 안 되기** 때문이다
    (설계 §3).
    """
    state = normalize(state)
    match = next((p for p in state["positions"] if p["id"] == pid), None)
    if match is None:
        raise RejectedError(f"대상 없음: {pid!r}")
    if not match.get("auto", True):
        # autofill 이 이미 걸러야 하지만 여기서도 막는다 — 예외는 사용자가
        # "이 종목은 건드리지 마라"고 한 것이라 이중으로 지킨다.
        raise RejectedError(f"자동 예외로 지정된 기록: {pid!r}")
    if match["status"] == CLOSED or match["exits"]:
        raise RejectedError(f"이미 종결된 기록: {pid!r}")
    if not fills:
        raise AlreadyApplied(pid)

    for f in fills:
        kind = f["kind"]
        price = _price(f["price"])
        if kind in ("buy2", "buy3"):
            match["buys"].append({"date": _date(day), "price": price,
                                  "kind": kind, "t": f["t"], "auto": True})
        elif kind in _FILL_REASON:
            match["exits"].append({
                "date": _date(day), "price": price,
                "reason": _FILL_REASON[kind], "t": f["t"], "auto": True,
                "session": "KRX",          # 설계 §6 — 지금은 상수, 확장 대비
                "weighting": "shares",     # 설계 §3 — 소급 변경 방지
                "minute_verified": minute_verified})
            match["status"] = CLOSED
            break   # 닫힌 뒤의 체결은 없다(replay 도 거기서 멈춘다)
        else:
            raise RejectedError(f"모르는 체결 종류: {kind!r}")
    return state
