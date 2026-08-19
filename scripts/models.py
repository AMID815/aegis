# -*- coding: utf-8 -*-
"""positions.json 의 모양을 지킨다. 수익률은 여기서 계산하지 않는다 (페이지 몫)."""
from __future__ import annotations

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
    if v <= 0:
        raise RejectedError(f"가격이 0 이하: {v!r}")
    return int(v)


def _code(v):
    if not isinstance(v, str) or not CODE_RE.match(v):
        raise RejectedError(f"종목코드 형식 오류: {v!r}")
    return v


def _date(v):
    if not isinstance(v, str) or not DATE_RE.match(v):
        raise RejectedError(f"날짜 형식 오류(YYYY-MM-DD): {v!r}")
    return v


def normalize(raw) -> dict:
    """읽어온 것을 믿지 않는다. 모양이 틀리면 조용히 버린다."""
    if not isinstance(raw, dict):
        return empty_state()
    items = raw.get("positions")
    if not isinstance(items, list):
        return empty_state()
    good = []
    for p in items:
        if not isinstance(p, dict):
            continue
        try:
            _code(p.get("code"))
        except RejectedError:
            continue
        if not isinstance(p.get("buys"), list) or not p["buys"]:
            continue
        p.setdefault("exits", [])
        p.setdefault("adjustments", [])
        p.setdefault("status", OPEN)
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
    state["positions"].append({
        "id": pid,
        "code": code,
        "name": (req.get("name") or code)[:40],
        "source": (req.get("source") or "수동")[:20],
        "signal_date": sig,
        "buys": [{"date": date, "price": price}],
        "exits": [],
        "adjustments": [],
        "status": OPEN,
        "memo": (req.get("memo") or "")[:200],
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
    target = min(opens, key=lambda p: p["buys"][0]["date"])   # 오래된 것부터
    target["exits"].append({
        "date": date, "price": price, "reason": (req.get("reason") or "")[:40]})
    target["status"] = CLOSED
    return state
