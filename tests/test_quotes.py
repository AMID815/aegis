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

Stage 2 리뷰(A1~A4) 반영:

- A1 — `asked==0` 은 "진짜 무보유"와 "정규화가 전부 걸러내서 0건으로
  보인 것"을 구분 못 한다. `should_commit` 이 `positions_dropped` 를 같이
  보게 고쳤고, `main()` 의 경고 로그도 "(파일 전체)" 합성 마커(최상위
  구조 손상)와 개별 항목 N건 손상을 구분해서 찍는다.
- A2 — 지수 조회 실패는 로그에만 남으면 화면이 못 본다(§8). 스냅샷에
  `benchmark_failed` 로 싣는다.
- A3 — `fetch_benchmark` 가 `n=250` 으로 지수 일봉을 받아 `benchmark_history`
  (YYYY-MM-DD 키)를 같이 싣는다. 요청 수는 그대로다 — 같은 한 번의
  요청이 더 많은 일수를 돌려줄 뿐이다.
- A4 — positions 조회(넓게)와 정규화(좁게, `RejectedError` 하나)를 별도
  try 로 나눴다. `_기본_준비` 의 `fetch_bars` 가짜가 `sym` 을 무시하던
  것도 지수별로 다른 값을 돌려주게 고쳤다(안 그러면 KOSPI 만 계속 불러도
  테스트가 못 잡는다).
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
# 추가 테스트 — 리뷰 A1: "보유 0건"과 "전부 격리돼서 0건"은 다르다
# ---------------------------------------------------------------------------

def test_보유가_전부_격리되면_빈_스냅샷을_커밋하지_않는다():
    """asked==0(ok_count==fail_count==0) 만으로는 "진짜 무보유"인지 "정규화가
    전부 걸러내서 0건으로 보인 것"인지 구분이 안 된다 — positions_dropped
    를 같이 봐야 한다. 후자를 커밋하면 정상 quotes.json 이 빈 스냅샷으로
    덮이고, fresh as_of_kst 가 §7 stale 배지를 조용히 재운다."""
    snap = quotes.build(got={}, asked=[], days=["2026-08-19"],
                        bench={}, now_kst="t", is_final=False, dropped=3)
    assert quotes.should_commit(snap) is False


def test_진짜_무보유는_dropped_0이라_여전히_커밋한다():
    """위 테스트와 짝 — dropped=0 이면(원래 공급된 케이스) 여전히 커밋해야
    한다. should_commit 의 asked==0 분기가 dropped 유무로 갈리는지 고정."""
    snap = quotes.build(got={}, asked=[], days=["2026-08-19"],
                        bench={}, now_kst="t", is_final=False, dropped=0)
    assert quotes.should_commit(snap) is True


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

    # sym 을 무시하는 가짜는 "KOSPI 만 계속 불러도" 테스트가 못 알아챈다
    # (리뷰 A4) — 지수별로 다른 값을 돌려주게 갈라서 실제로 두 심볼이
    # 각각 요청됐는지 드러나게 한다.
    _지수값 = {"KOSPI": 6471.17, "KOSDAQ": 824.46}

    def 가짜_bars(sym, n=250):
        if sym not in _지수값:
            raise AssertionError(f"예상 못한 지수 심볼: {sym}")
        v = _지수값[sym]
        return {"20260818": {"close": v - 1}, "20260819": {"close": v}}

    monkeypatch.setattr(quotes.naver, "fetch_bars", 가짜_bars)


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
    # 두 지수를 각각 확인한다 — sym 을 무시하는 가짜였다면 KOSPI 값이
    # KOSDAQ 자리에도 그대로 들어가 있어도 이 assert 로는 못 잡았다(A4).
    assert body["benchmark"]["KOSPI"] == pytest.approx(6471.17)
    assert body["benchmark"]["KOSDAQ"] == pytest.approx(824.46)
    assert body["benchmark_failed"] == []
    assert body["benchmark_history"]["KOSPI"]["2026-08-19"] == pytest.approx(6471.17)
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
    # 개별 항목 1건이 격리된 것이지 파일 전체가 안 보인 게 아니다 — 아래
    # test_main_최상위_구조가_깨지면... 과 로그 문구로 구분돼야 한다(A1).
    assert "해석 불가 항목 1건" in out
    assert "최상위 구조" not in out


def test_main_최상위_구조가_깨지면_전체가_사라진_것으로_보고하고_커밋하지_않는다(monkeypatch, capsys):
    """models.normalize 는 최상위 구조 자체가 이상하면(positions 가 list 가
    아님 등) dropped 에 "(파일 전체)" 합성 마커 **1건**만 싣고 나머지는
    전부 empty_state() 로 비워버린다.

    이걸 그냥 "해석 불가 항목 1건"이라고 찍으면, 보유가 몇 건이었든 전부
    안 보이게 된 사고를 "기록 1건을 못 읽었다"로 축소 보고하는 것이다
    (리뷰 A1). 게다가 정규화된 state 의 positions 는 비어 있으므로
    open_codes 는 [] 를 돌려주고, asked==0·positions_dropped==1 이라
    should_commit 이 이제(A1 이후) False 를 내야 한다 — 정상이던
    quotes.json 이 빈 스냅샷으로 덮이면 안 된다."""
    망가진_최상위 = {"schema": 1, "positions": "이건 배열이 아니라 문자열이다"}
    쓴것 = []
    _기본_준비(monkeypatch, positions=망가진_최상위, got={}, write_capture=쓴것)

    rc = quotes.main()

    assert rc == 1
    assert 쓴것 == []
    out = capsys.readouterr().out
    assert "최상위 구조" in out
    assert "해석 불가 항목 1건" not in out


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
    있으면 좋은 것' 이지 없다고 멈추지 않는다. 실패했다는 사실 자체는
    로그가 아니라 스냅샷의 benchmark_failed 에 실려야 화면이 말할 수
    있다(리뷰 A2 — "로그는 아무도 안 본다")."""
    쓴것 = []
    _기본_준비(monkeypatch, write_capture=쓴것)

    def 반쪽_bars(sym, n=250):
        if sym == "KOSDAQ":
            raise TimeoutError("지수 타임아웃")
        return {"20260818": {"close": 6460.0}, "20260819": {"close": 6471.17}}
    monkeypatch.setattr(quotes.naver, "fetch_bars", 반쪽_bars)

    rc = quotes.main()

    assert rc == 0
    body = 쓴것[0][1]
    assert body["benchmark"] == {"KOSPI": pytest.approx(6471.17)}
    assert body["benchmark_failed"] == ["KOSDAQ"]
    assert "KOSDAQ" not in body["benchmark_history"]
    assert body["benchmark_history"]["KOSPI"]["2026-08-18"] == pytest.approx(6460.0)
    out = capsys.readouterr().out
    assert "경고" in out


def test_main_생성한_스냅샷은_is_final_False이고_커밋메시지에_시각을_담는다(monkeypatch):
    """close.py(Task 8) 가 나중에 덮어쓸 두 필드다 — 조용히 뒤집히면 이
    모듈만 봐서는 알아채기 어렵다(리뷰 A4)."""
    쓴것 = []
    _기본_준비(monkeypatch, write_capture=쓴것)

    rc = quotes.main()

    assert rc == 0
    path, body, sha, msg = 쓴것[0]
    assert body["is_final"] is False
    assert msg == f"quotes: {body['as_of_kst']}"


def test_지수_이력을_YYYY_MM_DD_키로_한번의_요청에서_수집한다(monkeypatch):
    """§6-2 가 벤치마크를 두는 이유는 "같은 기간 지수 수익률" 비교인데,
    최신 레벨 하나로는 그 계산 자체가 불가능하다(리뷰 A3) — Task 12 가
    보유기간 지수 수익률을 계산하려면 trading_days 와 같은 날짜 형식
    (YYYY-MM-DD) 의 과거 값이 필요하다. naver.fetch_bars 는 한 번의
    요청으로 n일치를 전부 주므로, n 을 250 으로 올려도 요청 수는 늘지
    않는다는 전제를 n== 값으로 직접 확인한다."""
    def 가짜_bars(sym, n=250):
        assert n == 250   # 요청 수를 늘리지 않는다(추가 호출이 아니라 n 값만 커진다)
        return {"20260818": {"close": 6460.0}, "20260819": {"close": 6471.17}}
    monkeypatch.setattr(quotes.naver, "fetch_bars", 가짜_bars)

    values, history, failed = quotes.fetch_benchmark()

    assert failed == []
    assert values["KOSPI"] == pytest.approx(6471.17)
    assert history["KOSPI"] == {
        "2026-08-18": pytest.approx(6460.0),
        "2026-08-19": pytest.approx(6471.17),
    }


# ── 자동매수 대기 종목도 조회 대상이어야 한다 (2026-08-21 실측 사고) ──────
#
# open_codes() 가 status=="open" 만 골랐다. close.py 는 이 목록으로 **일봉**을
# 받고, autofill.run 은 그 bars 에서 대기 종목의 그날 저가를 찾아 지정가 도달을
# 판정한다 — 즉 대기 종목이 목록에 없으면 `bars.get(code)` 가 None 이라
# **자동매수가 한 번도 안 걸린다.** 라이브에서 실제로 그랬다(금호전기 001210,
# quotes.json 의 조회 종목이 빈 배열).
#
# 화면 쪽 증상(대기 표의 현재가가 늘 비어 있음)은 같은 원인의 겉모습일 뿐이고,
# 진짜 피해는 기능이 통째로 안 도는 것이었다.

def test_대기_종목도_조회_대상이다():
    st = models.normalize({"schema": 1, "positions": [
        {"code": "005930", "buys": [{"date": "2026-08-19", "price": 100000}],
         "status": "open", "orders": {"buy2": 94000, "buy3": 88000}},
        {"code": "000660", "buys": [], "status": "pending",
         "watch": {"price": 50000, "date": "2026-08-20", "days": 5}},
    ]})
    assert quotes.live_codes(st) == ["005930", "000660"]


def test_종결_만료는_조회_대상이_아니다():
    """이미 끝난 기록은 오늘 시세가 필요 없다. 상폐된 종목이 매번 조회를
    실패시켜 fail_count 를 부풀리는 것도 막는다(open_codes 의 원래 취지)."""
    st = models.normalize({"schema": 1, "positions": [
        {"code": "005930", "buys": [{"date": "2026-08-19", "price": 100000}],
         "status": "closed", "exits": [{"date": "2026-08-20", "price": 1, "reason": ""}]},
        {"code": "000660", "buys": [], "status": "expired",
         "watch": {"price": 50000, "date": "2026-08-01", "days": 5}},
    ]})
    assert quotes.live_codes(st) == []


def test_같은_코드가_보유와_대기로_동시에_있으면_한_번만():
    """중복이 남으면 missing_codes 가 같은 코드를 두 번 실어 fail_count 가
    부풀어 오른다 — open_codes 가 원래 막던 것과 같은 함정."""
    st = models.normalize({"schema": 1, "positions": [
        {"code": "005930", "buys": [{"date": "2026-08-19", "price": 100000}],
         "status": "open", "orders": {"buy2": 94000, "buy3": 88000}},
        {"code": "005930", "buys": [], "status": "pending",
         "watch": {"price": 50000, "date": "2026-08-20", "days": 5}},
    ]})
    assert quotes.live_codes(st) == ["005930"]
