# -*- coding: utf-8 -*-
"""worker.js 를 흉내내는 로컬 개발용 스텁 — **배포용이 아니다.**

실제 Cloudflare Worker 를 아직 배포하지 않은 상태에서도 index.html/app.js 의
Worker 연동 경로(성공/틀린 패스프레이즈/네트워크 실패)를 브라우저로 직접
눌러가며 확인하기 위한 도구다. 진짜 깃허브 이슈를 만들지 않는다 — PAT 도,
네트워크 호출도 전혀 없다. 콘솔에 "이렇게 이슈를 만들었을 것이다"만 찍는다.

스펙(worker/worker.js 와 최대한 같게 맞춘 부분):
  - OPTIONS → CORS 프리플라이트
  - POST 만 허용, 그 외 405
  - {pass, payload, display} JSON 을 읽는다
  - pass 가 DEV_GATE_PASS(기본 "devpass", 환경변수로 바꿀 수 있음)와 다르면 401
  - payload 가 object 이고 op 가 buy/sell/amend 중 하나가 아니면 400
  - 통과하면 {ok:true, number, url} 을 돌려준다(번호는 매 요청마다 증가)

사용법:
  python worker/devstub.py [포트(기본 8793)]
  (다른 패스프레이즈로 테스트하려면) DEV_GATE_PASS=내문구 python worker/devstub.py

app.js 의 WORKER_URL 을 이 스텁 주소(예: http://localhost:8793)로 임시로
바꾸고, index.html 의 CSP connect-src 에도 같은 주소를 임시로 추가해야
브라우저가 요청을 허용한다 — 둘 다 검증이 끝나면 원래 자리표시자로 되돌릴
것(실제 배포 전용 자리표시자를 커밋에 남겨야 한다).
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Windows 콘솔이 한글 로캘이면 기본 코드페이지가 cp949 라, 이 파일이 찍는
# 한글 로그(제목·본문·시작 배너)가 UnicodeEncodeError 로 죽는다 — 실제로
# 이 작업의 로컬 검증 중 그렇게 죽는 걸 봤다(devstub 는 개발 도구인데 정작
# 로그를 못 찍고 죽으면 개발 도구로서 쓸모가 없다). UTF-8 로 강제하고,
# 그래도 표현 못 하는 문자가 있으면(극히 드묾) 깨뜨리는 대신 대체 문자로
# 바꿔치기한다 — 로그 한 줄 때문에 스텁 전체가 죽는 것보다 낫다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # 리다이렉트 등으로 reconfigure 가 안 되는 드문 환경 — 조용히 넘어간다

DEV_GATE_PASS = os.environ.get("DEV_GATE_PASS", "devpass")
KNOWN_OPS = {"buy", "sell", "amend"}
OP_LABEL = {"buy": "BUY", "sell": "SELL", "amend": "AMEND"}

_counter = 1000  # worker.js 와 헷갈리지 않게 실제 이슈 번호대와 겹치지 않는 범위에서 시작


def _normalize(s: str) -> str:
    return unicodedata.normalize("NFC", s.strip()) if isinstance(s, str) else ""


def _build_title(payload: dict, display) -> str:
    label = OP_LABEL.get(payload.get("op"), "WRITE")
    name = display if isinstance(display, str) else ""
    name = re.sub(r"[\r\n]+", " ", name).strip()[:60]
    if not name:
        name = payload.get("name") or payload.get("code") or "?"
    return f"{label} {name}"[:200]


def _build_body(payload: dict) -> str:
    # scripts/intake.py 의 FENCE 정규식이 요구하는 모양과 정확히 같게 —
    # 실제 worker.js 의 buildBody() 와 동일한 문자열.
    return "모의고사 입력\n\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


class Handler(BaseHTTPRequestHandler):
    # 기본 로그 포맷이 시끄러워 조용한 커스텀 로그로 바꾼다.
    def log_message(self, fmt, *args):
        sys.stderr.write("[devstub] " + (fmt % args) + "\n")

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")  # 로컬 전용 — 배포판은 오리진 하나만 허용한다
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")

    def _json(self, status: int, obj: dict):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors_headers()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        self._json(405, {"ok": False, "error": "POST만 허용합니다."})

    def do_POST(self):
        global _counter
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""

        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"ok": False, "error": "JSON 파싱 실패."})
            return
        if not isinstance(body, dict):
            self._json(400, {"ok": False, "error": "요청 형식이 올바르지 않습니다."})
            return

        pas = body.get("pass")
        if _normalize(pas if isinstance(pas, str) else "") != _normalize(DEV_GATE_PASS):
            self._json(401, {"ok": False, "error": "인증 실패."})
            return

        payload = body.get("payload")
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("op"), str)
            or payload.get("op") not in KNOWN_OPS
        ):
            self._json(400, {"ok": False, "error": "payload 형식이 올바르지 않습니다."})
            return

        title = _build_title(payload, body.get("display"))
        issue_body = _build_body(payload)
        _counter += 1
        print(f"[devstub] 이슈 생성 시뮬레이션 #{_counter}")
        print(f"[devstub]   title: {title}")
        print(f"[devstub]   body:\n{issue_body}")
        self._json(
            201,
            {
                "ok": True,
                "number": _counter,
                "url": f"https://github.com/AMID815/aegis/issues/{_counter}",
            },
        )


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8793
    print(f"[devstub] worker.js 흉내 — 실제 배포 아님. 포트 {port}, DEV_GATE_PASS={DEV_GATE_PASS!r}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
