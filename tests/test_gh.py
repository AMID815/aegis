# -*- coding: utf-8 -*-
"""gh.py: data 브랜치 Contents API 래퍼(Task 5, 리뷰 반영판).

이 파일은 두 층을 나눠서 테스트한다.

1) `read_json`/`write_json`/`list_dir` — 항상 `gh._api` 를 monkeypatch 해서
   막는다. 이 함수들은 "payload 를 어떻게 조립하는가"만 검증하면 되고, 실제
   HTTP 왕복은 몰라도 된다. 여기서 흉내내는 `_api` 반환값은 실제 Contents API
   응답 모양을 따른다 — 특히 단일 파일 GET 은 항상 `encoding` 필드를 들고
   온다(실측: `.keep` 응답에 `"encoding":"base64"`가 있었다). 이 필드가 없는
   가짜 응답을 쓰면 read_json 의 1MB 초과 검사가 오작동한 것처럼 보이므로
   빠뜨리지 않는다.
2) `_api` 자체 — `urllib.request.urlopen` 을 monkeypatch 해서 막는다. 여기서는
   404→NotFound 변환, 그 외 상태코드는 경로·몸통을 담은 RuntimeError 로
   바뀌는지, 토큰 누락 시 RuntimeError 가 나는지를 검증한다. **실제
   네트워크는 절대 타지 않는다** — 러너에서 결정적으로 돌아야 하기
   때문이다(naver.py 테스트와 같은 원칙).

실제 GitHub API 실측(author/committer 기본값, 디렉토리 목록 1,000개 상한,
파일 크기 상한, 409 응답 몸통, GITHUB_TOKEN 시간당 한도)은 이 파일이 아니라
구현 커밋 메시지/PR 설명에 남긴다 — 테스트는 "결정된 동작"만 고정한다.
"""
import base64
import io
import json
import urllib.error

import pytest

from scripts import gh


# ---------------------------------------------------------------------------
# 제공된 테스트 (positions.json 이 항상-strict 로 바뀌면서 경로를 바꾼 한 곳
# 제외하고 그대로)
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
    monkeypatch.setattr(
        gh, "_api",
        lambda m, p, payload=None: {"content": enc, "sha": "abc", "encoding": "base64"})
    body, sha = gh.read_json("quotes.json")
    assert body == {"x": 2}
    assert sha == "abc"


# 원래 제공된 테스트는 "positions.json" 으로 이 케이스를 확인했다. 리뷰 I3
# 이후 positions.json 은 `IRREPLACEABLE` 이라 깨지면 항상 CorruptJSON 을
# 올리므로(strict 인자와 무관), 여기서는 "재생성 가능한 파일이 깨지면
# default+sha 로 회수한다"는 원래 의도를 재생성 가능한 파일(quotes.json)로
# 옮겨서 그대로 검증한다. positions.json 쪽 동작은 아래
# test_positions_json은_인자_없이도_깨지면_예외를_올린다 가 대신 고정한다.
def test_깨진_JSON은_기본값으로_격리한다(monkeypatch):
    enc = base64.b64encode(b"{ \xeb\xa7\x9d\xea\xb0\x80\xec\xa7\x90").decode()
    monkeypatch.setattr(
        gh, "_api",
        lambda m, p, payload=None: {"content": enc, "sha": "abc", "encoding": "base64"})
    body, sha = gh.read_json("quotes.json", default={"safe": True})
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
# I3 — positions.json 은 strict 인자와 무관하게 항상 막는다
# ---------------------------------------------------------------------------

# 5)/I3) positions.json 은 유일하게 복구 불가능한 파일이다. strict 를 "호출"에
#    붙이면 Task 6/7/8 의 실제 호출부(`read_json(POSITIONS,
#    default=empty_state())`, 두 인자짜리 평범한 호출)가 하나라도 strict=True
#    를 빠뜨리면 보호가 사라진다. 그래서 파일이 결정한다 —
#    `gh.IRREPLACEABLE` 에 오른 경로는 strict 인자가 없어도(기본값 False
#    여도) 항상 CorruptJSON 을 올린다.
def test_positions_json은_인자_없이도_깨지면_예외를_올린다(monkeypatch):
    enc = base64.b64encode(b"{ \xeb\xa7\x9d\xea\xb0\x80\xec\xa7\x90").decode()
    monkeypatch.setattr(
        gh, "_api",
        lambda m, p, payload=None: {"content": enc, "sha": "abc", "encoding": "base64"})
    with pytest.raises(gh.CorruptJSON) as exc_info:
        gh.read_json(gh.POSITIONS, default={"safe": True})   # strict 인자 없음
    assert exc_info.value.path == gh.POSITIONS
    assert exc_info.value.sha == "abc"


# strict 플래그 자체도 여전히 동작해야 한다 — IRREPLACEABLE 이 아닌 파일에서
# 호출자가 명시적으로 강하게 검증하고 싶을 때 쓸 수 있게 남겨뒀다(모듈
# docstring). positions.json 이 아니라 quotes.json 으로 확인해야 "플래그가
# 스스로 동작한다"를 IRREPLACEABLE 과 분리해서 볼 수 있다.
def test_strict_모드는_IRREPLACEABLE이_아닌_파일에도_동작한다(monkeypatch):
    enc = base64.b64encode(b"{ \xeb\xa7\x9d\xea\xb0\x80\xec\xa7\x90").decode()
    monkeypatch.setattr(
        gh, "_api",
        lambda m, p, payload=None: {"content": enc, "sha": "abc", "encoding": "base64"})
    with pytest.raises(gh.CorruptJSON) as exc_info:
        gh.read_json("quotes.json", default={"safe": True}, strict=True)
    assert exc_info.value.path == "quotes.json"
    assert exc_info.value.sha == "abc"


def test_strict_모드여도_없는_파일은_그냥_기본값이다(monkeypatch):
    """strict/IRREPLACEABLE 은 "깨짐"만 예외로 올린다 — "없음"은 정상적인
    최초 상태다(positions.json 도 마찬가지)."""
    def 가짜(method, path, payload=None):
        raise gh.NotFound(path)
    monkeypatch.setattr(gh, "_api", 가짜)
    body, sha = gh.read_json("positions.json", default={"a": 1}, strict=True)
    assert body == {"a": 1}
    assert sha is None


# M7) CorruptJSON 의 sha 를 그대로 write_json 에 넘기면 깨진 원본을 지우는
#     정확히 그 사고가 난다. 메시지에 복구 경로(git/blobs)를 박아 sha 가
#     "다시 써도 됨"이 아니라 "이걸로 원본을 꺼내라"로 읽히게 한다.
def test_CorruptJSON_메시지는_복구_명령을_담는다():
    exc = gh.CorruptJSON("positions.json", "abc123")
    msg = str(exc)
    assert "abc123" in msg
    assert "git/blobs" in msg
    assert gh.REPO in msg


# ---------------------------------------------------------------------------
# I1 — 1MB 초과 파일은 default 로 숨기지 않는다(strict 여부 무관)
# ---------------------------------------------------------------------------

# 실측(2026-08-19): 1,537,782바이트 파일은 GET 응답이 encoding:"none",
# content:"" 로 온다. 이걸 그냥 base64.b64decode 하면 b"" 가 되고
# json.loads(b"") 는 ValueError 를 내서 "JSON 이 깨졌다"와 똑같은 코드를
# 타 버린다 — 멀쩡한 대용량 파일이 sha 를 가진 채로 default 로 조용히
# 대체되고, 다음 write_json 이 그 sha 위에 default 를 얹으면 진짜 삭제가
# 커밋된다. 그래서 이 검사는 strict/IRREPLACEABLE 과 무관하게 항상 켜져
# 있어야 한다 — positions.json 이 아니어도(quotes.json 이어도) 막는다.
def test_1MB_초과_파일은_기본값으로_숨기지_않고_에러를_낸다(monkeypatch):
    def 가짜(method, path, payload=None):
        return {"encoding": "none", "size": 1537782, "content": "", "sha": "bc55745c"}
    monkeypatch.setattr(gh, "_api", 가짜)
    with pytest.raises(RuntimeError) as exc_info:
        gh.read_json("master.json", default={"THIS_IS_DEFAULT": True})
    msg = str(exc_info.value)
    assert "master.json" in msg
    assert "1537782" in msg


def test_1MB_초과는_strict_아니어도_quotes에서도_예외다(monkeypatch):
    def 가짜(method, path, payload=None):
        return {"encoding": "none", "size": 2_000_000, "content": ""}
    monkeypatch.setattr(gh, "_api", 가짜)
    with pytest.raises(RuntimeError):
        gh.read_json("quotes.json", default={"safe": True}, strict=False)


# ---------------------------------------------------------------------------
# M10 — UnicodeDecodeError 경로(ValueError 와 다른 갈래)도 실제로 탄다
# ---------------------------------------------------------------------------

# naver.py 가 이미 cp949/utf-8 코덱 함정에 물린 적이 있다(시가총액 페이지 등
# EUC-KR 응답 — market_calendar_공유노트 참조). gh.py 는 그 문제가 없어야
# 하지만, "있다"를 주장하려면 실제로 UTF-8 이 아닌 바이트로 확인해야 한다 —
# 지금까지의 깨진-JSON 픽스처는 전부 유효한 UTF-8(그냥 문법이 틀린 JSON)이라
# ValueError 갈래만 탔지 UnicodeDecodeError 갈래는 한 번도 안 탔다.
def test_cp949로_깨진_바이트도_기본값으로_격리한다(monkeypatch):
    raw = "삼성전자".encode("cp949")     # utf-8 로 디코드하면 바로 실패한다
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")              # 픽스처 전제 확인
    enc = base64.b64encode(raw).decode()
    monkeypatch.setattr(
        gh, "_api",
        lambda m, p, payload=None: {"content": enc, "sha": "abc", "encoding": "base64"})
    body, sha = gh.read_json("quotes.json", default={"safe": True})
    assert body == {"safe": True}
    assert sha == "abc"


# ---------------------------------------------------------------------------
# 7)/M8 — list_dir: 파일 경로, 정상 디렉토리(하위 디렉토리 포함), 빈 것,
# 1,000개 상한
# ---------------------------------------------------------------------------

def test_list_dir_파일경로를_주면_에러를_낸다(monkeypatch):
    monkeypatch.setattr(gh, "_api",
                        lambda m, p, payload=None: {"name": "positions.json", "type": "file"})
    with pytest.raises(NotADirectoryError):
        gh.list_dir("positions.json")


# M8) 원래 docstring 은 "파일 이름 목록"이라 썼지만 실제로는 type 필터가
#     없어 하위 디렉토리 이름도 그대로 섞여 나온다. history/ 는 하위
#     디렉토리를 두지 않으니 지금은 해가 없지만, 문서와 동작이 다르면 나중에
#     누군가 "당연히 파일만 오겠지"라고 오판할 수 있어 동작을 테스트로
#     고정해둔다.
def test_list_dir_정상_디렉토리는_하위_디렉토리도_포함한다(monkeypatch):
    가짜목록 = [{"name": "2026-08-17.json", "type": "file"},
              {"name": "2026-08-18.json", "type": "file"},
              {"name": "archive", "type": "dir"}]
    monkeypatch.setattr(gh, "_api", lambda m, p, payload=None: 가짜목록)
    assert gh.list_dir("history") == ["2026-08-17.json", "2026-08-18.json", "archive"]


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


# M11) Contents API 는 디렉토리당 최대 1,000개 항목까지만 주고 페이지네이션이
#      없다(공식 문서 확인, 모듈 docstring 참조). history/ 는 연 250여 개씩
#      쌓이니 2030년경 닿는다 — 그때 조용히 잘려서 "이게 전부"로 오판되면
#      close.py 의 백필 로직이 이미 있는 날짜를 다시 채우거나 빠뜨릴 수
#      있다. 지금 페이지네이션을 구현하진 않되, 상한에 닿으면 최소한 눈에
#      보이게 죽도록 트립와이어를 둔다.
def test_list_dir_1000개_상한에_닿으면_에러를_낸다(monkeypatch):
    가짜목록 = [{"name": f"{i}.json", "type": "file"} for i in range(1000)]
    monkeypatch.setattr(gh, "_api", lambda m, p, payload=None: 가짜목록)
    with pytest.raises(RuntimeError):
        gh.list_dir("history")


def test_list_dir_999개는_아직_정상이다(monkeypatch):
    가짜목록 = [{"name": f"{i}.json", "type": "file"} for i in range(999)]
    monkeypatch.setattr(gh, "_api", lambda m, p, payload=None: 가짜목록)
    assert len(gh.list_dir("history")) == 999


# ---------------------------------------------------------------------------
# 6)/M4/M5 — _contents_url 인코딩이 실제로 read_json/write_json/list_dir 에
# 배선돼 있는지, ?ref= 가 읽기 경로에 항상 붙는지
# ---------------------------------------------------------------------------

def test_contents_url은_경로_세그먼트를_퍼센트_인코딩한다():
    assert gh._contents_url("quotes.json") == f"/repos/{gh.REPO}/contents/quotes.json"
    assert (gh._contents_url("history/2026-08-19.json")
            == f"/repos/{gh.REPO}/contents/history/2026-08-19.json")
    assert (gh._contents_url("weird name.json")
            == f"/repos/{gh.REPO}/contents/weird%20name.json")


# M4) write_json 의 payload["branch"] 는 이미 제공된 테스트가 고정하지만,
#     읽기 쪽(read_json/list_dir) URL 에 ?ref={BRANCH} 가 붙는지는 아무
#     것도 안 고정하고 있었다 — 빠뜨려도 조용히 main 에서 읽어온다. 정확한
#     문자열을 통째로 비교해 빠짐을 못 지나가게 한다.
def test_read_json은_ref_쿼리를_반드시_붙인다(monkeypatch):
    captured = {}

    def 가짜(method, path, payload=None):
        captured["path"] = path
        raise gh.NotFound(path)

    monkeypatch.setattr(gh, "_api", 가짜)
    gh.read_json("quotes.json", default=None)
    assert captured["path"] == f"/repos/{gh.REPO}/contents/quotes.json?ref={gh.BRANCH}"


def test_list_dir은_ref_쿼리를_반드시_붙인다(monkeypatch):
    captured = {}

    def 가짜(method, path, payload=None):
        captured["path"] = path
        return []

    monkeypatch.setattr(gh, "_api", 가짜)
    gh.list_dir("history")
    assert captured["path"] == f"/repos/{gh.REPO}/contents/history?ref={gh.BRANCH}"


# M5) `_contents_url` 이 단위 테스트로만 옳고 실제 read_json/write_json 에
#     안 꽂혀 있어도(예: 예전처럼 인라인 f-string 으로 되돌려도) 안전한
#     경로("quotes.json" 등)에서는 결과 문자열이 똑같아서 위 pinning
#     테스트로는 못 잡는다. 공백처럼 인코딩이 실제로 달라지는 경로를
#     read_json 을 통해 직접 흘려보내야 "배선까지" 확인된다.
def test_read_json도_공백_섞인_경로를_인코딩해서_내려보낸다(monkeypatch):
    captured = {}

    def 가짜(method, path, payload=None):
        captured["path"] = path
        raise gh.NotFound(path)

    monkeypatch.setattr(gh, "_api", 가짜)
    gh.read_json("weird name.json", default=None)
    assert captured["path"] == f"/repos/{gh.REPO}/contents/weird%20name.json?ref={gh.BRANCH}"


def test_write_json도_contents_url을_통해_경로를_내려보낸다(monkeypatch):
    captured = {}

    def 가짜(method, path, payload=None):
        captured["path"] = path
        return {"commit": {"sha": "x"}}

    monkeypatch.setattr(gh, "_api", 가짜)
    gh.write_json("history/2026-08-19.json", {"a": 1}, sha=None, message="m")
    assert captured["path"] == f"/repos/{gh.REPO}/contents/history/2026-08-19.json"


# ---------------------------------------------------------------------------
# M6 — write_json 이 조립하는 content: 한글 이스케이프 금지, 끝에 개행
# ---------------------------------------------------------------------------

# ensure_ascii=False 는 positions.json 을 사람이 diff 로 직접 대조한다는
# 전제와 직결된다 — 종목명이 \uXXXX 로 나오면 그 자리에서 못 읽는다.
def test_write_json은_한글을_이스케이프하지_않는다(monkeypatch):
    본 = {}
    monkeypatch.setattr(
        gh, "_api",
        lambda m, p, payload=None: (본.update(payload), {"commit": {"sha": "x"}})[1])
    gh.write_json("positions.json", {"종목명": "삼성전자"}, sha=None, message="m")
    raw = base64.b64decode(본["content"]).decode("utf-8")
    assert "삼성전자" in raw
    assert "\\u" not in raw


def test_write_json_content는_끝에_개행을_둔다(monkeypatch):
    본 = {}
    monkeypatch.setattr(
        gh, "_api",
        lambda m, p, payload=None: (본.update(payload), {"commit": {"sha": "x"}})[1])
    gh.write_json("quotes.json", {"k": 1}, sha=None, message="m")
    raw = base64.b64decode(본["content"]).decode("utf-8")
    assert raw.endswith("\n")


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


# I2) sha 가 낡았을 때 GitHub 는 409 를 준다(실측: 몸통에
#     `"_scratch.json does not match 0000..."` 같은 구체적 사유가 실려온다).
#     원래는 urllib.error.HTTPError 를 그대로 다시 던졌는데, str(e) 가
#     "HTTP Error 409: Conflict" 뿐이라 어떤 경로가 실패했는지, 실제 사유가
#     뭔지가 로그에서 사라진다 — write_json(f"history/{day}.json", ...) 처럼
#     경로가 매번 다른 호출에서는 특히 치명적이다. 이제 method·path·상태
#     코드·몸통(500자까지)을 담은 RuntimeError 로 바뀐다 — 여전히 조용히
#     삼키지 않고 눈에 보이게 죽지만, 죽는 이유가 로그에 남는다.
def test_api_409는_경로와_본문을_담아_RuntimeError로_올라간다(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    body = b'{"message": "_scratch.json does not match 0000000000000000000000000000000000abcd"}'

    def 가짜_urlopen(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, 409, "Conflict", {}, io.BytesIO(body))

    monkeypatch.setattr(gh.urllib.request, "urlopen", 가짜_urlopen)
    with pytest.raises(RuntimeError) as exc_info:
        gh._api("PUT", "/repos/x/y/contents/quotes.json", {"a": 1})
    msg = str(exc_info.value)
    assert "quotes.json" in msg
    assert "409" in msg
    assert "does not match" in msg
    assert exc_info.value.__cause__ is not None   # from e — 원본 HTTPError 를 안 잃는다


def test_api_422도_경로와_본문을_담아_RuntimeError로_올라간다(monkeypatch):
    """sha 없이 기존 파일을 덮어쓰려 하면 422 — 이것도 같은 취급을 받아야 한다."""
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    body = b'{"message": "Invalid request.\\n\\n\\"sha\\" wasn\'t supplied."}'

    def 가짜_urlopen(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, 422, "Unprocessable Entity", {}, io.BytesIO(body))

    monkeypatch.setattr(gh.urllib.request, "urlopen", 가짜_urlopen)
    with pytest.raises(RuntimeError) as exc_info:
        gh._api("PUT", "/repos/x/y/contents/positions.json", {"a": 1})
    msg = str(exc_info.value)
    assert "positions.json" in msg
    assert "422" in msg
    assert "wasn't supplied" in msg


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
