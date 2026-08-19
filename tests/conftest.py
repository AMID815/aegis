# -*- coding: utf-8 -*-
"""테스트 전역 안전장치 (리뷰 A4).

`gh.py` 모듈 docstring 이 명시한다: `REPO` 의 기본값(AMID815/mouigosa)은
**실제 운영 저장소**이고, 로컬 환경에 `GITHUB_TOKEN` 이 설정된 채로
`gh` 를 실행하면 진짜 저장소에 쓴다 — 지금 이걸 막는 유일한 방지선은
사용자가 로컬에 PAT 를 두지 않아서 `_token()` 이 먼저 `RuntimeError` 를
내는 것뿐이다.

quotes.py 의 `main()` 처럼 entry point 자체가 테스트 대상이 된 지금,
어느 테스트가 gh.read_json/write_json 을 monkeypatch 하는 걸 깜빡해도
진짜 네트워크로 새어나가지 않게 세션 전체에 안전망을 하나 더 깐다 —
개발 PC 에 토큰이 실제로 남아 있더라도 pytest 프로세스 안에서는 지운다.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_live_github_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
