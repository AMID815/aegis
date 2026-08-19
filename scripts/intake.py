# -*- coding: utf-8 -*-
"""이슈 본문 → positions.json.

이슈는 **공개 리포라 누구나 열 수 있다.** 작성자 확인은 워크플로 job 레벨
(`if: github.event.issue.user.login == github.repository_owner`)에서 한다 —
여기까지 왔다는 건 이미 본인이라는 뜻이다. 그래도 **모양**은 여기서 다시
본다 — "본인이 냈다"가 "본인이 낸 JSON 이 유효하다"를 보장하진 않는다.

종료코드는 워크플로가 그대로 읽어 사용자에게 다른 코멘트를 다는 계약이다:

  0 = 반영됨 — 아무 것도 안 해도 됨
  2 = **이 이슈의 입력**이 틀림(형식/중복/미보유 등) — 고쳐서 다시 제출
  3 = **positions.json 자체**를 못 믿음(깨짐/스키마 불일치/개별 항목 손상)
      — 이 이슈에 뭘 적어 냈든 똑같이 막힌다. 사람이 파일을 손으로 고치기
      전엔 재제출해도 소용없다. 그래서 2 와 분리한다(코드리뷰 포인트 4).

이 둘 중 어디에도 안 속하는 실패(쓰기 API 409/5xx, ISSUE_BODY 환경변수
자체가 없는 워크플로 배선 문제 등)는 조용히 삼켜 2/3 으로 뭉개지 않고
그대로 올려보낸다 — 재시도나 설정 수정으로 풀릴 별개의 사고를 "입력을
고쳐라"/"파일을 고쳐라"로 잘못 안내하면 안 되기 때문이다(코드리뷰 포인트
5, 7). GitHub Actions 는 이걸 그냥 "실패한 스텝"으로 본다.
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
MAX_BODY = 8000
POSITIONS = "positions.json"


def extract(body: str) -> dict:
    """이슈 본문에서 fenced json 블록 하나를 뽑아 dict 로 돌려준다.

    형식이 틀리면 전부 RejectedError — 이 함수가 다루는 건 "이 이슈에
    뭐라고 적었는가"이지 positions.json 상태와는 무관하다. 그래서 여기서
    올리는 예외는 main() 에서 항상 종료코드 2(입력 거부)로 이어진다.
    """
    if not isinstance(body, str) or len(body) > MAX_BODY:
        raise models.RejectedError("본문이 없거나 너무 김")
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
    raise models.RejectedError(f"모르는 op: {op!r}")


def _clean_for_message(v, limit: int = 60):
    """커밋 메시지에 넣기 전에 방어적으로 정리한다.

    models._text 는 positions.json 에 "저장"되는 값의 길이만 자르고
    개행·제어문자는 막지 않는다(strict 가 아닌 필드는 조용히 자르기만
    한다는 게 models 의 기존 결정이고, 그건 안 건드린다). 하지만 커밋
    메시지 조립은 그 검증을 거치지 않은 req 원본을 그대로 쓸 수 있어서
    별개의 위험이다 — name 에 개행이 섞이면 git 로그에 여러 줄짜리(또는
    위조처럼 보이는) 커밋 메시지가 남는다(코드리뷰 포인트 6). 그래서
    커밋 메시지용으로 한 번 더, 별도로 정리한다.
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
        # 만들 수 없는 파일이다(코드리뷰 C1). 이것도 이 이슈의 입력과
        # 무관하게 파일 자체에 이미 있던 문제이므로, 바로 위 schema
        # 불일치와 같은 이유로 3(코드리뷰 포인트 4 — 애초 초안은 여기를
        # 2 로 뒀는데, "재제출해도 이 손상은 그대로"라는 점에서 3 이
        # 맞다).
        ids = [p.get("id") or p.get("code") for p in bad]
        print(f"[중단] 해석 불가 항목 {len(bad)}건 — 파일에 손대지 않는다: {ids}")
        return 3

    try:
        out = apply(state, req)
    except models.RejectedError as e:
        print(f"거부: {e}")
        return 2

    op = req.get("op")
    # code/date 는 이 시점에 이미 apply() 안의 _code()/_date() 를 통과했다
    # — 둘 다 글자 집합이 정규식(`\Z` 앵커, 개행 불가)으로 고정돼 있어
    # name 과 달리 커밋 메시지용 별도 정리가 필요 없다.
    name = _clean_for_message(req.get("name")) or req.get("code")
    message = f"{op}: {name} ({req.get('date')})"
    try:
        gh.write_json(POSITIONS, out, sha, message)
    except RuntimeError as e:
        # 전송 실패(409 sha 충돌, 5xx 등)는 "입력이 틀렸다"도 "파일이
        # 망가졌다"도 아니다 — 재시도나 다음 실행에서 자연히 풀릴 수 있는
        # 별개의 사고다. 2/3 으로 뭉뚱그리면 워크플로가 엉뚱한 안내
        # 코멘트를 단다. 여기서 삼키지 않고 그대로 올려 0/2/3 밖의
        # 실패로 남긴다 — 메시지는 이미 gh._api 가 method·path·상태코드·
        # 본문을 담아 채워준다(코드리뷰 포인트 5).
        print(f"[오류] positions.json 쓰기 실패 — 재시도 필요, 파일 문제 아님: {e}")
        raise
    print(f"반영: {op} {req.get('code')} — 보유 {len(out['positions'])}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
