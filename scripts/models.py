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
OPEN, CLOSED = "open", "closed"


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
        buys = p.get("buys")
        if not isinstance(buys, list) or not buys or not isinstance(buys[0], dict):
            if dropped is not None:
                dropped.append(p)
            continue
        try:
            _date(buys[0].get("date"))
            price_v = buys[0].get("price")
            if _price(price_v) != price_v:   # 저장값은 반올림해도 그대로여야 한다 — 소수는 손으로 고친 흔적
                raise RejectedError(f"저장된 가격이 정수가 아님: {price_v!r}")
        except RejectedError:
            if dropped is not None:
                dropped.append(p)
            continue
        # status 는 setdefault 이전, 원본 그대로 검사한다. dropped 페이로드에 id 등
        # 합성된 키가 섞여 들어가면 "파일에 있던 것"이라는 보고 취지가 깨진다.
        if p.get("status", OPEN) not in (OPEN, CLOSED):   # 거래정지/상장폐지는 시세 쪽 파생 상태이지 여기 값이 아니다
            if dropped is not None:
                dropped.append(p)
            continue
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
        p.setdefault("id", f"{p['buys'][0]['date'].replace('-', '')}-{p['code']}")
        p.setdefault("name", p["code"])
        p.setdefault("signal_date", None)
        p.setdefault("exits", [])
        p.setdefault("adjustments", [])
        p.setdefault("status", OPEN)
        p.setdefault("source", "수동")
        p.setdefault("memo", "")
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
        "memo": _text(req.get("memo"), 200, default=""),
    })
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


def apply_amend(state: dict, req: dict) -> dict:
    """기존 기록 하나를 고친다 — **패치**다, 교체가 아니다(Task 15, 구현계획.md).

    페이로드에 없는 키는 안 바뀐다. `exits` 를 언급하지 않으면 `exits` 는
    그대로 남는다 — 교체로 만들면 매도 기록이 통째로 사라지는 경로가 생긴다.

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
       정규화하면 같아지는 값은 "바뀐 것"으로 치지 않는다 — 비교를
       패치 **적용 전 JSON** 이 아니라 **적용 후 정규화된 필드**로 하기
       때문에 저절로 이렇게 된다.
    5. 값 검증은 `buy`/`sell` 과 완전히 같은 헬퍼(`_code`/`_date`/`_price`/
       `_text`)를 쓴다. `amend` 만 느슨하면 가드를 우회하는 뒷문이 된다.

    설계 문서에 없어서 이 구현이 코드리뷰로 추가한 두 가지:
    - `code` 를 고치면서 `name` 을 안 주면 거부한다. 패치 규칙(1)을 곧이
      곧대로 따르면 종목만 바뀌고 표시 이름은 이전 종목 이름으로 남는데,
      그건 기록이 거짓말을 하는 것과 같다 — "고친다"는 취지에 어긋난다.
    - 패치를 전부 적용한 뒤, 최종 매수일이 최종 매도일보다 늦으면 거부한다.
      `apply_sell` 은 매도 **시점**에 이 순서를 지키지만, `amend` 가 나중에
      `buy.date` 나 `exit.date` 를 따로 옮기면 그 가드를 건너뛸 수 있다 —
      같은 불변식을 여기서도 지킨다.

    `signal_date` 도 최상위 키로 고칠 수 있다 — 설계 페이로드 예시에는
    없지만, 매수 시 검증하는 필드(코드리뷰로 지적된 gap)를 amend 로는
    못 고치는 게 오히려 비대칭이라 넣었다. `apply_buy` 와 같은 규칙
    (매수일보다 늦으면 거부)을 그대로 적용한다.

    `adjustments` 는 건드리지 않는다 — 지금 이 필드를 쓰는 쪽이 없고
    (아무도 안 씀), 페이지도 이 필드가 있는 기록은 가격 파생값 계산 자체를
    건너뛴다. amend 페이로드에 이 필드의 모양이 정의돼 있지 않은데 여기서
    임의로 스키마를 만들면 아무도 합의하지 않은 걸 새로 만드는 셈이다.
    """
    target_id = req.get("id")
    was = req.get("was")
    state = normalize(state)
    idx = next((i for i, p in enumerate(state["positions"]) if p["id"] == target_id), None)
    if idx is None:
        raise RejectedError(f"고칠 대상 없음: {target_id!r}")
    match = state["positions"][idx]
    if match["code"] != was:
        raise RejectedError(
            f"코드 불일치(was) — 저장된 값과 다름: 저장={match['code']!r} 요청={was!r}")

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

    buy_patch = req.get("buy")
    if buy_patch is not None:
        if not isinstance(buy_patch, dict):
            raise RejectedError(f"buy 가 객체가 아님: {buy_patch!r}")
        if "price" in buy_patch:
            new["buys"][0]["price"] = _price(buy_patch["price"])
        if "date" in buy_patch:
            new["buys"][0]["date"] = _date(buy_patch["date"])

    exit_patch = req.get("exit")
    if exit_patch is not None:
        if not isinstance(exit_patch, dict):
            raise RejectedError(f"exit 가 객체가 아님: {exit_patch!r}")
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
    return state
