# -*- coding: utf-8 -*-
"""data 브랜치 파일 읽기/쓰기.

**Contents API PUT 만 쓴다.** 항상 현재 head 위에 커밋을 얹으므로 브랜치를
되감을 수 없다 — git push --force 나 reset 재시도로 기록이 사라지는 경로가 없다.

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
  대략 4년 뒤(2030년경)에나 닿는다. 지금 페이지네이션을 구현할 필요는 없다.
- **파일 크기**: 읽기는 1MB 까지 `content` 가 base64 로 채워진다(1~100MB는
  raw 미디어 타입으로만, 100MB 초과는 아예 미지원). master.json(~130KB)은
  1MB 상한의 1/8 수준이라 여유가 크다. 쓰기 쪽은 공식 문서에 별도 상한이
  명시돼 있지 않다 — 지금 다루는 파일 크기에서는 문제될 이유가 없다.
- **409(sha 충돌)**: sha 가 낡으면 GitHub 는 409 를 준다. 세 writer
  (intake/quotes/close)가 `concurrency: data-write` 그룹으로 직렬화돼
  있어서 같은 실행 안에서 스스로 409를 낼 일은 없다 — 사람이 data 브랜치를
  손으로 건드리는 등 바깥 요인일 때만 난다. `_api` 는 404 말고는 그대로
  다시 던지므로 409 도 그대로 올라가 워크플로우가 눈에 보이게 실패한다 —
  조용히 삼키지 않는다는 원칙과 맞아서 별도 예외로 감싸지 않았다.
- **속도 제한**: `GITHUB_TOKEN` 은 저장소당 시간당 1,000 요청. quotes(30분
  간격, 장중), close(하루 두 번), intake(이슈당) 를 다 합쳐도 하루 수십
  건 수준이라 여유가 크다.
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


class NotFound(Exception):
    pass


class CorruptJSON(Exception):
    """`read_json(..., strict=True)` 에서 JSON 파싱이 깨졌을 때.

    positions.json 처럼 복구 불가능한 파일은 "없음"과 "깨짐"을 같은 값으로
    돌려주면 안 된다 — 호출자가 default 를 그대로 다시 써버리면 깨진 원본이
    영영 사라진다. sha 를 들고 있으므로 잡은 쪽에서 (덮어쓰지 않고) 원인
    파악·수동 복구에 쓸 수 있다.
    """

    def __init__(self, path: str, sha: str):
        self.path = path
        self.sha = sha
        super().__init__(f"{path}: 손상된 JSON (sha={sha})")


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
        raise


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

    깨졌으면 기본은 (default, sha) — quotes/master/history 처럼 재생성
    가능한 파일은 이렇게 회수하는 게 맞다. `strict=True` 면 대신
    `CorruptJSON` 을 올린다 — positions.json 처럼 복구 불가능한 파일에서
    쓴다(호출자가 default 로 덮어써서 원본을 지우는 사고를 막는다).
    """
    try:
        r = _api("GET", f"{_contents_url(path)}?ref={BRANCH}")
    except NotFound:
        return default, None
    raw = base64.b64decode(r["content"])
    try:
        return json.loads(raw.decode("utf-8")), r["sha"]
    except (ValueError, UnicodeDecodeError):
        if strict:
            raise CorruptJSON(path, r["sha"])
        return default, r["sha"]


def write_json(path: str, body, sha: str | None, message: str):
    content = json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True)
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
    """path 아래 파일 이름 목록. 없으면 빈 리스트.

    path 가 디렉토리가 아니라 파일이면 Contents API 는 리스트가 아니라
    dict 하나를 돌려준다 — 그걸 그냥 순회하면(파이썬 dict 순회는 키만 돌기
    때문에) isinstance 체크에 전부 걸려 조용히 빈 리스트가 나온다. 그건
    "디렉토리가 비었다"와 구분이 안 돼서 위험하다(예: close.py 의
    history/ 백필 로직이 "기존 기록 없음"으로 오판) — 그래서 명시적으로
    막는다.
    """
    try:
        r = _api("GET", f"{_contents_url(path)}?ref={BRANCH}")
    except NotFound:
        return []
    if not isinstance(r, list):
        raise NotADirectoryError(f"{path} 는 디렉토리가 아니라 파일이다")
    return [x["name"] for x in r if isinstance(x, dict)]
