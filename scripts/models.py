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
CODE_RE = re.compile(r"^\d{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
OPEN, CLOSED = "open", "closed"


class RejectedError(Exception):
    """입력이 규칙에 맞지 않아 반영하지 않았다."""


def empty_state() -> dict:
    return {"schema": SCHEMA, "positions": []}


def _price(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise RejectedError(f"가격이 숫자가 아님: {v!r}")
    if not math.isfinite(v):
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


def _text(v, n, default="", strict=False):
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
    """
    if not isinstance(raw, dict):
        return empty_state()
    schema = raw.get("schema")
    if schema is not None and schema != SCHEMA:
        raise RejectedError(f"알 수 없는 schema: {schema!r}")
    items = raw.get("positions")
    if not isinstance(items, list):
        return empty_state()
    good = []
    for p in items:
        if not isinstance(p, dict):
            if dropped is not None:
                dropped.append(p)
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
            _price(buys[0].get("price"))
        except RejectedError:
            if dropped is not None:
                dropped.append(p)
            continue
        p.setdefault("id", f"{p['buys'][0]['date'].replace('-', '')}-{p['code']}")
        p.setdefault("name", p["code"])
        p.setdefault("signal_date", None)
        p.setdefault("exits", [])
        p.setdefault("adjustments", [])
        p.setdefault("status", OPEN)
        if p["status"] not in (OPEN, CLOSED):   # 거래정지/상장폐지는 시세 쪽 파생 상태이지 여기 값이 아니다
            if dropped is not None:
                dropped.append(p)
            continue
        p.setdefault("source", "수동")
        p.setdefault("memo", "")
        good.append(p)
    return {"schema": SCHEMA, "positions": good}


def apply_buy(state: dict, req: dict) -> dict:
    code = _code(req.get("code"))
    date = _date(req.get("date"))
    price = _price(req.get("price"))
    pid = f"{date.replace('-', '')}-{code}"
    state = normalize(state)
    if any(p["id"] == pid for p in state["positions"]):
        raise RejectedError(f"이미 있는 기록: {pid}")
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
