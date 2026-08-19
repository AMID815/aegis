# -*- coding: utf-8 -*-
"""data 브랜치 파일 읽기/쓰기.

**Contents API PUT 만 쓴다.** 항상 현재 head 위에 커밋을 얹으므로 브랜치를
되감을 수 없다 — git push --force 나 reset 재시도로 기록이 사라지는 경로가 없다.

⚠ `REPO` 의 기본값(AMID815/mouigosa)은 **실제 운영 저장소**다. `GITHUB_TOKEN`
이 로컬 환경에 설정된 채로 이 모듈을 실행하면(예: 개발 PC에서 `python -m
scripts.close`) 진짜 저장소에 쓴다 — 지금 이걸 막는 유일한 방지선은 사용자가
로컬에 PAT 를 두지 않아서 `_token()` 이 먼저 RuntimeError 를 내는 것뿐이다.

실측 메모(2026-08-19, AMID815/mouigosa `data` 브랜치, 스크래치 커밋 후 삭제로
확인 — 자세한 절차는 Task 5 구현 커밋 메시지 참조):

- **author 기본값**: `committer` 만 주고 `author` 를 생략하면, GitHub 는
  `author` 를 `committer` 값으로 채운다 — 토큰 소유자(실제 사람 계정)의
  이메일이 아니다. `.keep` 커밋(사용자가 git 으로 직접 만든 것)은 실제
  이메일이 남아있지만, 이 모듈이 쓰는 API 경로는 그렇지 않다. 그래서
  `author` 는 별도로 안 보낸다 — `committer` 하나로 둘 다 정해진다.
- **디렉토리 목록 상한**: Contents API 로 디렉토리를 조회하면 최대 1,000개
  항목까지만 오고 페이지네이션이 없다(공식 문서: "This API has an upper
  limit of 1,000 files for a directory" — 넘으면 Git Trees API 로 가라고
  안내한다). `history/`는 거래일마다 하나씩 쌓인다 — 연 250여 개면 1,000개는
  대략 4년 뒤(2030년경)에나 닿는다. 지금 페이지네이션을 구현하진 않지만,
  `list_dir` 은 상한에 닿으면(999개가 아니라 1,000개째부터) 조용히 자르는
  대신 에러를 낸다 — close.py 의 history/ 백필 로직이 "더 볼 필요 없다"로
  오판하면 이미 있는 날짜를 다시 채우거나 반대로 빠뜨릴 수 있어서다.
- **파일 크기**: 읽기는 **1MB 미만**까지만 `content` 가 base64 로 채워진다
  (1~100MB는 raw 미디어 타입으로만 접근 가능하고, 이 경로로 받으면
  `encoding` 이 `"none"`, `content` 가 빈 문자열로 온다 — 100MB 초과는 아예
  미지원). 실측 확인(2026-08-19): 1,017,782바이트는 정상적으로
  `encoding: "base64"` 로 오고, 1,537,782바이트는 `encoding: "none"` +
  `content: ""` 로 온다. `read_json` 은 이 신호를 명시적으로 확인한다 —
  확인하지 않으면 `base64.b64decode("")` → `b""` → `json.loads("")` 가
  `ValueError` 를 내고, 그게 "JSON 이 깨졌다"와 똑같은 코드 경로를 타서
  **멀쩡한 대용량 파일이 sha 를 가진 채로 default 로 조용히 대체된다** —
  다음 write_json 이 그 default 를 그 sha 위에 얹으면 진짜 삭제가 영구히
  커밋된다. 그래서 이 검사는 strict 여부와 무관하게 항상 켜져 있다.
  master.json(~130KB)은 1MB 상한의 1/8 수준이라 여유가 크지만, 이 상한
  자체는 코드가 명시적으로 다룬다 — 문서화만으로는 안 지켜진다.
- **409(sha 충돌) 및 그 외 4xx/5xx**: sha 가 낡으면 GitHub 는 409 를 준다
  (실측: `PUT` 에 틀린 sha 를 주면 `409 Conflict`, 몸통에
  `"_scratch.json does not match 0000..."` 같은 구체적 사유가 실려온다).
  세 writer(intake/quotes/close)가 `concurrency: data-write` 그룹으로
  직렬화돼 있어서 같은 실행 안에서 스스로 409를 낼 일은 없다 — 사람이
  data 브랜치를 손으로 건드리는 등 바깥 요인일 때만 난다. 그럴 땐 조용히
  삼키지 않고 워크플로우가 눈에 보이게 실패하는 게 맞다 — 다만
  `urllib.error.HTTPError` 를 그대로 다시 던지면 `str(e)` 가
  `"HTTP Error 409: Conflict"` 뿐이라 실패 로그에 **어떤 경로**(`path`)가
  실패했는지, 몸통에 실린 실제 사유가 뭔지 안 남는다(`e.read()` 는 한 번
  읽으면 사라지므로 여기서 안 읽으면 영영 잃는다). 그래서 `_api` 는 404 만
  `NotFound` 로 바꾸고, 나머지는 method·path·상태코드·몸통을 담은
  `RuntimeError` 로 다시 던진다.
- **속도 제한**: `GITHUB_TOKEN` 은 저장소당 시간당 1,000 요청. quotes(30분
  간격, 장중), close(하루 두 번), intake(이슈당) 를 다 합쳐도 하루 수십
  건 수준이라 여유가 크다.

**positions.json 은 항상 strict.** `read_json` 에 `strict=True` 를 넘기면
JSON 이 깨졌을 때 default 로 조용히 대체하는 대신 `CorruptJSON` 을 올린다.
그런데 이 플래그를 파일이 아니라 **호출**에 붙이면, positions.json 을 건드릴
모든 호출자(Task 6 intake, 그리고 나중에 참고삼아 읽을 수도 있는 다른
스크립트)가 매번 잊지 않고 챙겨야 한다 — 하나라도 빠뜨리면 이 파일이
가진 유일한 보호가 사라진다. 그래서 `IRREPLACEABLE` 에 오른 경로는 `strict`
인자를 안 줘도(두 인자짜리 평범한 호출이어도) 항상 예외를 올린다 — 파일이
결정하지, 호출자가 결정하지 않는다. `strict` 파라미터 자체는 남겨둔다 —
나중에 다른 파일이 같은 보호가 필요해지면 즉석에서 쓸 수 있게.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

REPO = os.environ.get("GITHUB_REPOSITORY", "AMID815/mouigosa")
BRANCH = os.environ.get("DATA_BRANCH", "data")
API = "https://api.github.com"
COMMITTER = {"name": "mouigosa-bot",
             "email": "41898282+github-actions[bot]@users.noreply.github.com"}

POSITIONS = "positions.json"
# 손으로 입력한 매매 기록 — 값을 잃으면 되살릴 방법이 없는 유일한 파일.
# read_json 이 strict 인자와 무관하게 항상 지킨다.
IRREPLACEABLE = frozenset({POSITIONS})


class NotFound(Exception):
    pass


class CorruptJSON(Exception):
    """JSON 파싱이 깨진 파일을 `read_json` 이 default 로 숨기지 않고 올릴 때.

    (positions.json 같은 `IRREPLACEABLE` 파일은 항상, 그 외 파일은
    `strict=True` 일 때만.) sha 를 들고 있는 건 "복구에 써라"는 뜻이지
    "이걸로 다시 write_json 해서 지워도 된다"는 뜻이 아니다 — 메시지에
    복구 경로(git/blobs)를 박아 sha 가 초대장이 아니라 지시문으로 읽히게
    한다.
    """

    def __init__(self, path: str, sha: str):
        self.path = path
        self.sha = sha
        super().__init__(f"{path}: 손상된 JSON — 복구: gh api repos/{REPO}/git/blobs/{sha}")


def _token() -> str:
    t = os.environ.get("GITHUB_TOKEN")
    if not t:
        raise RuntimeError("GITHUB_TOKEN 없음")
    return t


def _api(method: str, path: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {_token()}")
    req.add_header("Accept", "application/vnd.github+json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound(path)
        # e.read() 는 한 번 읽으면 스트림이 소진된다 — 여기서 안 담으면
        # 어떤 경로가, 왜 실패했는지가 로그에서 영영 사라진다.
        body = e.read()[:500].decode("utf-8", "replace")
        raise RuntimeError(f"{method} {path} -> {e.code}: {body}") from e


def _contents_url(path: str) -> str:
    """`/repos/{REPO}/contents/{path}` 를 세그먼트 단위로 퍼센트 인코딩해 조립.

    지금 호출자는 전부 안전한 상수("positions.json")나 ISO 날짜
    ("history/2026-08-19.json")라 실질적 위험은 없지만, `/` 는 경로
    구분자로 남기고 세그먼트만 인코딩해야 하위 경로가 안 깨진다 — 문자열
    전체를 그냥 quote() 하면 `/` 까지 인코딩돼 버린다.
    """
    encoded = "/".join(urllib.parse.quote(seg, safe="") for seg in path.split("/"))
    return f"/repos/{REPO}/contents/{encoded}"


def read_json(path: str, default=None, *, strict: bool = False):
    """(내용, sha). 없으면 (default, None).

    깨졌으면: `path` 가 `IRREPLACEABLE` 이거나 `strict=True` 면
    `CorruptJSON` 을 올린다. 그 외(quotes/master/history 처럼 재생성 가능한
    파일)는 (default, sha) 로 회수한다 — 그래야 호출자가 그 sha 위에
    새로 정상적인 내용을 다시 써서 자체 치유할 수 있다.

    1MB 이상이라 GitHub 가 `content` 를 안 채워 보낸 경우는 이것과 다른
    문제다(파일이 깨진 게 아니라 API 응답 형식이 다른 것) — strict 여부와
    무관하게 항상 예외를 낸다. 자세한 이유는 모듈 docstring 참조.
    """
    try:
        r = _api("GET", f"{_contents_url(path)}?ref={BRANCH}")
    except NotFound:
        return default, None
    if r.get("encoding") != "base64":
        raise RuntimeError(
            f"{path}: content 없음 (encoding={r.get('encoding')!r}, "
            f"size={r.get('size')}) — 1MB 초과로 추정, read_json 이 처리 못 함")
    raw = base64.b64decode(r["content"])
    try:
        return json.loads(raw.decode("utf-8")), r["sha"]
    except (ValueError, UnicodeDecodeError):
        if strict or path in IRREPLACEABLE:
            raise CorruptJSON(path, r["sha"])
        return default, r["sha"]


def write_json(path: str, body, sha: str | None, message: str):
    # ensure_ascii=False 는 장식이 아니다 — positions.json 은 사람이 diff 로
    # 직접 대조하는 파일이라, 종목명이 \uXXXX 로 이스케이프되면 그 자리에서
    # 못 읽는다. 끝에 개행을 붙이는 것도 장식이 아니다 — 없으면 모든 diff가
    # "\ No newline at end of file" 을 달고 나와 실제 변경과 섞여 보인다.
    content = json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode(),
        "branch": BRANCH,
        "committer": COMMITTER,
    }
    if sha:
        payload["sha"] = sha
    return _api("PUT", _contents_url(path), payload)


def list_dir(path: str) -> list:
    """path 아래 이름 목록(파일·하위 디렉토리 모두 포함). 없으면 빈 리스트.

    `history/`는 하위 디렉토리를 두지 않는 평평한 구조라 지금은
    type=="file" 로 거를 이유가 없다 — 필터링이 필요해지면 그때 추가한다.

    path 가 디렉토리가 아니라 파일이면 Contents API 는 리스트가 아니라
    dict 하나를 돌려준다 — 그걸 그냥 순회하면(파이썬 dict 순회는 키만 돌기
    때문에) isinstance 체크에 전부 걸려 조용히 빈 리스트가 나온다. 그건
    "디렉토리가 비었다"와 구분이 안 돼서 위험하다(예: close.py 의
    history/ 백필 로직이 "기존 기록 없음"으로 오판) — 그래서 명시적으로
    막는다.

    항목이 1,000개(Contents API 상한, 모듈 docstring 참조)에 닿으면 그
    이상은 응답에 안 실려온다 — 자른 목록을 "이게 전부"로 취급하면 이미
    있는 파일이 없는 것처럼 보여서 위험하므로 조용히 넘기지 않고 에러를
    낸다.
    """
    try:
        r = _api("GET", f"{_contents_url(path)}?ref={BRANCH}")
    except NotFound:
        return []
    if not isinstance(r, list):
        raise NotADirectoryError(f"{path} 는 디렉토리가 아니라 파일이다")
    if len(r) >= 1000:
        raise RuntimeError(
            f"{path}: 목록이 1,000개 상한에 닿음 — Contents API 페이지네이션 "
            f"없음, Git Trees API 로 전환 필요")
    return [x["name"] for x in r if isinstance(x, dict)]
