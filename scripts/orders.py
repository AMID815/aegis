# -*- coding: utf-8 -*-
"""가상 지정가 주문 — 순수 계산.

네트워크도 파일 접근도 없다. 주문 가격을 산출하고, 분봉을 시간순으로
재생해 체결 목록을 돌려준다. 부수효과는 전부 autofill.py 몫이다.

확정 규칙은 docs/설계_가상지정가주문.md §2. 숫자를 여기서 바꾸면
test_orders.py 의 부등식 테스트가 막는다 — 손절선이 3차 체결가보다
위로 올라가면 3차 체결 직후 즉시 손절되는 모순이 생긴다.
"""
from __future__ import annotations

# 1차 매수가 대비 비율. 설계 §2 확정값.
BUY2_RATIO = 0.94        # -6%
BUY3_RATIO = 0.88        # -12%
# 평균가 대비 비율.
TAKE_PROFIT_RATIO = 1.053    # +5.3%
STOP_LOSS_RATIO = 0.91       # -9%, 3차 체결 후에만 발동


def plan(first_price: int) -> dict:
    """1차 매수가로부터 2차·3차 지정가를 산출한다.

    진짜 지정가 주문처럼 **관측 시점에 절대가격으로 확정**한다 — 매번
    비율로 다시 계산하면, 나중에 1차가를 amend 로 고쳤을 때 이미 체결된
    2차·3차의 근거 가격이 소급해서 바뀐다.

    원 단위 정수로 반올림한다(절단 아님 — models._price 와 같은 이유로
    계통적 편향을 만들지 않는다). models._price 자체는 정수가 아닌 값을
    반올림할 뿐 거부하지 않는다 — 거부는 models.normalize() 가 하고,
    그것도 이미 디스크에 저장된 값이 정수가 아닐 때(손편집 흔적)뿐이다.

    **하한이 있다** (2026-08-20 리뷰): 1차가가 40원 이하면 반올림 때문에
    손절선이 3차가보다 위로 올라가 이 설계의 핵심 부등식이 깨진다(3차 체결
    즉시 손절). 12원 이하면 buy2 ≤ buy3 로 순서까지 무너지고, 8원이면
    buy2 가 1차가와 같아져 할인이 사라진다. 막지 않는 이유는 여기서 거부하면
    models.apply_buy 가 통째로 실패해 그 종목을 아예 관측할 수 없게 되기
    때문이다 — 정리매매·관리종목이 아니면 닿지 않는 영역이라, 거부보다
    기록해두는 쪽을 골랐다.

    이 붕괴는 즉시 손절로만 나타나지 않는다 — 8원처럼 더 내려가면 반올림이
    익절선을 관측가 자체로 무너뜨려, 하락한 종목이 가짜 승리(익절)로
    기록될 수도 있다(`plan(8)`, `take_profit([8])` 로 확인 가능).
    """
    return {
        "buy2": round(first_price * BUY2_RATIO),
        "buy3": round(first_price * BUY3_RATIO),
    }


def average(prices: list) -> int:
    """체결된 매수가들의 평균. 설계 §3 확정: 동일 수량 가정 = 산술평균.

    수량을 기록하지 않기로 했으므로(포트폴리오 규모 노출 방지) 평균가는
    가정에서 나온다. 나중에 "매번 같은 금액"(조화평균)으로 바꿀 수 있는데,
    그때 **과거 기록의 평균가가 소급해서 바뀌면 안 된다** — 이미 그 평균가로
    익절·손절이 체결된 기록들이라 계산식이 바뀌면 과거 체결이 소급 무효가
    된다. 그래서 체결 기록에 그 시점의 방식(`weighting`)을 함께 저장한다
    (models.apply_fills 참조).
    """
    if not prices:
        raise ValueError("체결된 매수가 없다")
    return round(sum(prices) / len(prices))


def take_profit(prices: list) -> int:
    """익절선. 평균가 기준이라 물타기하면 내려온다 — 그게 물타기의 목적이다."""
    return round(average(prices) * TAKE_PROFIT_RATIO)


def stop_loss(prices: list) -> int | None:
    """손절선. **3차 체결 후에만** 존재한다(설계 §2). 그 전에는 None.

    3차까지 안 간 종목은 손절 경로가 없어 영원히 열려 있을 수 있다 —
    설계 §11 이 명시한 한계이고, 통계 화면이 미결 건수를 드러내야 한다.

    체결이 아예 없어도(`prices == []`) None 이다 — `len(prices) < 3` 에
    걸려 average() 의 빈 리스트 거부(ValueError)까지 가지 않는다. 손절선이
    없다는 결론은 같지만 경로가 다르다는 뜻이라 여기 적어둔다.
    """
    if len(prices) < 3:
        return None
    return round(average(prices) * STOP_LOSS_RATIO)


def replay(ladder: dict, filled: list, minutes: list,
           since: str | None = None, exempt: bool = False) -> list:
    """분봉을 시간순으로 재생해 체결 목록을 돌려준다.

    `ladder` 는 이 기록에 **저장된** 2차·3차 지정가(`positions.json` 의
    `orders`)다. 1차가로부터 매번 다시 계산하지 않는다 — plan() 독스트링이
    말하는 그 이유 그대로다. amend 로 1차가를 고치면 이미 체결된 물타기의
    근거 가격이 소급해서 바뀌고, 사용자가 손으로 지정한 사다리
    (`customized`)는 아예 무시된다.

    `since` 는 **재생 시작 시각**("YYYYMMDDHHMM")이다. 이 시각 이하의 분봉은
    건너뛴다. 호출자가 관측 시각과 **마지막 체결 시각 중 나중**을 넘겨야
    한다 — 관측 시각만 넘기면 다음 사고가 난다(2026-08-20 실측 재현):

        close.yml 은 하루 두 번 돈다(cron "0 8,23"). 두 번째 실행은 개장
        전이라 **같은 거래일을 다시** 처리하는데, 그때 filled 에는 이미
        그날 체결된 매수가 들어 있다. 그러면 체결 이전 시각의 분봉이
        **내려간 익절선**으로 평가되어, 떨어지는 종목이 +5.3% 승리로
        기록된다.

    `filled` 는 비어 있으면 안 된다. 아직 1차도 안 산 기록(pending)은 이
    함수의 대상이 아니다 — 그건 지정가 관찰이 따로 처리한다.

    각 분봉에서 고가·저가만 본다. 분 안에서의 순서는 알 수 없다. 매수는
    저가로, 매도는 고가·저가로 판정하되 **매수를 먼저** 본다 — 갭하락으로
    2차·3차가 같은 분에 체결되는 경우(설계 §4-1)를 실제 지정가 주문과 같게
    처리하기 위함이다.

    **한 분봉이 손절선과 익절선을 둘 다 스치면 손절로 본다.** 어느 쪽이
    먼저였는지 알 수 없고, 설계 §9 가 그 모호함에 대해 "승률을 부풀리지
    않는 쪽"을 규칙으로 정해뒀다. 그렇게 되려면 1분 안에 15.7% 를 출렁여야
    해서 드물지만, 규칙이 있는데 반대로 두면 안 된다.

    **각 주문은 자기 체결 이후의 분봉만 본다.** 이게 이 함수에서 가장
    중요한 규칙이다(설계 §4-1). 3차가 체결되는 순간 익절선이 내려앉는데,
    거기까지 떨어진 시점에 그 가격은 이미 지나온 값이다 — 분봉 전체를
    한꺼번에 보면 **떨어지는 종목이 그 즉시 익절로 닫힌다.** 루프 안에서
    순차 처리하는 지금 구조가 그 성질을 보장한다. 리팩터할 때 익절·손절
    판정을 루프 밖으로 빼면 안 된다.

    `exempt` 는 예외 버튼이다. 켜져 있으면 아무것도 체결하지 않는다 —
    자동매도뿐 아니라 자동매수(2차·3차)도 같이 멈춘다(설계 §8).
    """
    if not filled:
        raise ValueError("1차 매수가 없다 — 아직 안 산 기록(pending)은 replay 대상이 아니다")
    if exempt:
        return []
    held = list(filled)
    out = []
    for m in minutes:
        if since is not None and m["t"] <= since:
            continue
        # 매수 먼저. 갭하락으로 2차·3차가 같은 분에 둘 다 체결될 수 있다 —
        # 지정가 주문의 실제 동작이라 허용하되 순서를 보존한다(설계 §4-1).
        if len(held) == 1 and m["low"] <= ladder["buy2"]:
            held.append(ladder["buy2"])
            out.append({"kind": "buy2", "t": m["t"], "price": ladder["buy2"]})
        if len(held) == 2 and m["low"] <= ladder["buy3"]:
            held.append(ladder["buy3"])
            out.append({"kind": "buy3", "t": m["t"], "price": ladder["buy3"]})

        # 손절을 먼저 본다 — 위 독스트링 "둘 다 스치면 손절" 참조.
        sl = stop_loss(held)
        if sl is not None and m["low"] <= sl:
            out.append({"kind": "stop_loss", "t": m["t"], "price": sl})
            break
        tp = take_profit(held)
        if m["high"] >= tp:
            out.append({"kind": "take_profit", "t": m["t"], "price": tp})
            break
    return out
