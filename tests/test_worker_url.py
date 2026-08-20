# -*- coding: utf-8 -*-
"""app.js 의 WORKER_URL 과 index.html 의 CSP connect-src 가 어긋나지 않게 못박는다.

**왜 있나**

이 주소는 **손으로 두 곳을 같이** 고쳐야 하는 값이다(worker/README.md 4단계).
한 곳만 고치면 브라우저가 CSP 로 fetch 를 막는데, app.js 의 tryWorker() 는 그
실패를 "Worker 에 연결 못 함"과 구분하지 않고 **깃허브 폴백으로 조용히
넘어간다.** 결과가 고약하다 —

- 화면은 멀쩡히 동작한다. 저장도 된다(깃허브 탭이 열릴 뿐).
- 경고도, 배지도, 콘솔 오류 말고는 아무 표시도 없다.
- 즉 **Worker 를 배포해놓고 한 번도 안 쓰는 상태**를 사용자가 알 길이 없다.

`test_index_html.py` 가 잡은 "숨겨진 required" 와 같은 계열이다: 검증이 틀린 게
아니라 **검증이 닿지 않는 층**에서 조용히 새는 종류.

자리표시자 상태(미배포)도 정상이므로 "채워져 있을 것"은 요구하지 않는다 —
요구하는 건 오직 **두 곳이 서로 같을 것** 하나다.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = ROOT / "app.js"
INDEX = ROOT / "index.html"

# isWorkerConfigured() 가 "아직 미설정"을 판단하는 문자열. 이게 바뀌면 배포
# 후에도 영원히 "미설정"으로 오판하거나 그 반대가 된다.
SENTINEL = "REPLACE_WITH_YOUR_WORKER_URL"

WORKER_URL_RE = re.compile(r'^const WORKER_URL = "([^"]*)";', re.M)
CSP_RE = re.compile(
    r'http-equiv="Content-Security-Policy"\s*content="([^"]*)"', re.S)


def worker_url(app_js: str) -> str:
    m = WORKER_URL_RE.search(app_js)
    assert m, "app.js 에서 `const WORKER_URL = \"...\";` 를 못 찾았다"
    return m.group(1)


def connect_src(html: str) -> str:
    m = CSP_RE.search(html)
    assert m, "index.html 에서 Content-Security-Policy meta 를 못 찾았다"
    for part in m.group(1).split(";"):
        part = part.strip()
        if part.startswith("connect-src"):
            return part
    raise AssertionError("CSP 에 connect-src 지시자가 없다")


def host_of(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0]


# ── 실제 파일 ───────────────────────────────────────────────────────────

def test_worker_주소가_csp에_허용돼_있다():
    host = host_of(worker_url(APP_JS.read_text(encoding="utf-8")))
    allowed = connect_src(INDEX.read_text(encoding="utf-8"))
    assert host in allowed, (
        f"app.js 의 WORKER_URL 호스트({host})가 index.html 의 CSP connect-src 에 없다.\n"
        f"  connect-src: {allowed}\n"
        "이러면 브라우저가 저장 요청을 CSP 로 막고, 화면은 아무 경고 없이\n"
        "깃허브 폴백으로 넘어간다 — Worker 를 배포해놓고 안 쓰는 상태가 된다.\n"
        "worker/README.md 4단계대로 app.js 와 index.html 두 곳을 같이 고칠 것.")


def test_미설정_판별_문자열이_살아있다():
    """이 문자열이 사라지면 isWorkerConfigured() 가 늘 True 를 낸다."""
    app_js = APP_JS.read_text(encoding="utf-8")
    assert f'WORKER_URL.includes("{SENTINEL}")' in app_js, (
        f"isWorkerConfigured() 의 판별 문자열({SENTINEL})이 없어졌다 — "
        "미배포 상태에서도 Worker 로 fetch 를 시도하게 된다.")


def test_자리표시자가_주소로_남아있지_않다():
    """판별용으로 쓰는 건 정상이지만, WORKER_URL 자체가 자리표시자면 미배포다."""
    url = worker_url(APP_JS.read_text(encoding="utf-8"))
    if SENTINEL in url:
        pytest.skip("Worker 미배포 상태(자리표시자) — 두 곳 일치만 지키면 된다")


# ── 검사기 자체가 진짜로 잡는지 못박는다 ────────────────────────────────
# 아무것도 못 찾는 검사기는 없는 것보다 나쁘다.

CSP_TMPL = ('<meta http-equiv="Content-Security-Policy"\n'
            '      content="default-src \'self\'; connect-src \'self\' {}; '
            'script-src \'self\'">')


@pytest.mark.parametrize("js_host, html_host", [
    ("worker-a.example.workers.dev", "worker-b.example.workers.dev"),  # 다른 주소
    ("worker-a.example.workers.dev", "REPLACE_WITH_YOUR_WORKER_URL"),  # 한 곳만 고침
    ("REPLACE_WITH_YOUR_WORKER_URL", "worker-a.example.workers.dev"),  # 반대로 한 곳만
])
def test_검사기가_어긋남을_잡는다(js_host, html_host):
    js = f'const WORKER_URL = "https://{js_host}";'
    html = CSP_TMPL.format(f"https://{html_host}")
    assert host_of(worker_url(js)) not in connect_src(html), \
        f"놓쳤다: {js_host} vs {html_host}"


def test_검사기가_일치를_통과시킨다():
    h = "worker-a.example.workers.dev"
    js = f'const WORKER_URL = "https://{h}";'
    html = CSP_TMPL.format(f"https://{h}")
    assert host_of(worker_url(js)) in connect_src(html)


def test_connect_src_가_없으면_잡는다():
    html = ('<meta http-equiv="Content-Security-Policy"\n'
            '      content="default-src \'self\'; script-src \'self\'">')
    with pytest.raises(AssertionError):
        connect_src(html)


def test_다른_지시자에_들어있는_주소를_connect_src로_오인하지_않는다():
    """img-src 에만 있는 주소를 통과시키면 검사가 헛돈다."""
    h = "worker-a.example.workers.dev"
    html = ('<meta http-equiv="Content-Security-Policy"\n'
            f'      content="default-src \'self\'; img-src https://{h}; '
            'connect-src \'self\'">')
    assert h not in connect_src(html)
