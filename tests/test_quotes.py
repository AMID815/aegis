# -*- coding: utf-8 -*-
"""quotes.py: 장중 시세 갱신 (Task 7, 리뷰 반영판).

공급된 테스트는 그대로 두고, 아래를 추가했다:

- `open_codes` 중복 제거 (구현계획.md 코드리뷰 이월 항목, Task 7 담당) —
  같은 코드가 두 번 열릴 수 있다(7월 매수 + 8월 매수, 서로 다른 id, 둘 다
  open). 중복을 그대로 두면 그 코드가 응답에서 빠졌을 때 `missing` 에
  두 번 실려 `fail_count` 가 부풀어 오른다.
- `main()` 통합 테스트 — gh/naver 를 monkeypatch 해서 네트워크 없이:
  정상 커밋, 손상 항목 경고 후 진행(§8), positions 조회 자체가 못 읽히는
  경우(구 코드는 `models.RejectedError` 만 잡아서 `gh.CorruptJSON` ·
  `RuntimeError` 는 트레이스백으로 죽었다 — 이 파일이 지향하는 "넓게
  잡고 커밋하지 않는다" 원칙과 어긋나 고쳤다), 시세/달력 실패, 전부 실패,
  quotes.json 조회 자체가 실패하는 경우(구 코드는 이 호출이 어떤 try 밖에도
  없어 마찬가지로 트레이스백으로 죽었다), 지수 하나만 실패해도 나머지는
  살아남는 부분 실패.
"""
import pytest

from scripts import gh, models, naver, quotes


# ---------------------------------------------------------------------------
# 공급된 테스트 (그대로)
# ---------------------------------------------------------------------------

def test_보유중_코드만_고른다():
    state = {"positions": [
        {"code": "005930", "status": "open"},
        {"code": "000660", "status": "closed"},
        {"code": "035720", "status": "open"},
    ]}
    assert quotes.open_codes(state) == ["005930", "035720"]


def test_스냅샷을_조립한다():
    snap = quotes.build(
        got={"005930": {"price": 247500, "name": "삼성전자", "status": "tradable"}},
        asked=["005930", "999999"],
        days=["2026-08-18", "2026-08-19"],
        bench={"KOSPI": 6471.17, "KOSDAQ": 824.46},
        now_kst="2026-08-19T13:00:00+09:00",
        is_final=False,
    )
    assert snap["ok_count"] == 1
    assert snap["fail_count"] == 1
    assert snap["missing"] == ["999999"]
    assert snap["positions_dropped"] == 0
    assert snap["is_final"] is False
    assert snap["as_of_kst"] == "2026-08-19T13:00:00+09:00"
    assert snap["quotes"]["005930"]["price"] == 247500
    assert snap["trading_days"] == ["2026-08-18", "2026-08-19"]
    assert snap["benchmark"]["KOSPI"] == pytest.approx(6471.17)


def test_전부_실패하면_커밋하지_않는다():
    """빈 quotes.json 이 올라가면 화면이 '데이터 없음' 이 아니라 '전 종목 0원' 이 된다."""
    snap = quotes.build(got={}, asked=["005930"], days=["2026-08-19"],
                        bench={}, now_kst="t", is_final=False)
    assert quotes.should_commit(snap) is False


def test_일부만_실패하면_커밋한다():
    snap = quotes.build(got={"005930": {"price": 1, "name": "n", "status": "tradable"}},
                        asked=["005930", "999999"], days=["2026-08-19"],
                        bench={}, now_kst="t", is_final=False)
    assert quotes.should_commit(snap) is True


def test_보유가_없으면_빈_스냅샷도_커밋한다():
    """들고 있는 게 없는 건 실패가 아니다 — 달력·시각은 갱신되어야 한다."""
    snap = quotes.build(got={}, asked=[], days=["2026-08-19"],
                        bench={}, now_kst="t", is_final=False)
    assert quotes.should_commit(snap) is True


def test_손상_항목_개수를_스냅샷에_싣는다():
    """로그는 아무도 안 본다 — 화면이 말하게 한다 (설계 §8)."""
    snap = quotes.build(got={}, asked=[], days=["2026-08-19"],
                        bench={}, now_kst="t", is_final=False, dropped=2)
    assert snap["positions_dropped"] == 2


# ---------------------------------------------------------------------------
# 추가 테스트 — open_codes 중복 제거 (알려진 결함, 구현계획.md 코드리뷰 이월)
# ---------------------------------------------------------------------------

def test_보유중_코드는_중복없이_고른다():
    """같은 코드가 두 번 열릴 수 있다(7월 매수 + 8월 매수, id 는 다르고 둘 다 open).

    중복을 그대로 두면 naver.missing_codes 가 asked 리스트를 그대로 훑어서
    그 코드가 응답에서 빠졌을 때 missing 에 두 번 실리고 fail_count 가
    부풀어 오른다.
    """
    state = {"positions": [
        {"id": "20260701-005930", "code": "005930", "status": "open"},
        {"id": "20260801-005930", "code": "005930", "status": "open"},
        {"id": "20260702-000660", "code": "000660", "status": "closed"},
        {"id": "20260703-035720", "code": "035720", "status": "open"},
    ]}
    assert quotes.open_codes(state) == ["005930", "035720"]


def test_중복_코드가_있어도_실패시_missing에_한번만_잡힌다():
    """dedup 이 안 됐다면 이 스냅샷의 missing 은 ["999999", "999999"] 가 되고
    fail_count 는 2 가 된다 — 실제로는 종목 하나가 빠졌을 뿐이다."""
    codes = quotes.open_codes({"positions": [
        {"id": "a", "code": "999999", "status": "open"},
        {"id": "b", "code": "999999", "status": "open"},
    ]})
    snap = quotes.build(got={}, asked=codes, days=["2026-08-19"],
                        bench={}, now_kst="t", is_final=False)
    assert snap["missing"] == ["999999"]
    assert snap["fail_count"] == 1


# ---------------------------------------------------------------------------
# 추가 테스트 — main() 통합 (gh/naver 는 전부 monkeypatch, 네트워크 없음)
# ---------------------------------------------------------------------------

정상_보유 = {"schema": 1, "positions": [
    {"id": "20260801-005930", "code": "005930", "name": "삼성전자",
     "buys": [{"date": "2026-08-01", "price": 240000}],
     "exits": [], "adjustments": [], "status": "open",
     "signal_date": None, "source": "수동", "memo": ""},
]}


def _기본_준비(monkeypatch, *, positions=None, quotes_sha="qsha",
             got=None, days=None, write_capture=None):
    """main() 이 쓰는 gh/naver 호출을 전부 결정적인 가짜로 바꾼다."""
    if positions is None:
        positions = 정상_보유
    if got is None:
        got = {"005930": {"price": 247500, "name": "삼성전자", "status": "tradable"}}
    if days is None:
        days = ["2026-08-18", "2026-08-19"]

    def 가짜_읽기(path, *a, **k):
        if path == quotes.POSITIONS:
            return positions, "psha"
        if path == quotes.QUOTES:
            return None, quotes_sha
        raise AssertionError(f"예상 못한 경로: {path}")

    monkeypatch.setattr(quotes.gh, "read_json", 가짜_읽기)

    if write_capture is not None:
        monkeypatch.setattr(
            quotes.gh, "write_json",
            lambda path, body, sha, msg: write_capture.append((path, body, sha, msg)))

    monkeypatch.setattr(quotes.naver, "fetch_quotes", lambda codes: dict(got))
    monkeypatch.setattr(quotes.naver, "fetch_trading_days", lambda n: list(days))
    monkeypatch.setattr(quotes.naver, "fetch_bars",
                        lambda sym, n=2: {"20260819": {"close": 6471.17}})


def test_main_정상_커밋(monkeypatch, capsys):
    쓴것 = []
    _기본_준비(monkeypatch, write_capture=쓴것)

    rc = quotes.main()

    assert rc == 0
    assert len(쓴것) == 1
    path, body, sha, msg = 쓴것[0]
    assert path == quotes.QUOTES
    assert sha == "qsha"
    assert body["ok_count"] == 1
    assert body["quotes"]["005930"]["price"] == 247500
    assert body["positions_dropped"] == 0
    assert body["benchmark"]["KOSPI"] == pytest.approx(6471.17)
    out = capsys.readouterr().out
    assert "완료" in out


def test_main_quotes파일이_처음이면_sha_None으로_쓴다(monkeypatch):
    """gh.read_json(QUOTES) 가 없는 파일 기본값 (default, None) 을 돌려주는
    경우 — 첫 실행. sha=None 이 그대로 write_json 에 전달돼야 새 파일로
    만들어진다(gh.write_json 은 sha 가 falsy 면 payload 에서 뺀다)."""
    쓴것 = []
    _기본_준비(monkeypatch, quotes_sha=None, write_capture=쓴것)

    rc = quotes.main()

    assert rc == 0
    assert 쓴것[0][2] is None


def test_main_손상_항목은_경고_후_진행한다(monkeypatch, capsys):
    """Task 6(intake) 은 거부하지만 Task 7 은 다르다 — quotes.json 은 재생성
    가능하므로 멈추지 않고 개수를 스냅샷에 실어 화면이 말하게 한다(§8)."""
    손상_포함 = {"schema": 1, "positions": [
        {"id": "20260801-005930", "code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-01", "price": 240000}],
         "exits": [], "adjustments": [], "status": "open",
         "signal_date": None, "source": "수동", "memo": ""},
        {"id": "깨짐", "code": "00660"},   # 5자리 — 코드 형식 오류로 격리됨
    ]}
    쓴것 = []
    _기본_준비(monkeypatch, positions=손상_포함, write_capture=쓴것)

    rc = quotes.main()

    assert rc == 0
    assert len(쓴것) == 1
    assert 쓴것[0][1]["positions_dropped"] == 1
    out = capsys.readouterr().out
    assert "경고" in out


def test_main_positions_스키마가_깨지면_중단하고_쓰지_않는다(monkeypatch, capsys):
    """구 코드는 models.RejectedError 만 잡아서, 여기(모르는 schema)는
    잡히지만 gh.CorruptJSON 류는 트레이스백으로 죽었다. 이 테스트는
    RejectedError 경로가 여전히 깨끗하게 처리되는지 고정한다."""
    다른_schema = {"schema": 99, "positions": []}
    쓴것 = []
    _기본_준비(monkeypatch, positions=다른_schema, write_capture=쓴것)

    rc = quotes.main()

    assert rc == 1
    assert 쓴것 == []
    out = capsys.readouterr().out
    assert "중단" in out


def test_main_positions_조회_자체가_실패해도_트레이스백_없이_중단한다(monkeypatch, capsys):
    """positions.json 이 IRREPLACEABLE 이라 손상되면 gh.CorruptJSON 이 온다.
    구 코드는 이걸 models.RejectedError 로 잡지 못해 main() 밖으로 그대로
    새어나갔다(테스트 없이는 안 드러나던 결함) — 지금은 넓게 잡아야 한다."""
    def 깨진_읽기(path, *a, **k):
        if path == quotes.POSITIONS:
            raise gh.CorruptJSON(path, "somesha")
        raise AssertionError("quotes.json 조회까지 가면 안 된다")

    monkeypatch.setattr(quotes.gh, "read_json", 깨진_읽기)
    쓴것 = []
    monkeypatch.setattr(quotes.gh, "write_json",
                        lambda *a, **k: 쓴것.append(a))

    rc = quotes.main()

    assert rc == 1
    assert 쓴것 == []
    out = capsys.readouterr().out
    assert "중단" in out


def test_main_시세_조회_실패시_중단하고_직전값을_유지한다(monkeypatch, capsys):
    _기본_준비(monkeypatch)

    def 실패(codes):
        raise TimeoutError("네트워크 타임아웃")
    monkeypatch.setattr(quotes.naver, "fetch_quotes", 실패)

    쓴것 = []
    monkeypatch.setattr(quotes.gh, "write_json",
                        lambda *a, **k: 쓴것.append(a))

    rc = quotes.main()

    assert rc == 1
    assert 쓴것 == []
    out = capsys.readouterr().out
    assert "중단" in out


def test_main_달력_조회_실패시_중단한다(monkeypatch):
    _기본_준비(monkeypatch)
    monkeypatch.setattr(quotes.naver, "fetch_trading_days",
                        lambda n: (_ for _ in ()).throw(naver.EmptyParseError("망함")))

    쓴것 = []
    monkeypatch.setattr(quotes.gh, "write_json",
                        lambda *a, **k: 쓴것.append(a))

    rc = quotes.main()

    assert rc == 1
    assert 쓴것 == []


def test_main_전부_실패하면_커밋하지_않는다(monkeypatch, capsys):
    _기본_준비(monkeypatch, got={})   # 요청한 종목이 하나도 안 옴

    쓴것 = []
    monkeypatch.setattr(quotes.gh, "write_json",
                        lambda *a, **k: 쓴것.append(a))

    rc = quotes.main()

    assert rc == 1
    assert 쓴것 == []
    out = capsys.readouterr().out
    assert "중단" in out


def test_main_보유가_없으면_시세없이도_커밋한다(monkeypatch):
    """asked=0 이면 should_commit 이 True — fetch_quotes 는 빈 코드 목록으로
    불려도 예외 없이 빈 dict 를 돌려준다."""
    빈_보유 = {"schema": 1, "positions": []}
    쓴것 = []
    _기본_준비(monkeypatch, positions=빈_보유, got={}, write_capture=쓴것)

    rc = quotes.main()

    assert rc == 0
    assert 쓴것[0][1]["ok_count"] == 0
    assert 쓴것[0][1]["quotes"] == {}


def test_main_quotes파일_조회_실패해도_트레이스백_없이_중단한다(monkeypatch, capsys):
    """구 코드는 `_, sha = gh.read_json(QUOTES)` 가 어떤 try 안에도 없어서,
    이 호출이 실패하면(1MB 초과·409·네트워크) 시세는 다 받아놓고도
    트레이스백으로 죽었다. 이제는 깨끗하게 중단해야 한다."""
    def 읽기(path, *a, **k):
        if path == quotes.POSITIONS:
            return 정상_보유, "psha"
        if path == quotes.QUOTES:
            raise RuntimeError("GET quotes.json -> 409: 충돌")
        raise AssertionError(path)

    monkeypatch.setattr(quotes.gh, "read_json", 읽기)
    monkeypatch.setattr(quotes.naver, "fetch_quotes",
                        lambda codes: {"005930": {"price": 1, "name": "n", "status": "tradable"}})
    monkeypatch.setattr(quotes.naver, "fetch_trading_days", lambda n: ["2026-08-19"])
    monkeypatch.setattr(quotes.naver, "fetch_bars",
                        lambda sym, n=2: {"20260819": {"close": 1.0}})

    쓴것 = []
    monkeypatch.setattr(quotes.gh, "write_json",
                        lambda *a, **k: 쓴것.append(a))

    rc = quotes.main()

    assert rc == 1
    assert 쓴것 == []
    out = capsys.readouterr().out
    assert "중단" in out


def test_main_지수_하나만_실패해도_나머지는_커밋된다(monkeypatch, capsys):
    """fetch_benchmark 는 지수 하나가 실패해도 나머지는 살린다 — '지수는
    있으면 좋은 것' 이지 없다고 멈추지 않는다."""
    쓴것 = []
    _기본_준비(monkeypatch, write_capture=쓴것)

    def 반쪽_bars(sym, n=2):
        if sym == "KOSDAQ":
            raise TimeoutError("지수 타임아웃")
        return {"20260819": {"close": 6471.17}}
    monkeypatch.setattr(quotes.naver, "fetch_bars", 반쪽_bars)

    rc = quotes.main()

    assert rc == 0
    body = 쓴것[0][1]
    assert body["benchmark"] == {"KOSPI": pytest.approx(6471.17)}
    out = capsys.readouterr().out
    assert "경고" in out
