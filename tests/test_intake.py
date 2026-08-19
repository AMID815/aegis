# -*- coding: utf-8 -*-
"""intake.py: 이슈 본문 → positions.json (Task 6, 리뷰 반영판).

공급된 테스트는 거의 그대로 두되, 딱 하나(손상된 항목 → 종료코드)만 리뷰
포인트 4 에 따라 기대값을 2→3 으로 고쳤다 — 아래 해당 테스트의 주석 참조.
그 외 리뷰 포인트(1/5/6/7)에 대응하는 테스트를 추가했다. 포인트 3/8 은
코드를 바꿀 필요가 없다는 결론이라 별도 테스트 없이 기존/신규 테스트가
이미 그 경로를 지나간다(본문 하단 설명 참조).
"""
import pytest

from scripts import intake, models

BODY = """모의고사 입력

```json
{"op":"buy","code":"005930","name":"삼성전자","price":247500,
 "date":"2026-08-19","source":"종가베팅","signal_date":"2026-08-18","memo":"눌림"}
```
"""


# ---------------------------------------------------------------------------
# 공급된 테스트 (그대로)
# ---------------------------------------------------------------------------

def test_이슈_본문에서_JSON_블록을_뽑는다():
    d = intake.extract(BODY)
    assert d["op"] == "buy"
    assert d["code"] == "005930"
    assert d["price"] == 247500


def test_JSON_블록이_없으면_거부한다():
    with pytest.raises(models.RejectedError):
        intake.extract("그냥 아무 말")


def test_깨진_JSON은_거부한다():
    with pytest.raises(models.RejectedError):
        intake.extract("```json\n{망가짐\n```")


def test_매수를_상태에_반영한다():
    out = intake.apply(models.empty_state(), intake.extract(BODY))
    assert out["positions"][0]["code"] == "005930"
    assert out["positions"][0]["source"] == "종가베팅"


def test_매도를_상태에_반영한다():
    st = intake.apply(models.empty_state(), intake.extract(BODY))
    sell = '```json\n{"op":"sell","code":"005930","price":260000,' \
           '"date":"2026-08-25","reason":"목표가"}\n```'
    out = intake.apply(st, intake.extract(sell))
    assert out["positions"][0]["status"] == "closed"


def test_모르는_op는_거부한다():
    with pytest.raises(models.RejectedError):
        intake.apply(models.empty_state(), {"op": "지워줘", "code": "005930"})


def test_본문이_아주_길면_거부한다():
    with pytest.raises(models.RejectedError):
        intake.extract("x" * 20000)


def test_손상된_항목이_있으면_파일에_쓰지_않는다(monkeypatch):
    """조용히 버리고 쓰면 그 커밋으로 영구 삭제된다 (코드리뷰 C1).

    ※ 종료코드는 공급된 버전의 2 에서 3 으로 바꿨다 (리뷰 포인트 4). 이
    시나리오의 손상(코드 5자리 오타)은 이번 이슈에 뭘 적어 냈든 상관없이
    positions.json 자체에 이미 있던 문제다 — "입력을 고쳐 다시 내라"(2)는
    사용자에게 헛수고를 시킨다(재제출해도 파일 쪽 문제는 그대로라 계속
    막힌다). "파일을 손으로 고쳐라"(3)가 실제 필요한 조치와 일치한다.
    unknown-schema 케이스(정확히 같은 이유로 3이어야 하는, 아래 별도
    테스트)와 같은 취급이 맞다 — 둘 다 "이 이슈의 입력과 무관하게 파일
    자체를 못 믿는다"는 동일한 사고다.
    """
    손상 = {"schema": 1, "positions": [
        {"id": "20260801-000660", "code": "00660",        # 5자리 = 손편집 오타
         "buys": [{"date": "2026-08-01", "price": 1234000}], "status": "open"},
    ]}
    monkeypatch.setattr(intake.gh, "read_json", lambda *a, **k: (손상, "sha"))
    쓴것 = []
    monkeypatch.setattr(intake.gh, "write_json",
                        lambda *a, **k: 쓴것.append(a))
    monkeypatch.setenv("ISSUE_BODY", BODY)
    assert intake.main() == 3           # 거부 — 파일 손상 취급
    assert 쓴것 == []                   # 아무것도 쓰지 않았다


# ---------------------------------------------------------------------------
# 리뷰 포인트 1 — json 블록이 여러 개면 첫 블록을 조용히 취하지 않고 거부한다
# ---------------------------------------------------------------------------

# 정상 흐름(대시보드 페이지가 조립한 본문)은 블록이 항상 하나다. 여러 개가
# 나타난다면 사용자가 이슈를 수기로 편집했거나 이전 제출의 잔여물이 남은
# 것인데, 어느 블록이 "진짜" 의도인지 이 코드가 추측해서 첫 번째를 집으면
# 사용자가 의도하지 않은 매매가 조용히 반영될 수 있다.
def test_json_블록이_여러개면_거부한다():
    본문 = BODY + '\n또 다른 지시:\n```json\n' \
        '{"op":"sell","code":"005930","price":1,"date":"2026-08-20"}\n```\n'
    with pytest.raises(models.RejectedError):
        intake.extract(본문)


# ---------------------------------------------------------------------------
# 리뷰 포인트 4 — 알 수 없는 schema 는 "입력 거부"(2)가 아니라
# "파일 손상"(3) 이어야 한다
# ---------------------------------------------------------------------------

def test_알수없는_schema는_파일손상으로_거부한다(monkeypatch):
    """normalize() 가 raise 하는 유일한 경우(schema 불일치)를 직접 겨눈
    테스트. 위 손상-항목 테스트와 달리 이건 normalize() 자체가 통째로
    거부하는 경로다 — 둘 다 종료코드 3 으로 수렴해야 일관적이다."""
    다른버전 = {"schema": 2, "positions": []}
    monkeypatch.setattr(intake.gh, "read_json", lambda *a, **k: (다른버전, "sha"))
    쓴것 = []
    monkeypatch.setattr(intake.gh, "write_json",
                        lambda *a, **k: 쓴것.append(a))
    monkeypatch.setenv("ISSUE_BODY", BODY)
    assert intake.main() == 3
    assert 쓴것 == []


# ---------------------------------------------------------------------------
# 리뷰 포인트 5 — 쓰기 실패(409/5xx 등)를 2/3 으로 뭉개지 않는다
# ---------------------------------------------------------------------------

# gh.write_json 은 RuntimeError 를 낼 수 있다(9번 파일 참조: sha 충돌 409,
# 그 외 4xx/5xx). 이건 "이 이슈의 입력이 틀렸다"도 "positions.json 이
# 손상됐다"도 아니다 — 재시도나 다음 실행에서 자연히 풀릴 수 있는 별개의
# 사고다. main() 이 이걸 삼켜 2 나 3 을 돌려주면 워크플로가 "다시
# 입력하라"거나 "파일을 고쳐라"는 엉뚱한 코멘트를 단다. 그대로 올라가
# 0/2/3 어디에도 속하지 않는 실패로 남아야 한다.
def test_쓰기_실패는_입력거부나_파일손상_코드로_감추지_않는다(monkeypatch):
    monkeypatch.setattr(intake.gh, "read_json",
                        lambda *a, **k: (models.empty_state(), None))

    def 실패(*a, **k):
        raise RuntimeError("PUT positions.json -> 409: sha mismatch")

    monkeypatch.setattr(intake.gh, "write_json", 실패)
    monkeypatch.setenv("ISSUE_BODY", BODY)
    with pytest.raises(RuntimeError):
        intake.main()


# ---------------------------------------------------------------------------
# 리뷰 포인트 6 — 커밋 메시지는 검증되지 않은 원본 name 을 그대로 쓰지 않는다
# ---------------------------------------------------------------------------

# models._text 는 name 의 길이(40자)만 자르지 개행·제어문자는 막지 않는다.
# apply() 가 끝난 뒤 커밋 메시지를 조립할 때 req["name"] 원본을 그대로
# 쓰면, positions.json 에는 안전하게 저장되더라도 git 커밋 메시지에는
# 개행이 그대로 남아 여러 줄짜리(혹은 위조된 것처럼 보이는) 커밋이 생길 수
# 있다.
def test_커밋_메시지에서_이름의_개행을_지운다(monkeypatch):
    monkeypatch.setattr(intake.gh, "read_json",
                        lambda *a, **k: (models.empty_state(), None))
    captured = {}

    def 가짜_쓰기(path, body, sha, message):
        captured["message"] = message

    monkeypatch.setattr(intake.gh, "write_json", 가짜_쓰기)
    나쁜본문 = ('```json\n{"op":"buy","code":"005930",'
              '"name":"삼성전자\\n악성 커밋",'
              '"price":1000,"date":"2026-08-19"}\n```')
    monkeypatch.setenv("ISSUE_BODY", 나쁜본문)
    assert intake.main() == 0
    assert "\n" not in captured["message"]
    assert "삼성전자" in captured["message"]


# ---------------------------------------------------------------------------
# 리뷰 포인트 7 — ISSUE_BODY 가 아예 없는 것과 빈 문자열인 것은 다르게
# 취급한다
# ---------------------------------------------------------------------------

# 환경변수 자체가 없는 건 워크플로 설정 문제(예: env 배선 누락)이지 사용자가
# 빈 이슈를 낸 것과 같은 사고가 아니다. 조용히 ""로 흡수해서 "입력
# 거부"(2)로 나가면 워크플로 배선이 고장났는데도 사용자에게 "다시 입력해
# 달라"는 코멘트가 달려 진짜 원인을 가린다.
def test_ISSUE_BODY_환경변수가_아예_없으면_입력거부와_다르게_실패한다(monkeypatch):
    monkeypatch.delenv("ISSUE_BODY", raising=False)
    with pytest.raises(RuntimeError):
        intake.main()


# 빈 문자열로 "있지만 비어있음"은 여전히 정상적인 "입력 거부"(2) 경로다 —
# 사용자가 이슈 본문을 지우고 제출한 정상적인 실수 케이스.
def test_ISSUE_BODY가_빈_문자열이면_평범한_입력거부다(monkeypatch):
    monkeypatch.setenv("ISSUE_BODY", "")
    assert intake.main() == 2


# ---------------------------------------------------------------------------
# 리뷰 포인트 3 — 필드가 빠진 요청도 크래시 없이 어떤 필드인지 알려주는
# 메시지로 거부한다 (models 위임 확인, 코드 변경 없음)
# ---------------------------------------------------------------------------

def test_필수_필드가_없으면_어떤_필드인지_짐작할_수_있는_메시지를_준다():
    with pytest.raises(models.RejectedError, match="코드"):
        intake.apply(models.empty_state(), {"op": "buy"})


# 리뷰 포인트 8(모듈 attribute 패치가 실제로 가로채는지, 손상-항목 픽스처가
# CorruptJSON 이 아니라 normalize() 의 dropped 경로를 타는지)은 코드 변경이
# 필요 없는 확인 사항이라 별도 테스트를 추가하지 않았다 — 위
# test_손상된_항목이_있으면_파일에_쓰지_않는다 자체가 두 사실을 이미
# 실증한다: intake.gh.read_json 을 완전히 대체하는 가짜로 교체해도
# intake.main() 이 그 가짜를 쓴다는 것(패치가 먹힌다는 뜻), 그리고 그
# 가짜가 파싱까지 끝난 dict 를 직접 돌려주므로 gh.CorruptJSON 경로는 전혀
# 타지 않는다는 것(별개의, "파싱은 됐지만 항목이 이상함" 경로라는 뜻).
