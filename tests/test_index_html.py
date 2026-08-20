# -*- coding: utf-8 -*-
"""index.html 정적 검사 — 숨겨진 required 가 폼 전체를 막는 것을 잡는다.

**이 검사가 왜 있나 (2026-08-20 실사고)**

`#exit-price`·`#exit-date` 에 `required` 를 정적으로 달아뒀는데, 그 필드를 감싼
`div` 가 `hidden`(= `display:none !important`) 이었다. HTML5 제약 검사는 포커스할 수
없는 컨트롤에서 실패하고, **`submit` 이벤트를 아예 발생시키지 않는다.** 그래서
매수·매도·매도기록 없는 종목의 고치기가 전부 죽었는데 —

- 사용자에게는 **아무것도 안 보인다.** 탭도, 알림도, 배지도 없다.
- 콘솔에만 `An invalid form control with name='' is not focusable.`

페이로드를 만들어 실제 서버 코드에 재생하는 검증은 **전부 통과했다.**
`form.dispatchEvent(new Event("submit"))` 가 제약 검사를 건너뛰기 때문이다.
즉 검증이 틀린 게 아니라 **검증이 닿지 않는 층**이 있었다.

지금은 `app.js` 의 `setExitFieldsVisible()` 이 `hidden` 과 `required` 를 같이 켜고
끈다. 이 테스트는 앞으로 **새로 추가되는 필드**가 같은 실수를 반복하지 않게 막는다.

**면제 두 가지** (진짜로 제약 검사에서 빠지므로 오탐이 된다):
- `disabled` 컨트롤
- `type="hidden"` 입력
"""
from __future__ import annotations

import pathlib
from html.parser import HTMLParser

import pytest

INDEX = pathlib.Path(__file__).resolve().parent.parent / "index.html"

# 자식을 가질 수 없는 요소 — 스택에 쌓지 않는다
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "source", "track", "wbr"}


class _RequiredUnderHidden(HTMLParser):
    """`required` 인데 조상(또는 자신)이 `hidden` 인 컨트롤을 모은다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None]] = []   # (태그, 그 조상의 hidden 식별자)
        self.hits: list[str] = []

    @staticmethod
    def _label(tag: str, attrs: dict) -> str:
        ident = attrs.get("id") or attrs.get("name") or attrs.get("class")
        return f"<{tag} {ident}>" if ident else f"<{tag}>"

    def _hidden_ancestor(self) -> str | None:
        for _, hidden_label in reversed(self.stack):
            if hidden_label:
                return hidden_label
        return None

    def _check(self, tag: str, attrs: dict) -> None:
        if "required" not in attrs:
            return
        # 제약 검사에서 진짜로 빠지는 것들은 막지 않는다
        if "disabled" in attrs or attrs.get("type") == "hidden":
            return
        blocker = self._label(tag, attrs) if "hidden" in attrs else self._hidden_ancestor()
        if blocker:
            self.hits.append(f"{self._label(tag, attrs)} — 숨긴 쪽: {blocker}")

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self._check(tag, d)
        if tag not in VOID:
            self.stack.append((tag, self._label(tag, d) if "hidden" in d else None))

    def handle_startendtag(self, tag, attrs):
        self._check(tag, dict(attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return


def _offenders(html: str) -> list[str]:
    p = _RequiredUnderHidden()
    p.feed(html)
    return p.hits


def test_숨겨진_required_가_없다():
    """있으면 폼이 통째로 제출 불가가 되고, 사용자에게는 아무것도 안 보인다."""
    hits = _offenders(INDEX.read_text(encoding="utf-8"))
    assert hits == [], (
        "hidden 컨테이너 안에 required 컨트롤이 있다 — 이러면 submit 이벤트가\n"
        "아예 발생하지 않고 화면에는 아무 표시도 안 난다. required 는 정적으로 두지 말고\n"
        "app.js 의 setExitFieldsVisible() 처럼 hidden 과 함께 켜고 꺼야 한다:\n  "
        + "\n  ".join(hits))


# ── 검사기 자체가 진짜로 잡는지 못박는다 ────────────────────────────────
# 아무것도 못 찾는 검사기는 없는 것보다 나쁘다. 위 테스트가 통과하는 이유가
# "index.html 이 깨끗해서" 인지 "검사기가 눈이 멀어서" 인지 구분해야 한다.

@pytest.mark.parametrize("html", [
    '<div hidden><input id="a" required></div>',                 # 부모가 hidden
    '<div hidden><span><input id="a" required></span></div>',    # 조상이 hidden
    '<input id="a" required hidden>',                            # 자기 자신이 hidden
    '<div hidden><select id="a" required><option>x</option></select></div>',
    '<div hidden><textarea id="a" required></textarea></div>',
])
def test_검사기가_숨겨진_required_를_잡는다(html):
    assert _offenders(html), f"놓쳤다: {html}"


@pytest.mark.parametrize("html", [
    '<div><input id="a" required></div>',                        # 안 숨겨짐
    '<div hidden><input id="a"></div>',                          # required 아님
    '<div hidden><input id="a" required disabled></div>',        # disabled 는 검사 면제
    '<div hidden><input id="a" type="hidden" required></div>',   # type=hidden 도 면제
    '<div hidden><input id="a"></div><input id="b" required>',   # 닫힌 뒤는 영향 없음
])
def test_검사기가_멀쩡한_것을_잡지_않는다(html):
    assert _offenders(html) == [], f"오탐: {html}"


def test_index_html_이_실제로_읽힌다():
    """경로가 틀려 빈 문자열을 검사하면 위 테스트가 공짜로 통과한다."""
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="price"' in html and 'id="exit-price"' in html, INDEX
