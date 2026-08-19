# -*- coding: utf-8 -*-
"""close.py: 종가 확정·백필 (Task 8, 리뷰 반영판).

공급된 4개 테스트(missing_days ×2, snapshot_for ×2)는 그대로 두고 아래를 추가·수정했다.
계획 문서(구현계획.md)의 공급 코드를 그대로 옮기지 않은 이유는 각 지점에 주석으로
남겼다 — 요약하면:

1. **stale `fetch_benchmark()` 호출** — Task 7 이후 3-tuple
   `(values, history, failed)` 을 돌려준다. `quotes.build(..., bench, ...)` 처럼
   튜플을 통째로 한 자리에 넣으면 `bench` 딕셔너리 자리에 튜플이 들어가 즉시
   깨진다. `bench, bench_history, bench_failed = quotes.fetch_benchmark()` 로
   풀고 `benchmark_history`/`benchmark_failed` 를 명시적으로 넘긴다.
   `dropped=len(bad)` 도 명시한다 — 이 시점의 `bad` 는 main() 앞부분의 refusal
   게이트를 통과했으므로 항상 0 이지만(아래 주석), 기본값에 기대지 않고
   불변식을 코드로 남긴다(구현계획.md 코드리뷰 이월: "quotes.build(...) 를
   dropped 없이 부르면 기본값 0 이라 격리 사실을 지운다").

2. **positions 조회(gh.CorruptJSON 등 넓은 실패)와 정규화(RejectedError 하나,
   좁은 실패)를 한 try 에 묶어놓고 `except models.RejectedError` 만 잡던 버그** —
   quotes.py 가 Task 7 에서 이미 겪고 고친 것과 정확히 같은 결함이 공급 코드에
   그대로 재발해 있었다. 두 try 로 분리했다.

3. **확정 quotes.json 커밋 구간이 어떤 try 에도 없던 버그** — `gh.read_json(QUOTES)`
   가 1MB 초과·409·네트워크 오류로 실패하면 백필은 이미 커밋해놓고도 트레이스백으로
   죽었다. 이것도 quotes.py 가 이미 겪은 것과 같은 결함. try/except 로 감쌌다.

4. **`codes` 가 종결(closed) 종목까지 포함** — `sorted({p["code"] for p in
   state["positions"]})` 는 열림·닫힘을 가리지 않는다. quotes.py 는 `open_codes()`
   로 열린 것만 조회한다(설계 §5-1 "보유 중(open) 종목 코드만"). 닫힌 포지션은
   실현 손익이 `buys`/`exits` 에 이미 고정되어 있어 오늘 종가가 필요 없다 —
   포함시키면 (a) 상폐된 닫힌 종목이 매번 `naver.fetch_bars` 를 실패시켜
   `missing`/`fail_count` 를 오염시키고, (b) 아래 5번 백필 게이트와 만나면
   **영구적으로 백필이 막히는** 사고로 번진다. `quotes.open_codes(state)` 로
   좁혔다.

5. **일봉 조회가 종목 하나라도 완전히 실패하면(거래정지로 그날 값이 없는 것과는
   다르다 — 아예 요청이 예외를 냄) 백필 전체를 건너뛴다** — `history/` 는
   한 번 쓰면 `missing_days` 가 다시는 그 날짜를 안 본다(파일이 있으면 "됐다"로
   친다). 그 상태에서 일부 종목이 빠진 채로 쓰면 그 결손은 **영구화**된다 —
   이 모듈이 `bad`(positions 개별 항목 손상)에 대해 이미 취하는 "차라리 안 쓴다"
   태도를 네트워크발 결손에도 그대로 적용한 것이다. 확정 quotes.json 쪽은
   다르게 뒀다 — 그건 close.py 가 다음에 돌 때(하루 두 번) 마다 통째로 다시
   쓰므로 오늘 실패해도 자연 치유되고, `missing`/`fail_count` 로 이미 투명하게
   드러난다(quotes.py 와 같은 방식) — 그래서 완전 실패가 아니면 굳이 막지 않는다.
   (4번 수정 덕에 이 게이트가 닫힌 종목 상폐로 영영 걸리는 사고는 이제 없다.)

6. **백필 개별 쓰기 실패가 전체를 죽이던 문제** — 하루치 `gh.write_json` 이
   실패하면(429·5xx 등) 트레이스백으로 죽어서 이미 성공한 앞 날짜의 커밋은
   남지만(되돌릴 방법도 없고 되돌릴 이유도 없다), 남은 날짜 시도와 확정
   quotes.json 갱신까지 통째로 못 하게 된다. 하루 단위로 try/except 를 둘러
   한 날짜가 실패해도 나머지 날짜·확정 갱신을 계속 시도한다. 이번 실행에
   못 채운 날짜는 다음 실행이 `missing_days` 로 다시 찾아 채운다.

7. **보유가 0건이면 확정 커밋을 아예 건너뛰던 문제** — 공급 코드는
   `if final:` 로 게이트하는데, `snapshot_for` 는 (테스트가 고정하듯) `closes`
   가 비면 무조건 `None` 을 돌려준다 — 보유가 아예 없을 때도 마찬가지다.
   그러면 `trading_days`/`benchmark` 갱신조차 없이 확정 스냅샷 커밋을 건너뛰어,
   quotes.py 의 "진짜 무보유는 커밋한다"(§8, `test_보유가_없으면_빈_스냅샷도_커밋한다`)
   원칙과 어긋난다. `final` 유무와 무관하게 항상 `quotes.build`/`should_commit`
   을 거치게 고쳤다 — `should_commit` 이 이미 "무보유"와 "전부 실패"를
   올바르게 구분하므로 별도 분기가 필요 없다.

나머지(공급 코드 그대로 채택한 것):
- `missing_days` 의 `f[:-5]`(→ `f[:-len(".json")]` 로 표현만 명확히 했다) —
  `.endswith(".json")` 게이트를 먼저 거치므로 `....json.bak` 은 애초에 안 걸리고,
  `.json` 단독 파일은 빈 문자열을 만들어도 어떤 실제 날짜와도 충돌하지 않는다.
  아래 추가 테스트로 고정.
- `n=WINDOW*2`(=60 거래일치 일봉) — `missing_days` 가 항상 최근 WINDOW(30)
  거래일로만 `todo` 를 제한하므로(얼마나 오래 안 돌았든) 60 은 2배 여유다.
- `latest = days[-1]` — 그날 삼성전자 일봉이 아직 안 나왔으면 `days` 자체가
  그 날짜를 안 담으므로 `latest` 는 자동으로 "확정 가능한 가장 최근 날짜"가
  된다. 커밋되는 `trading_days` 배열의 마지막 값이 그 사실을 스스로 드러내므로
  화면(Task 12)이 "확정 가격이 어느 날짜 것인지" 를 알 수 있다 — 별도 필드
  불필요.
- `name` 을 `next((p["name"] for p in state["positions"] if p["code"] == c), c)`
  로 선형 탐색 — 같은 코드가 두 번(분할 매수) 있어도 같은 종목이라 이름이
  같다. `normalize()` 가 `p.setdefault("name", p["code"])` 로 항상 채우므로
  기본값 `c` 로 떨어질 일도 없다.
- `history/` 에 지수 종가를 따로 안 싣는 것 — §6-2 가 요구하는 "같은 기간
  지수 수익률" 근거는 `quotes.json` 의 `benchmark_history`(250거래일 롤링)가
  이미 충분히 감당한다. `history/` 의 30일 백필 창은 그 250일 안에 항상
  포함되므로 중복 저장할 이유가 없다.
"""
import datetime as _dt

import pytest

from scripts import close, gh, models, naver, quotes

DAYS = ["2026-08-12", "2026-08-13", "2026-08-14", "2026-08-18", "2026-08-19"]


# ---------------------------------------------------------------------------
# 공급된 테스트 (그대로)
# ---------------------------------------------------------------------------

def test_빠진_날짜를_찾는다():
    있음 = ["2026-08-18.json", "2026-08-19.json", "안녕.txt"]
    assert close.missing_days(DAYS, 3, 있음) == ["2026-08-14"]


def test_다_있으면_빈_목록():
    있음 = [f"{d}.json" for d in DAYS]
    assert close.missing_days(DAYS, 5, 있음) == []


def test_일봉에서_그날_종가를_모은다():
    bars = {
        "005930": {"20260818": {"close": 268500}, "20260819": {"close": 247500}},
        "000660": {"20260819": {"close": 1234000}},
    }
    snap = close.snapshot_for("2026-08-19", bars,
                              {"positions": [{"code": "005930"}, {"code": "000660"}]})
    assert snap["date"] == "2026-08-19"
    assert snap["closes"] == {"005930": 247500, "000660": 1234000}
    assert snap["positions"] == [{"code": "005930"}, {"code": "000660"}]


def test_그날_봉이_없는_종목은_뺀다():
    """거래정지 종목은 봉이 없다. 0 으로 채우면 수익률이 -100% 가 된다."""
    bars = {"005930": {"20260819": {"close": 247500}},
            "000660": {"20260818": {"close": 1}}}
    snap = close.snapshot_for("2026-08-19", bars, {"positions": []})
    assert snap["closes"] == {"005930": 247500}


def test_봉이_하나도_없는_날은_스냅샷을_만들지_않는다():
    """오늘 봉은 15:31~32 에 나온다. 그 전에 돌면 아무것도 쓰지 않는다."""
    assert close.snapshot_for("2026-08-19", {"005930": {}}, {"positions": []}) is None


# ---------------------------------------------------------------------------
# 추가 테스트 — missing_days: f[:-5] 가 정말 안전한가 (비평 포인트 2)
# ---------------------------------------------------------------------------

def test_json_bak_파일은_json_이_아니라서_애초에_안_걸린다():
    """`.endswith(".json")` 게이트가 먼저다 — `.json.bak` 은 그 자리에서 걸러진다.
    걸러지지 않았다면 `f[:-5]` 가 "2026-08-19.json" 이 아니라 "19.json.bak"
    같은 걸 자르는 사고가 났겠지만, 애초에 이 파일은 `have` 에 들어가지도 않는다."""
    있음 = ["2026-08-19.json.bak"]
    assert close.missing_days(DAYS, 5, 있음) == DAYS  # 아무것도 "있다"고 인정 안 함


def test_점json_단독_파일은_빈_문자열이_되어도_무해하다():
    """`.json` 단독(길이 5)이면 `f[:-5]` 가 빈 문자열이 된다. 빈 문자열은 어떤
    실제 날짜(YYYY-MM-DD)와도 같을 수 없으므로 `missing` 판정에 영향이 없다."""
    있음 = [".json"] + [f"{d}.json" for d in DAYS]
    assert close.missing_days(DAYS, 5, 있음) == []


# ---------------------------------------------------------------------------
# main() 통합 테스트 준비 — gh/naver/quotes.fetch_benchmark 는 전부 monkeypatch
# ---------------------------------------------------------------------------

def _거래일_목록(n: int, end: str = "2026-08-19") -> list:
    """끝나는 날짜까지 연속 n일치 날짜 문자열(오름차순). trading_calendar 는
    이 문자열들을 달력 계산 없이 순서 있는 라벨로만 다루므로 주말 포함
    단순 연속일이어도 로직 검증에는 지장이 없다."""
    end_d = _dt.date.fromisoformat(end)
    return [(end_d - _dt.timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


ALL_DAYS = _거래일_목록(35)                 # WINDOW(30)+2=32 이상 필요 → 여유있게 35
assert len(ALL_DAYS) == 35 and ALL_DAYS[-1] == "2026-08-19"


def _bars_for(days: list, base: int, step) -> dict:
    return {d.replace("-", ""): {"close": base + i * step} for i, d in enumerate(days)}


_지수_bars = {
    "KOSPI": _bars_for(ALL_DAYS, base=6400, step=1),
    "KOSDAQ": _bars_for(ALL_DAYS, base=800, step=0.5),
}


def _삼성_bars(days=ALL_DAYS, base=240000, step=500):
    return _bars_for(days, base, step)


정상_보유 = {"schema": 1, "positions": [
    {"id": "20260801-005930", "code": "005930", "name": "삼성전자",
     "buys": [{"date": "2026-08-01", "price": 240000}],
     "exits": [], "adjustments": [], "status": "open",
     "signal_date": None, "source": "수동", "memo": ""},
]}

보유_열림_닫힘 = {"schema": 1, "positions": [
    {"id": "20260801-005930", "code": "005930", "name": "삼성전자",
     "buys": [{"date": "2026-08-01", "price": 240000}],
     "exits": [], "adjustments": [], "status": "open",
     "signal_date": None, "source": "수동", "memo": ""},
    {"id": "20260601-999999", "code": "999999", "name": "상폐예정",
     "buys": [{"date": "2026-06-01", "price": 10000}],
     "exits": [{"date": "2026-07-01", "price": 9000, "reason": "손절"}],
     "adjustments": [], "status": "closed",
     "signal_date": None, "source": "수동", "memo": ""},
]}


def _기본_준비(monkeypatch, *, positions=None, quotes_sha="qsha",
             기존_history=None, write_capture=None,
             삼성_bars=None):
    if positions is None:
        positions = 정상_보유
    if 기존_history is None:
        # 최근 30거래일 중 마지막 2일만 비어있게 — 백필 대상이 2건
        기존_history = [f"{d}.json" for d in ALL_DAYS[-30:-2]]
    if 삼성_bars is None:
        삼성_bars = _삼성_bars()

    def 가짜_읽기(path, *a, **k):
        if path == close.POSITIONS:
            return positions, "psha"
        if path == close.QUOTES:
            return None, quotes_sha
        raise AssertionError(f"예상 못한 경로: {path}")

    monkeypatch.setattr(close.gh, "read_json", 가짜_읽기)
    monkeypatch.setattr(close.gh, "list_dir",
                        lambda path: 기존_history if path == "history" else (_ for _ in ()).throw(
                            AssertionError(f"예상 못한 디렉토리: {path}")))

    if write_capture is not None:
        monkeypatch.setattr(
            close.gh, "write_json",
            lambda path, body, sha, msg: write_capture.append((path, body, sha, msg)))

    monkeypatch.setattr(close.naver, "fetch_trading_days", lambda n: list(ALL_DAYS))

    def 가짜_bars(symbol, n=60):
        if symbol == "005930":
            return dict(삼성_bars)
        if symbol in _지수_bars:
            return dict(_지수_bars[symbol])
        raise AssertionError(f"예상 못한 심볼: {symbol}")

    monkeypatch.setattr(close.naver, "fetch_bars", 가짜_bars)


def test_main_정상_백필_후_확정_커밋(monkeypatch, capsys):
    쓴것 = []
    _기본_준비(monkeypatch, write_capture=쓴것)

    rc = close.main()

    assert rc == 0
    # 백필 2건(ALL_DAYS[-2], ALL_DAYS[-1]) + 확정 quotes 1건 = 3
    assert len(쓴것) == 3
    백필_경로 = [w[0] for w in 쓴것[:2]]
    assert 백필_경로 == [f"history/{ALL_DAYS[-2]}.json", f"history/{ALL_DAYS[-1]}.json"]
    for path, body, sha, msg in 쓴것[:2]:
        assert sha is None  # 새 파일 — 이미 있는 날짜에 쓰면 422
        assert body["date"] in (ALL_DAYS[-2], ALL_DAYS[-1])
        assert "005930" in body["closes"]
        assert body["positions"] == 정상_보유["positions"]

    확정_path, 확정_body, 확정_sha, 확정_msg = 쓴것[2]
    assert 확정_path == close.QUOTES
    assert 확정_sha == "qsha"
    assert 확정_body["is_final"] is True
    assert 확정_body["quotes"]["005930"]["price"] == _삼성_bars()[ALL_DAYS[-1].replace("-", "")]["close"]
    assert 확정_body["positions_dropped"] == 0
    assert 확정_body["benchmark"]["KOSPI"] == pytest.approx(6400 + 34)
    assert 확정_body["benchmark_history"]["KOSPI"][ALL_DAYS[-1]] == pytest.approx(6400 + 34)
    assert 확정_body["benchmark_failed"] == []
    assert 확정_msg == f"quotes(확정): {ALL_DAYS[-1]}"

    out = capsys.readouterr().out
    assert "완료 — 새 스냅샷 2건" in out
    assert "확정 시세 갱신" in out


def test_main_메울_날짜_없으면_백필없이_확정만_커밋(monkeypatch, capsys):
    쓴것 = []
    _기본_준비(monkeypatch, 기존_history=[f"{d}.json" for d in ALL_DAYS[-30:]],
             write_capture=쓴것)

    rc = close.main()

    assert rc == 0
    assert len(쓴것) == 1
    assert 쓴것[0][0] == close.QUOTES
    out = capsys.readouterr().out
    assert "메울 날짜 없음" in out


def test_main_positions_조회_자체가_실패해도_트레이스백_없이_중단한다(monkeypatch, capsys):
    """공급 코드는 `gh.read_json` 을 `models.normalize` 와 한 try 에 묶어놓고
    `except models.RejectedError` 만 잡았다 — `gh.CorruptJSON`(positions.json 은
    IRREPLACEABLE 이라 손상되면 항상 이것)은 못 잡혀 트레이스백으로 죽었다.
    quotes.py 가 Task 7 에서 이미 고친 것과 같은 결함이다."""
    def 깨진_읽기(path, *a, **k):
        if path == close.POSITIONS:
            raise gh.CorruptJSON(path, "somesha")
        raise AssertionError("quotes.json/history 조회까지 가면 안 된다")

    monkeypatch.setattr(close.gh, "read_json", 깨진_읽기)
    쓴것 = []
    monkeypatch.setattr(close.gh, "write_json", lambda *a, **k: 쓴것.append(a))
    monkeypatch.setattr(close.gh, "list_dir", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("여기까지 가면 안 된다")))

    rc = close.main()

    assert rc == 1
    assert 쓴것 == []
    out = capsys.readouterr().out
    assert "중단" in out


def test_main_positions_스키마가_깨지면_중단하고_쓰지_않는다(monkeypatch, capsys):
    다른_schema = {"schema": 99, "positions": []}
    쓴것 = []
    _기본_준비(monkeypatch, positions=다른_schema, write_capture=쓴것)

    rc = close.main()

    assert rc == 1
    assert 쓴것 == []
    out = capsys.readouterr().out
    assert "중단" in out


def test_main_손상_항목이_있으면_스냅샷을_전혀_찍지_않는다(monkeypatch, capsys):
    """quotes.py 와 다르다 — history 는 복구용 사본이므로 손상 항목이 있으면
    (개수와 무관하게) 아무것도 안 쓰고 멈춘다."""
    손상_포함 = {"schema": 1, "positions": [
        {"id": "20260801-005930", "code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-01", "price": 240000}],
         "exits": [], "adjustments": [], "status": "open",
         "signal_date": None, "source": "수동", "memo": ""},
        {"id": "깨짐", "code": "00660"},   # 5자리 — 코드 형식 오류로 격리됨
    ]}
    쓴것 = []
    _기본_준비(monkeypatch, positions=손상_포함, write_capture=쓴것)

    rc = close.main()

    assert rc == 1
    assert 쓴것 == []
    out = capsys.readouterr().out
    assert "중단" in out
    assert "해석 불가 항목 1건" in out


def test_main_최상위_구조가_깨지면_전체가_사라진_것으로_보고한다(monkeypatch, capsys):
    """quotes.py 의 WHOLE_FILE_MARKER 구분을 그대로 재사용한다. 어느 쪽이든
    return 1·아무것도 안 씀은 같지만, 로그 문구가 "기록 1건 손상"으로 뭉뚱그려
    지면 "보유 전체가 안 보인다"는 사고가 축소 보고된다(quotes.py 리뷰 A1과
    같은 함정)."""
    망가진_최상위 = {"schema": 1, "positions": "이건 배열이 아니라 문자열이다"}
    쓴것 = []
    _기본_준비(monkeypatch, positions=망가진_최상위, write_capture=쓴것)

    rc = close.main()

    assert rc == 1
    assert 쓴것 == []
    out = capsys.readouterr().out
    assert "최상위 구조" in out
    assert "해석 불가 항목 1건" not in out


def test_main_달력_조회_실패시_중단한다(monkeypatch, capsys):
    _기본_준비(monkeypatch)
    monkeypatch.setattr(close.naver, "fetch_trading_days",
                        lambda n: (_ for _ in ()).throw(naver.EmptyParseError("망함")))
    쓴것 = []
    monkeypatch.setattr(close.gh, "write_json", lambda *a, **k: 쓴것.append(a))

    rc = close.main()

    assert rc == 1
    assert 쓴것 == []
    out = capsys.readouterr().out
    assert "중단" in out


def test_main_달력이_짧으면_중단한다(monkeypatch, capsys):
    """오래 방치돼서(혹은 네이버 응답 이상으로) 거래일이 WINDOW+2 보다 적으면
    잘못 채우느니 쉰다."""
    _기본_준비(monkeypatch)
    monkeypatch.setattr(close.naver, "fetch_trading_days", lambda n: ALL_DAYS[-5:])
    쓴것 = []
    monkeypatch.setattr(close.gh, "write_json", lambda *a, **k: 쓴것.append(a))

    rc = close.main()

    assert rc == 1
    assert 쓴것 == []
    out = capsys.readouterr().out
    assert "중단" in out
    assert "짧다" in out


def test_main_보유_종목_일봉이_완전히_실패하면_백필을_건너뛴다(monkeypatch, capsys):
    """거래정지로 그날 값이 없는 것과, 아예 요청이 실패하는 것은 다르다.
    후자를 그대로 두면 history/ 가 그 종목이 빠진 채로 영구히 저장된다
    (missing_days 는 파일이 있으면 다시 안 본다). 대신 확정 quotes.json 은
    계속 시도한다 — 그건 매번 다시 쓰이므로 자연 치유된다."""
    def 가짜_bars(symbol, n=60):
        if symbol == "005930":
            raise TimeoutError("네트워크 타임아웃")
        if symbol in _지수_bars:
            return dict(_지수_bars[symbol])
        raise AssertionError(symbol)

    쓴것 = []
    _기본_준비(monkeypatch, write_capture=쓴것)
    monkeypatch.setattr(close.naver, "fetch_bars", 가짜_bars)

    rc = close.main()

    # 백필은 전혀 안 씀. 확정 쪽은 005930 이 빠진 채(=0건) 이고 asked=["005930"]
    # 하나뿐이라 ok_count=0 → should_commit 이 False → 그것도 안 쓴다.
    assert 쓴것 == []
    assert rc == 1
    out = capsys.readouterr().out
    assert "일봉 실패 005930" in out
    assert "history/" not in out or "건너뛴" in out or "백필" in out


def test_main_일부_종목만_일봉_실패해도_확정은_나머지로_커밋된다(monkeypatch, capsys):
    """열린 종목이 둘인데 하나만 완전 실패 — 백필은 건너뛰지만(위 테스트와
    같은 이유) 확정 quotes.json 은 성공한 나머지 하나로 커밋되고, 실패한
    쪽은 missing/fail_count 로 투명하게 드러난다(quotes.py 와 같은 방식)."""
    보유_둘 = {"schema": 1, "positions": [
        {"id": "20260801-005930", "code": "005930", "name": "삼성전자",
         "buys": [{"date": "2026-08-01", "price": 240000}],
         "exits": [], "adjustments": [], "status": "open",
         "signal_date": None, "source": "수동", "memo": ""},
        {"id": "20260801-000660", "code": "000660", "name": "SK하이닉스",
         "buys": [{"date": "2026-08-01", "price": 200000}],
         "exits": [], "adjustments": [], "status": "open",
         "signal_date": None, "source": "수동", "memo": ""},
    ]}

    def 가짜_bars(symbol, n=60):
        if symbol == "005930":
            return _삼성_bars()
        if symbol == "000660":
            raise TimeoutError("네트워크 타임아웃")
        if symbol in _지수_bars:
            return dict(_지수_bars[symbol])
        raise AssertionError(symbol)

    쓴것 = []
    _기본_준비(monkeypatch, positions=보유_둘, write_capture=쓴것)
    monkeypatch.setattr(close.naver, "fetch_bars", 가짜_bars)

    rc = close.main()

    assert rc == 1   # 이번 실행에 일부 실패가 있었다는 사실은 여전히 드러난다
    assert len(쓴것) == 1   # 백필은 0건, 확정만 1건
    body = 쓴것[0][1]
    assert body["is_final"] is True
    assert body["quotes"]["005930"]["price"] == _삼성_bars()[ALL_DAYS[-1].replace("-", "")]["close"]
    assert "000660" not in body["quotes"]
    assert body["missing"] == ["000660"]
    assert body["fail_count"] == 1
    out = capsys.readouterr().out
    assert "일봉 실패 000660" in out


def test_main_닫힌_포지션_코드는_일봉을_아예_조회하지_않는다(monkeypatch, capsys):
    """닫힌 포지션의 실현 손익은 buys/exits 에 이미 고정돼 있다 — 오늘 종가가
    필요 없다. 조회 대상에 넣으면 상폐된 닫힌 종목이 매번 fetch 를 실패시켜
    (a) 확정 스냅샷의 missing/fail_count 를 무의미하게 부풀리고, (b) 위
    "일봉 완전 실패 → 백필 건너뛴다" 게이트와 만나면 그 종목이 상폐인 한
    백필이 영원히 막힌다."""
    쓴것 = []

    def 가짜_bars(symbol, n=60):
        if symbol == "999999":
            raise AssertionError("닫힌 포지션 코드는 조회하면 안 된다")
        if symbol == "005930":
            return _삼성_bars()
        if symbol in _지수_bars:
            return dict(_지수_bars[symbol])
        raise AssertionError(symbol)

    _기본_준비(monkeypatch, positions=보유_열림_닫힘, write_capture=쓴것)
    monkeypatch.setattr(close.naver, "fetch_bars", 가짜_bars)

    rc = close.main()

    assert rc == 0
    확정_body = 쓴것[-1][1]
    assert "999999" not in 확정_body["quotes"]
    assert "999999" not in 확정_body["missing"]
    assert 확정_body["fail_count"] == 0


def test_main_백필_쓰기가_일부_실패해도_나머지와_확정은_계속된다(monkeypatch, capsys):
    """하루치 gh.write_json 실패(예: 5xx)가 남은 날짜·확정 갱신까지 막으면
    안 된다 — 이미 쓴 날짜는 되돌릴 필요도 없고(다음 날짜 시도를 막을 이유도
    없다), 확정 quotes.json 은 백필과 무관한 별개 스텝이다."""
    기존_history = [f"{d}.json" for d in ALL_DAYS[-30:-3]]  # 마지막 3일 백필 대상

    def 쓰기(path, body, sha, msg):
        if path == f"history/{ALL_DAYS[-2]}.json":
            raise RuntimeError("PUT history/... -> 500: 일시적 오류")
        쓴것.append((path, body, sha, msg))

    쓴것 = []
    _기본_준비(monkeypatch, 기존_history=기존_history)
    monkeypatch.setattr(close.gh, "write_json", 쓰기)

    rc = close.main()

    assert rc == 1   # 이번 실행에 실패가 있었다는 사실은 드러나야 한다
    경로들 = [w[0] for w in 쓴것]
    assert f"history/{ALL_DAYS[-3]}.json" in 경로들   # 실패 이전 날짜 — 성공
    assert f"history/{ALL_DAYS[-2]}.json" not in 경로들  # 실패한 날짜 — 없음(당연)
    assert f"history/{ALL_DAYS[-1]}.json" in 경로들   # 실패 이후 날짜 — 계속 시도됨
    assert close.QUOTES in 경로들                      # 확정 갱신도 계속 시도됨
    out = capsys.readouterr().out
    assert "쓰기 실패" in out or "경고" in out


def test_main_확정_quotes_조회_실패해도_백필은_남고_트레이스백_없이_넘어간다(monkeypatch, capsys):
    """공급 코드는 `_, sha = gh.read_json(QUOTES)` 가 어떤 try 안에도 없었다 —
    quotes.py 가 이미 겪은 것과 같은 결함. 백필까지는 정상 진행되고, 확정
    커밋 단계만 조용히 실패해야 한다(이미 쓴 백필 커밋은 되돌릴 이유가 없다)."""
    쓴것 = []

    def 읽기(path, *a, **k):
        if path == close.POSITIONS:
            return 정상_보유, "psha"
        if path == close.QUOTES:
            raise RuntimeError("GET quotes.json -> 409: 충돌")
        raise AssertionError(path)

    monkeypatch.setattr(close.gh, "read_json", 읽기)
    monkeypatch.setattr(close.gh, "list_dir",
                        lambda p: [f"{d}.json" for d in ALL_DAYS[-30:-1]])  # 마지막 1일만 백필
    monkeypatch.setattr(close.gh, "write_json", lambda path, body, sha, msg: 쓴것.append((path, body, sha, msg)))
    monkeypatch.setattr(close.naver, "fetch_trading_days", lambda n: list(ALL_DAYS))

    def 가짜_bars(symbol, n=60):
        if symbol == "005930":
            return _삼성_bars()
        if symbol in _지수_bars:
            return dict(_지수_bars[symbol])
        raise AssertionError(symbol)
    monkeypatch.setattr(close.naver, "fetch_bars", 가짜_bars)

    rc = close.main()

    assert rc == 1
    assert len(쓴것) == 1
    assert 쓴것[0][0] == f"history/{ALL_DAYS[-1]}.json"
    out = capsys.readouterr().out
    assert "경고" in out or "실패" in out


def test_main_보유가_0건이면_확정_스냅샷도_커밋한다(monkeypatch, capsys):
    """quotes.py 의 "진짜 무보유는 커밋한다"(§8) 원칙과 짝을 맞춘다 — 공급
    코드는 `if final:` 로 게이트해서, closes 가 빈(보유 0건 포함) 경우
    확정 커밋 자체를 건너뛰었다. trading_days/benchmark 는 보유가 없어도
    갱신돼야 한다."""
    빈_보유 = {"schema": 1, "positions": []}
    쓴것 = []
    _기본_준비(monkeypatch, positions=빈_보유,
             기존_history=[f"{d}.json" for d in ALL_DAYS[-30:]],  # 백필 대상 없음
             write_capture=쓴것)

    rc = close.main()

    assert rc == 0
    assert len(쓴것) == 1
    body = 쓴것[0][1]
    assert body["quotes"] == {}
    assert body["ok_count"] == 0
    assert body["fail_count"] == 0
    assert body["is_final"] is True
    assert body["trading_days"] == ALL_DAYS
