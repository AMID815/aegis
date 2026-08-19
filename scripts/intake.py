# -*- coding: utf-8 -*-
"""이슈 본문 → positions.json.

이슈는 **공개 리포라 누구나 열 수 있다.** 작성자 확인은 워크플로 job 레벨
(`if: github.event.issue.user.login == github.repository_owner`)에서 한다 —
여기까지 왔다는 건 이미 본인이라는 뜻이다. 그래도 **모양**은 여기서 다시
본다 — "본인이 냈다"가 "본인이 낸 JSON 이 유효하다"를 보장하진 않는다.

종료코드는 워크플로가 그대로 읽어 사용자에게 다른 코멘트를 다는 계약이다:

  0 = 반영됨 — 아무 것도 안 해도 됨
  2 = **이 이슈의 입력**이 틀림(형식/미보유 등) — 고쳐서 다시 제출
  3 = **positions.json 자체**를 못 믿음(깨짐/스키마 불일치/최상위 구조
      이상/개별 항목 손상) — 이 이슈에 뭘 적어 냈든 똑같이 막힌다. 사람이
      파일을 손으로 고치기 전엔 재제출해도 소용없다. 그래서 2 와
      분리한다(코드리뷰 포인트 4).
  4 = **이미 반영됨**(동일 id 중복 매수) — 고칠 것도, 기다릴 것도 없다.
      "다시 제출"을 안내하면 사용자는 날짜를 바꿔 재제출하기 쉬운데, 그건
      가짜 매매 기록을 파일에 새로 심는 것이다(코드리뷰 I3). 그래서 2 와
      분리한다. apply_sell 의 "보유 중이 아님"은 이미 팔았는지/애초에 안
      샀는지/코드를 잘못 썼는지 이 코드가 구분할 수 없어 그대로 2 에
      남긴다.

이 중 어디에도 안 속하는 실패(쓰기 API 409/5xx, ISSUE_BODY 환경변수 자체가
없는 워크플로 배선 문제, "반영 후 보유 건수가 줄었다"는 내부 불변식 위반
등)는 조용히 삼켜 2/3/4 로 뭉개지 않고 그대로 올려보낸다 — 재시도나 설정
수정으로 풀릴 별개의 사고를, 또는 코드 버그 그 자체를 "입력을 고쳐라"/
"파일을 고쳐라"로 잘못 안내하면 안 되기 때문이다(코드리뷰 포인트 5, 7).
GitHub Actions 는 이걸 그냥 "실패한 스텝"으로 본다.
"""
from __future__ import annotations

import json
import os
import re
import sys

from . import gh, models

# 대시보드 페이지가 조립하는 정상 본문은 fenced json 블록이 정확히 하나다.
# 여러 개가 나타나면(수기 편집, 이전 제출 잔여물 등) 어느 게 진짜 의도인지
# 이 코드가 추측하면 안 된다 — extract() 가 개수를 직접 세서 판단한다
# (코드리뷰 포인트 1).
FENCE = re.compile(r"```json\s*(.+?)\s*```", re.S)
# GitHub 이슈 본문은 65,536자까지 허용하지만, 실제 페이로드(name 40자·
# source 20자·memo 200자 — models._text 상한)는 아무리 늘려 잡아도 수백
# 바이트다. 8000 은 그 실제 필요량보다 훨씬 크게 잡은 파손/DoS 방지용
# 상한이지, 정상적인 긴 메모를 거부할 만큼 타이트하지 않다(코드리뷰
# 포인트 2).
MAX_BODY = 8000
POSITIONS = "positions.json"


def extract(body: str) -> dict:
    """이슈 본문에서 fenced json 블록 하나를 뽑아 dict 로 돌려준다.

    형식이 틀리면 전부 RejectedError — 이 함수가 다루는 건 "이 이슈에
    뭐라고 적었는가"이지 positions.json 상태와는 무관하다. 그래서 여기서
    올리는 예외는 main() 에서 항상 종료코드 2(입력 거부)로 이어진다.
    """
    if not isinstance(body, str):
        raise models.RejectedError("본문이 문자열이 아님")
    if len(body) > MAX_BODY:
        raise models.RejectedError(f"본문이 너무 김({len(body)}자 > {MAX_BODY})")
    blocks = list(FENCE.finditer(body))
    if not blocks:
        raise models.RejectedError("json 블록 없음")
    if len(blocks) > 1:
        raise models.RejectedError(f"json 블록이 {len(blocks)}개 — 하나여야 함")
    try:
        d = json.loads(blocks[0].group(1))
    except ValueError as e:
        raise models.RejectedError(f"JSON 파싱 실패: {e}")
    if not isinstance(d, dict):
        raise models.RejectedError("객체가 아님")
    return d


def apply(state: dict, req: dict) -> dict:
    """req 를 state 에 반영한다. 필드별 검증은 전부 models 에 위임한다.

    req 에 code/price/date 등이 빠지거나 이상해도 여기서 크래시하지 않는다
    — models._code/_date/_price 가 각각 "어떤 필드가 왜 틀렸는지" 담은
    RejectedError 를 낸다(코드리뷰 포인트 3, models.py 위임 확인만 하고
    별도 검증을 추가하지 않았다).
    """
    op = req.get("op")
    if op == "buy":
        return models.apply_buy(state, req)
    if op == "sell":
        return models.apply_sell(state, req)
    if op == "amend":
        return models.apply_amend(state, req)
    raise models.RejectedError(f"모르는 op: {op!r}")


def _single_line(v, limit: int = 40):
    """개행을 공백으로 지우고 limit 자로 자른 한 줄짜리 문자열을 돌려준다
    (문자열이 아니면 None). 커밋 메시지 조립 전용 — positions.json 에
    "저장"되는 값의 검증(models._text)과는 별개다.

    models._text 는 길이만 자르고 개행·제어문자는 막지 않는다(strict 가
    아닌 필드는 조용히 자르기만 한다는 게 models 의 기존 결정이고, 그건
    안 건드린다). 하지만 커밋 메시지 조립은 그 검증을 거치지 않은 req
    원본을 직접 쓸 수 있어서 별개의 위험이다 — name 에 개행이 섞이면 git
    로그에 여러 줄짜리 커밋이 생기고, 빈 줄 뒤에 `Key: value` 모양의 줄이
    오면 git 이 그걸 실제 트레일러(예: `Co-authored-by:`)로 해석해버린다
    (실측 확인 — 코드리뷰 포인트 6). limit 은 60 이 아니라 40 이다 —
    positions.json 에 저장되는 name 상한(models._text(..., 40, ...))과
    맞춰서, 커밋 메시지에 파일에는 없는 글자가 보이는 일이 없게 한다.
    """
    if not isinstance(v, str):
        return None
    v = v.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").strip()
    return v[:limit] or None


def main() -> int:
    body = os.environ.get("ISSUE_BODY")
    if body is None:
        # 환경변수 자체가 없는 건 워크플로 배선 문제이지, 사용자가 빈
        # 이슈를 낸 것과 같은 사고가 아니다(코드리뷰 포인트 7). 조용히
        # ""로 흡수해 종료코드 2(입력 거부)로 나가면, 워크플로가
        # 고장났는데도 사용자에게 "다시 입력해 달라"는 엉뚱한 코멘트가
        # 달려 진짜 원인을 가린다. 여기서 잡지 않고 그대로 올려 0/2/3
        # 밖의, 눈에 띄는 실패로 남긴다.
        raise RuntimeError(
            "ISSUE_BODY 환경변수가 설정되지 않음 — 워크플로 설정을 확인하라")

    try:
        req = extract(body)
    except models.RejectedError as e:
        print(f"거부: {e}")
        return 2

    try:
        state, sha = gh.read_json(POSITIONS, default=models.empty_state())
    except gh.CorruptJSON as e:
        # positions.json 을 통째로 못 읽었다. 여기서 새로 쓰면 손입력
        # 원본이 사라진다. 사용자가 파일을 고치기 전에는 아무것도 하지
        # 않는다.
        print(f"[중단] {e}")
        return 3

    # normalize() 를 부르기 전에 최상위 모양부터 직접 본다. normalize() 도
    # (아래에서) 같은 상황을 dropped 마커로 보고하긴 하지만, intake.py는
    # 자기 docstring에 "읽은 걸 안 믿는다"고 적어놓은 쓰기 쪽이다 — 그
    # 신뢰를 normalize() 내부 구현 하나에만 의존하면 안 된다. 이 파일이
    # 손편집으로 배열(`[...]`)만 남거나, "positions" 키가 오타나거나,
    # dict/None 등 엉뚱한 타입이 되면 여기서 바로 멈춘다. 안 그러면
    # 아래 normalize() 가 조용히 빈 상태를 돌려주고, 그 위에 이번 매수
    # 하나만 얹은 파일이 기존 sha 위에 그대로 커밋된다 — 기존 보유 전체가
    # 삭제되는데 종료코드는 0, 워크플로는 "반영했습니다"로 닫는다
    # (코드리뷰 C1, 실측: 배열/키오타/positions가 dict/positions가 null
    # 네 가지 모양 전부 이 경로 없이는 rc=0으로 전체 삭제됐다).
    if not (isinstance(state, dict) and isinstance(state.get("positions"), list)):
        print("[중단] positions.json 최상위 구조가 예상과 다름 — 파일에 손대지 않는다")
        return 3

    bad = []
    try:
        state = models.normalize(state, bad)
    except models.RejectedError as e:
        # normalize() 가 직접 raise 하는 유일한 경우 — schema 자체가 이
        # 코드가 모르는 버전이다. 이 이슈에 뭘 적어 냈든 결과는 똑같이
        # 막히므로 "입력을 고쳐 다시 내라"(2)는 오답이다. CorruptJSON 과
        # 같은 취급: 사람이 파일을 손보기 전엔 아무 것도 안 한다
        # (코드리뷰 포인트 4).
        print(f"[중단] positions.json 스키마를 알 수 없음 — 파일에 손대지 않는다: {e}")
        return 3
    if bad:
        # 손상된 항목이 하나라도 있으면 여기서 그냥 진행하면 normalize 가
        # 버린 항목이 이 커밋으로 영구 삭제된다 — positions.json 은 다시
        # 만들 수 없는 파일이다(코드리뷰 C1). 위 최상위 구조 가드를
        # 통과했더라도 normalize() 는 "id 는 있는데 buys 가 이상함" 같은
        # 개별 항목 손상, 그리고(이론상) 위 가드가 놓친 최상위 이상까지
        # 같은 dropped 채널로 보고한다 — 이것도 이 이슈의 입력과 무관하게
        # 파일 자체에 이미 있던 문제이므로, 바로 위 schema 불일치와 같은
        # 이유로 3(코드리뷰 포인트 4 — 애초 초안은 여기를 2 로 뒀는데,
        # "재제출해도 이 손상은 그대로"라는 점에서 3 이 맞다).
        ids = [p.get("id") or p.get("code") for p in bad]
        print(f"[중단] 해석 불가 항목 {len(bad)}건 — 파일에 손대지 않는다: {ids}")
        return 3
    prior_count = len(state["positions"])

    try:
        out = apply(state, req)
    except models.AlreadyApplied as e:
        # 중복 id — 이 요청은 "틀린" 게 아니라 "이미 끝난" 것이다. 2 로
        # 나가면 사용자가 "다시 제출"하다가 날짜를 바꿔서라도 통과시키기
        # 쉬운데, 그건 가짜 매매 기록을 파일에 새로 심는 것이다. 결론을
        # 그대로 말해 추가 조치가 필요 없다는 걸 알린다(코드리뷰 I3).
        print(f"이미 반영되어 있음 — 추가 조치 불필요: {e.pid}")
        return 4
    except models.RejectedError as e:
        print(f"거부: {e}")
        return 2

    if len(out["positions"]) < prior_count:
        # 벨트 앤 브레이시스: 여기까지 온 이상 위의 가드들(최상위 구조,
        # dropped)이 전부 통과했으니 정상적으로는 절대 줄어들 수 없다
        # (buy 는 +1, sell 은 개수 불변). 그런데도 줄었다면 이 코드
        # 자신의 버그이지 사용자 입력도 파일 손상도 아니다 — "고쳐서
        # 다시 제출"도 "파일을 손보라"도 오답이라 2/3/4 어디에도 넣지
        # 않고 시끄럽게 죽는다.
        raise AssertionError(
            f"반영 후 보유 건수가 줄어듦({prior_count} → {len(out['positions'])}) "
            f"— 쓰지 않고 중단, 코드 버그 의심")

    op = req.get("op")
    if op == "amend":
        # amend 는 buy/sell 과 달리 이번 요청이 name 을 안 건드렸을 수
        # 있다(패치 규칙) — 그러면 커밋 메시지용 이름은 "이번에 낸 값"이
        # 아니라 "고친 뒤 기록에 남은 값"이어야 한다. 그 값이 이번 요청이
        # 아니라 **과거에 저장된** name/id 필드일 수도 있는데, normalize()
        # 는 이 두 필드를 내용 검증 없이 보존한다(있으면 setdefault 가
        # 손대지 않는다) — 즉 예전 손편집이 개행이나 가짜 git 트레일러를
        # 남겨놨어도 그대로 실려온다. code/date 와 달리 이 두 필드는 정규식
        # 앵커로 개행이 원천 차단되지 않으므로, 이번에 amend 가 건드렸든
        # 안 건드렸든 커밋 메시지에 넣기 전에는 항상 _single_line 을
        # 거친다(리뷰 포인트 6 과 같은 이유, 출처만 다르다).
        changed = next((new_p for old_p, new_p in zip(state["positions"], out["positions"])
                        if old_p != new_p), None)
        # apply()가 AlreadyApplied 를 안 냈다면(여기 도달했다면) 반드시 하나는
        # 바뀌어 있다 — 못 찾으면 apply_amend 자체의 버그다.
        assert changed is not None, "amend 반영됐다는데 바뀐 기록을 못 찾음 — 코드 버그"
        name = _single_line(changed["name"]) or changed["code"]
        pid = _single_line(changed["id"]) or changed["code"]
        message = f"amend: {name} ({pid})"
    else:
        # code/date 는 이 시점에 이미 apply() 안의 _code()/_date() 를 통과했다
        # — 둘 다 글자 집합이 정규식(`\Z` 앵커, 개행 불가)으로 고정돼 있어
        # name 과 달리 커밋 메시지용 별도 정리가 필요 없다.
        name = _single_line(req.get("name")) or req.get("code")
        message = f"{op}: {name} ({req.get('date')})"
    try:
        gh.write_json(POSITIONS, out, sha, message)
    except RuntimeError as e:
        # 전송 실패(409 sha 충돌, 5xx 등)는 "입력이 틀렸다"도 "파일이
        # 망가졌다"도 아니다 — 재시도나 다음 실행에서 자연히 풀릴 수 있는
        # 별개의 사고다. 2/3/4 로 뭉뚱그리면 워크플로가 엉뚱한 안내
        # 코멘트를 단다. 여기서 삼키지 않고 그대로 올려 그 밖의 실패로
        # 남긴다 — 메시지는 이미 gh._api 가 method·path·상태코드·본문을
        # 담아 채워준다(코드리뷰 포인트 5).
        print(f"[오류] positions.json 쓰기 실패 — 재시도 필요, 파일 문제 아님: {e}")
        raise
    held = sum(1 for p in out["positions"] if p["status"] == models.OPEN)
    # amend 는 req 에 code 가 없는 게 보통이다(패치 규칙 — 코드를 안 고치면
    # 안 적는다) — 그 흔한 경우에 "반영: amend None" 처럼 찍히지 않게 위에서
    # 이미 계산해둔(sanitize 까지 끝난) pid 를 쓴다.
    target = pid if op == "amend" else req.get("code")
    print(f"반영: {op} {target} — 보유 {held}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
