# -*- coding: utf-8 -*-
"""gh.py: data 브랜치 Contents API 래퍼(Task 5).

이 파일은 두 층을 나눠서 테스트한다.

1) `read_json`/`write_json`/`list_dir` — 항상 `gh._api` 를 monkeypatch 해서
   막는다. 이 함수들은 "payload 를 어떻게 조립하는가"만 검증하면 되고, 실제
   HTTP 왕복은 몰라도 된다.
2) `_api` 자체 — `urllib.request.urlopen` 을 monkeypatch 해서 막는다. 여기서는
   404→NotFound 변환, 그 외 상태코드는 그대로 전파되는지, 토큰 누락 시
   RuntimeError 가 나는지를 검증한다. **실제 네트워크는 절대 타지 않는다** —
   러너에서 결정적으로 돌아야 하기 때문이다(naver.py 테스트와 같은 원칙).

실제 GitHub API 실측(author/committer 기본값, 디렉토리 목록 1,000개 상한,
파일 크기 상한, 409 응답, GITHUB_TOKEN 시간당 한도)은 이 파일이 아니라
구현 커밋 메시지/PR 설명에 남긴다 — 테스트는 "결정된 동작"만 고정한다.
"""
import base64
import json
import urllib.error

import pytest

from scripts import gh


# ---------------------------------------------------------------------------
# 제공된 테스트 (그대로)
# ---------------------------------------------------------------------------

def test_없는_파일은_기본값으로_읽는다(monkeypatch):
    def 가짜(method, path, payload=None):
        raise gh.NotFound(path)
    monkeypatch.setattr(gh, "_api", 가짜)
    body, sha = gh.read_json("positions.json", default={"a": 1})
    assert body == {"a": 1}
    assert sha is None


def test_있는_파일을_읽고_sha를_돌려준다(monkeypatch):
    enc = base64.b64encode(json.dumps({"x": 2}).encode()).decode()
    monkeypatch.setattr(gh, "_api",
                        lambda m, p, payload=None: {"content": enc, "sha": "abc"})
    body, sha = gh.read_json("quotes.json")
    assert body == {"x": 2}
    assert sha == "abc"


def test_깨진_JSON은_기본값으로_격리한다(monkeypatch):
    enc = base64.b64encode(b"{ \xeb\xa7\x9d\xea\xb0\x80\xec\xa7\x90").decode()
    monkeypatch.setattr(gh, "_api",
                        lambda m, p, payload=None: {"content": enc, "sha": "abc"})
    body, sha = gh.read_json("positions.json", default={"safe": True})
    assert body == {"safe": True}
    assert sha == "abc"          # 덮어쓸 수 있게 sha 는 유지


def test_쓸때_sha와_커밋신원을_붙인다(monkeypatch):
    본 = {}

    def 가짜(method, path, payload=None):
        본.update(payload); 본["_path"] = path; 본["_m"] = method
        return {"commit": {"sha": "new"}}

    monkeypatch.setattr(gh, "_api", 가짜)
    gh.write_json("quotes.json", {"k": 1}, sha="old", message="갱신")
    assert 본["_m"] == "PUT"
    assert 본["branch"] == "data"
    assert 본["sha"] == "old"
    assert 본["message"] == "갱신"
    assert json.loads(base64.b64decode(본["content"])) == {"k": 1}
    # 이메일을 명시하지 않으면 실제 주소가 공개 브랜치에 남는다
    assert 본["committer"]["email"].endswith("noreply.github.com")


def test_새_파일은_sha를_보내지_않는다(monkeypatch):
    본 = {}
    monkeypatch.setattr(gh, "_api", lambda m, p, payload=None: (본.update(payload), {})[1])
    gh.write_json("new.json", {"k": 1}, sha=None, message="생성")
    assert "sha" not in 본


# ---------------------------------------------------------------------------
# 추가 테스트 — 비평에서 나온 항목들
# ---------------------------------------------------------------------------

# 5) positions.json 은 유일하게 복구 불가능한 파일이다. read_json 의 기본
#    동작(깨지면 default+sha)은 quotes/master/history 처럼 재생성 가능한
#    파일에는 맞지만, positions.json 을 다루는 호출자(Task 6 intake.py)는
#    "없음"과 "깨짐"을 구분해서 깨짐일 때는 절대 덮어쓰지 않아야 한다.
#    기존 계약(제공된 테스트)은 그대로 두고, strict=True 일 때만 예외로
#    올리는 옵션을 추가한다 — 호출자가 선택할 수 있게.
def test_strict_모드에서는_깨진_JSON을_기본값_대신_예외로_올린다(monkeypatch):
    enc = base64.b64encode(b"{ \xeb\xa7\x9d\xea\xb0\x80\xec\xa7\x90").decode()
    monkeypatch.setattr(gh, "_api",
                        lambda m, p, payload=None: {"content": enc, "sha": "abc"})
    with pytest.raises(gh.CorruptJSON) as exc_info:
        gh.read_json("positions.json", default={"safe": True}, strict=True)
    assert exc_info.value.path == "positions.json"
    assert exc_info.value.sha == "abc"          # sha 는 예외에도 실려있다 — 복구용


def test_strict_모드여도_없는_파일은_그냥_기본값이다(monkeypatch):
    """strict 는 "깨짐"만 예외로 올린다 — "없음"은 정상적인 최초 상태다."""
    def 가짜(method, path, payload=None):
        raise gh.NotFound(path)
    monkeypatch.setattr(gh, "_api", 가짜)
    body, sha = gh.read_json("positions.json", default={"a": 1}, strict=True)
    assert body == {"a": 1}
    assert sha is None


# 7) list_dir 이 디렉토리가 아니라 파일 경로를 받으면(=버그로 상위 호출자가
#    잘못된 경로를 줬을 때) Contents API 는 리스트가 아니라 dict 하나를
#    돌려준다. 원안의 `[x["name"] for x in r if isinstance(x, dict)]` 는
#    dict 를 순회하면 키(문자열)만 나오므로 isinstance 체크에서 전부
#    걸러져 조용히 빈 리스트를 돌려준다 — "실패를 감추지 않는다"는 이
#    프로젝트의 원칙과 반대다. close.py(Task 8)의 history/ 백필 로직이
#    이걸 근거로 "기존 기록 없음"이라고 오판하면 안 되므로 명시적으로 막는다.
def test_list_dir_파일경로를_주면_에러를_낸다(monkeypatch):
    monkeypatch.setattr(gh, "_api",
                        lambda m, p, payload=None: {"name": "positions.json", "type": "file"})
    with pytest.raises(NotADirectoryError):
        gh.list_dir("positions.json")


def test_list_dir_정상_디렉토리는_이름_목록을_돌려준다(monkeypatch):
    가짜목록 = [{"name": "2026-08-17.json", "type": "file"},
              {"name": "2026-08-18.json", "type": "file"}]
    monkeypatch.setattr(gh, "_api", lambda m, p, payload=None: 가짜목록)
    assert gh.list_dir("history") == ["2026-08-17.json", "2026-08-18.json"]


# 지금 실측(2026-08-19): history/ 는 아직 존재하지 않는 디렉토리라 GET 은
# 404 를 낸다 — "빈 디렉토리"가 아니라 "없는 경로"다. NotFound 를 빈
# 리스트로 취급하는 게 맞는 이유: close.py 첫 실행 시점에 history/ 가 아직
# 하나도 없어도 "백필할 게 없다"가 아니라 "전부 백필해야 한다"로 이어지는
# 정상 시작 상태이기 때문이다.
def test_list_dir_없는_디렉토리는_빈_리스트다(monkeypatch):
    def 가짜(method, path, payload=None):
        raise gh.NotFound(path)
    monkeypatch.setattr(gh, "_api", 가짜)
    assert gh.list_dir("history") == []


# 6) _api 가 조립하는 URL 에 경로 세그먼트를 그대로 f-string 으로 꽂는다.
#    지금 당장의 호출자는 전부 안전한 상수/ISO 날짜라 실질적 위험은 없지만,
#    퍼센트 인코딩을 빼먹으면 공백 등이 섞인 경로에서 조용히 잘못된 URL을
#    만들 수 있다. read_json/write_json/list_dir 이 공유하는 내부 헬퍼
#    `_contents_url` 에서 세그먼트 단위로 인코딩한다 — `/` 는 구분자로 남기고
#    각 세그먼트만 인코딩해야 `history/2026-08-19.json` 같은 하위 경로가
#    깨지지 않는다.
def test_contents_url은_경로_세그먼트를_퍼센트_인코딩한다():
    assert gh._contents_url("quotes.json") == f"/repos/{gh.REPO}/contents/quotes.json"
    assert (gh._contents_url("history/2026-08-19.json")
            == f"/repos/{gh.REPO}/contents/history/2026-08-19.json")
    assert (gh._contents_url("weird name.json")
            == f"/repos/{gh.REPO}/contents/weird%20name.json")


# ---------------------------------------------------------------------------
# `_api` 자체 — urlopen 을 막아서 확인한다 (실제 네트워크 없음)
# ---------------------------------------------------------------------------

class _가짜응답:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_api_토큰이_없으면_RuntimeError(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        gh._api("GET", "/repos/x/y/contents/z.json")


def test_api_404는_NotFound로_바뀐다(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")

    def 가짜_urlopen(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(gh.urllib.request, "urlopen", 가짜_urlopen)
    with pytest.raises(gh.NotFound):
        gh._api("GET", "/repos/x/y/contents/nope.json")


# 4) sha 가 낡았을 때 GitHub 는 409 를 준다(2026-08-19 실측). _api 는 404
#    말고는 전부 그대로 다시 던지므로 409 도 urllib.error.HTTPError 그대로
#    올라간다 — 이건 "조용히 삼키지 않고 눈에 보이게 죽는다"는 이 프로젝트의
#    원칙과 맞다. write_json 세 곳(intake/quotes/close)이 전부 같은
#    concurrency 그룹으로 직렬화돼 있어서 같은 실행 안에서 스스로 409를
#    낼 일은 없고, 사람이 data 브랜치를 수동으로 건드리는 등 바깥 요인일
#    때만 발생한다 — 그럴 땐 조용히 넘어가지 않고 워크플로우가 실패하는 게
#    맞으므로 별도 예외 클래스로 감싸지 않는다.
def test_api_409는_그대로_전파된다(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")

    def 가짜_urlopen(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, 409, "Conflict", {}, None)

    monkeypatch.setattr(gh.urllib.request, "urlopen", 가짜_urlopen)
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        gh._api("PUT", "/repos/x/y/contents/quotes.json", {"a": 1})
    assert exc_info.value.code == 409


def test_api_정상응답은_JSON으로_파싱된다(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    captured = {}

    def 가짜_urlopen(req, timeout=30):
        captured["headers"] = dict(req.header_items())
        captured["method"] = req.get_method()
        return _가짜응답(b'{"ok": true}')

    monkeypatch.setattr(gh.urllib.request, "urlopen", 가짜_urlopen)
    result = gh._api("GET", "/repos/x/y/contents/z.json")
    assert result == {"ok": True}
    assert captured["headers"]["Authorization"] == "Bearer t"
    assert captured["method"] == "GET"
