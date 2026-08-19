// 모의고사 — 페이지 전체 두뇌. 파생 지표는 전부 여기서만 계산한다
// (파이썬은 값만 모은다 — positions.json/quotes.json/master.json 어디에도
// 수익률·승률·보유일수는 없다). 문자열은 반드시 textContent 로만 넣는다.
// innerHTML 금지 — 특히 자동완성 목록에서 일치 부분을 강조하고 싶어질
// 때가 가장 위험한 지점이다(문자열 이어붙이기로 새는 경로).
//
// 구현계획.md Task 12/13 의 공급 코드에서 아래를 고쳤다(코드리뷰 이월
// 항목 + 자체 비판적 검토 — 각 지점에도 짧은 주석이 있다):
//
//  1. load() 가 404(positions.json 이 아직 한 번도 안 커밋된 정상적인
//     첫 실행)와 그 외 실패(네트워크·5xx·JSON 파싱 오류)를 { ok, notFound }
//     로 구분해 돌려준다. 원안은 둘 다 같은 catch 로 떨어져 "실패해서
//     못 받아옴"과 "안 사서 없음"이 화면에서 똑같이 "0건"으로 보였다.
//     로드 실패는 renderStale 배지가 최우선으로 알린다.
//  2. master.json(207KB, 4,299종목)을 Promise.all 밖으로 뺐다 — 표
//     렌더는 positions/quotes 만 있으면 된다. 원안은 이 파일을 기다리느라
//     첫 페인트가 막혔다. 캐시버스터도 Date.now() 대신 KST 오늘 날짜로
//     바꿔 하루 한 번만 새로 받게 했다(하루 안엔 안 바뀌는 파일).
//  3. fail_count/missing/benchmark_failed 를 stale 배지에 추가했다 — 원안은
//     positions_dropped 만 보여줘서, 시세를 못 받은 종목이 개별 행엔
//     "-"로 보이지만 합계로는 화면 어디에도 안 보였다.
//  4. is_final 확정가의 날짜를 as_of_kst 대신 trading_days 의 마지막
//     값에서 읽는다 — close.py 의 08시 확정 런은 "어제" 종가를 커밋하면서
//     "방금" 시각을 찍는다(latest=days[-1] 인데 as_of_kst=now_kst()).
//     as_of_kst 시각 옆에 그냥 "종가 확정"만 붙이면 어느 날의 종가인지
//     거짓을 말하게 된다.
//  5. benchmark_history(설계 §6-2, 최근 250거래일 지수)를 실제로 쓴다 —
//     원안은 benchmark(최신 지수 레벨 하나)만 화면에 찍었는데, 그건 이
//     데이터를 모으는 이유("장이 좋아서 번 것"과 "스크리너가 좋아서 번
//     것"을 가른다, §6-2)에 아무 답도 안 한다. 출처별 요약에 종결 종목
//     각각의 보유기간(매수일→매도일) 지수 수익률과 비교한 초과수익
//     평균(대비 KOSPI/KOSDAQ)을 추가했다.
//  6. #price 값을 Number() 로 바꾸기 전에 콤마·공백을 지운다(parsePrice) —
//     Task 11 이 #price 를 type=text+inputmode=numeric 으로 바꾼 이유
//     (콤마 포함 붙여넣기가 type=number 입력란에서 통째로 버려짐)를 여기서
//     실제로 지키지 않으면 그 변경이 무의미해진다.
//  7. #q 를 "입력하는 동안"(제출 시점이 아니라) 보유 여부를 판정해 매입/
//     매도 모드를 전환한다(applyMode/updateMode — Task 11 계약:
//     #mode/#price-label/#source-field/#form[data-mode]/#submit-btn).
//     제출 시점에만 판정하면 그 전까지 매입가 칸에 매도가를 조용히
//     입력하게 둔다(Task 11 지시문이 명시한 결함).
//  8. status/exits 가 서로 다른 이야기를 하는 항목(hand-edit 이 유일한
//     수리 경로라 손편집으로만 생길 수 있다 — apply_sell 은 둘을 항상
//     같이 바꾼다)을 "그럴듯하지만 틀린 값" 대신 "(상태 불일치)" 표시로
//     드러낸다. rows() 참조.
//  9. heldDays 가 종목마다 배열 indexOf 를 두 번 부르는 대신 rows() 가
//     한 번 만든 Map(dayIndex)을 쓴다 — trading_calendar.held_days 가
//     이미 dict 인덱스를 쓰는 것과 방식을 맞췄다. 이 규모(수십 건)에서
//     성능 문제는 아니었지만 공짜라 바꿨다.
// 10. 매입일 기본값을 trading_days 의 마지막 값 대신 오늘(KST) 날짜로
//     잡는다 — 정규장 마감(15:31~32) 전에는 trading_days 의 마지막 값이
//     아직 "어제"다(naver.fetch_bars: 당일 봉은 마감 후에야 나온다).
//     장중에 방금 산 걸 그 자리에서 적으면 매입일이 어제로 잘못 채워졌다.
// 11. window.open 이 팝업 차단으로 null 을 돌려주면 현재 탭에서 이동한다
//     (모바일 인앱 브라우저 등에서 버튼을 눌러도 반응이 없어 보이는 걸
//     막는다).
//
// 검토했지만 바꾸지 않은 것(각 지점 주석에 근거):
// adjustedBuy 의 분할 나눗셈 방향(구체적 예시로 검증 — 맞다), renderSummary
// 의 승률/평균수익률 대 평균보유 분모 차이(의도된 동작 — 계산 가능 조건
// 자체가 다르다), fillCandidates 의 앞/중간 분리(실제 4,299종목 데이터로
// 정확성·성능 확인 — 1ms 미만), resolveCode 의 이름 완전일치 폴백(실측
// 데이터 중복 이름 0건), ±30% 오타 가드가 신규 매수엔 구조적으로 못
// 걸리는 것(quotes.quotes 자체가 보유 중 종목만 담고 있어 페이지가
// 대안 시세를 구할 방법이 없다 — 신규 매수를 CORS 없이 검증하려면 별도
// 데이터가 필요한데 지금 파이프라인 범위 밖).

const RAW = "https://raw.githubusercontent.com/AMID815/mouigosa/data/";
const REPO = "https://github.com/AMID815/mouigosa";
const STALE_MIN = 40;               // 30분 주기 + 여유

async function load(name, fallback, opts) {
  opts = opts || {};
  const buster = opts.buster !== undefined ? opts.buster : Date.now();
  const cacheMode = opts.cacheMode || "no-store";
  try {
    const r = await fetch(RAW + name + "?t=" + buster, { cache: cacheMode });
    if (r.status === 404 && opts.allow404) {
      // positions.json 이 아직 한 번도 커밋되지 않은 정상적인 첫 실행
      // 상태 — 실패가 아니다.
      return { data: fallback, ok: true, notFound: true };
    }
    if (!r.ok) throw new Error("HTTP " + r.status);
    return { data: await r.json(), ok: true };
  } catch (e) {
    // 404(정상일 수 있음, 호출자가 allow404 로 이미 걸렀다)와 네트워크
    // 오류·5xx·JSON 파싱 실패(진짜 실패)는 이 시점부터는 구분하지 않는다 —
    // ok:false 하나로 합쳐 호출자에게 넘기고, 그 판단(화면에 뭐라고
    // 보여줄지)은 renderStale 이 한다. 여기서 콘솔에만 남기고 조용히
    // fallback 만 주면, "안 산 게 없어서 0건"과 "못 받아와서 0건"이
    // 화면에서 똑같이 보인다 — 이 과제가 지적한 결함.
    console.warn("load 실패:", name, e);
    return { data: fallback, ok: false, error: e };
  }
}

// 매입 평균가 — 수량을 기록하지 않으므로 단순평균이다 (v1 은 항상 1건)
const avgBuy = p => p.buys.reduce((s, b) => s + b.price, 0) / p.buys.length;
const exitPrice = p => (p.exits.length ? p.exits[p.exits.length - 1].price : null);
const pct = (from, to) => ((to - from) / from) * 100;

// 액면분할 보정: 매입가는 조정되지 않는데 네이버 시세는 조정된다.
// 보정하지 않으면 5:1 분할 다음날부터 -80% 로 보인다.
//
// 방향 검증(비판 포인트 5) — adjustments 를 쓰는 곳이 아직 없어 미검증
// 상태였다. 구체적 예시: 5:1 분할, 매입가 100,000원.
//   분할 후 네이버 종가는 소급 조정되어(설계 §6-3 실측: 알테오젠 사례)
//   같은 가치가 대략 100,000/5 = 20,000원대로 보인다(주수만 5배로 늘고
//   가치는 그대로). ratio=5로 나누면 adjustedBuy = 100,000/5 = 20,000 —
//   오늘 시세(20,000원대)와 같은 축이 되어 수익률이 0% 근처로 정확히
//   나온다. 나누지 않으면 pct(100000, 20000) = -80% 로 계산되어 위
//   주석이 말하는 증상과 정확히 일치한다 — 나누는 방향이 맞다는 뜻이다.
//   ratio 는 "분할 후 주수 / 분할 전 주수"(정배수 분할이면 5 같은 값,
//   1보다 큼) 관례를 전제한다 — 이 필드를 쓰는 첫 쓰기 코드가 이 관례를
//   지켜야 한다.
function adjustedBuy(p) {
  let v = avgBuy(p);
  for (const a of p.adjustments || []) {
    if (a.type === "split" && a.ratio > 0) v = v / a.ratio;
  }
  return v;
}

function heldDays(dayIndex, from, to) {
  if (from === null || to === null) return null;
  const i = dayIndex.get(from), j = dayIndex.get(to);
  if (i === undefined || j === undefined) return null;   // 클램프하지 않는다
  if (j < i) return null;                   // 역순 = 답할 수 없음 (파이썬과 같은 계약)
  return j - i;
}

function rows(state, quotes) {
  const days = quotes.trading_days || [];
  const dayIndex = new Map(days.map((d, i) => [d, i]));
  const last = days.length ? days[days.length - 1] : null;
  return (state.positions || []).map(p => {
    // 파이썬이 격리한(quarantined) 기록도 여기로 그대로 온다 — 페이지에는
    // normalize 가 없다. 화면에서 조용히 사라지면 안 되므로, 던지지 말고
    // '읽을 수 없음' 으로 표시한다.
    if (!Array.isArray(p.buys) || !p.buys.length
        || typeof p.buys[0]?.price !== "number") {
      return { p, bad: true, buy: null, now: null, ret: null, held: null,
               closed: p.status === "closed", halted: false, mismatch: false,
               buyDate: null, sellDate: null };
    }
    const buy = adjustedBuy(p);

    // status 와 exits 가 서로 다른 이야기를 할 수 있다(비판 포인트 2) —
    // apply_sell() 은 둘을 원자적으로 같이 바꾸므로 정상 경로에서는 절대
    // 어긋나지 않지만, positions.json 은 amend 연산이 없어 손편집이
    // 유일한 수리 경로다(구현계획.md 코드리뷰 이월). 손편집으로
    //   (a) status="closed" 인데 exits=[] (매도 기록을 빠뜨림), 또는
    //   (b) exits 는 있는데 status="open" 로 남음(되돌리는 걸 잊음)
    // 이 생길 수 있다. (a)를 무시하고 종전처럼 "오늘까지 보유"를 계산하면
    // 종결 표시된 행에 실시간 시세가 "현재가"인 척 붙는다(더 구체적인
    // 사실인 exits 를 무시하는 것) — 그래서 exits 유무를 closed 판정의
    // 1순위로 쓰고, 어긋나면 mismatch 로 표시해 화면에서 드러낸다.
    const hasExit = Array.isArray(p.exits) && p.exits.length > 0;
    const statusClosed = p.status === "closed";
    const mismatch = hasExit !== statusClosed;
    const closed = hasExit || statusClosed;

    const sold = exitPrice(p);   // hasExit 이면 마지막 매도가, 아니면 null
    const q = (quotes.quotes || {})[p.code];
    // statusClosed 인데 sold 가 null(=exits 없음, mismatch 케이스)이면
    // 실시간 시세를 "현재가"인 척 보여주지 않는다 — 종결로 표시되는 행에
    // 시세를 안 붙이는 게, 이미 팔았는데 아직 보유 중인 것처럼 보이는
    // 것보다 정직하다.
    const now = sold !== null ? sold : (statusClosed ? null : (q ? q.price : null));
    const until = sold !== null ? p.exits[p.exits.length - 1].date
                : (closed ? null : last);
    return {
      p, buy, now,
      ret: now === null ? null : pct(buy, now),
      held: heldDays(dayIndex, p.buys[0].date, until),
      closed, mismatch,
      halted: !!(q && q.status !== "tradable"),
      buyDate: p.buys[0].date,
      sellDate: sold !== null ? until : null,
    };
  });
}

function cell(tr, text, cls) {
  const td = document.createElement("td");
  td.textContent = text;                    // innerHTML 금지
  if (cls) td.className = cls;
  tr.appendChild(td);
}

const fmt = n => n === null || n === undefined ? "-" : Math.round(n).toLocaleString("ko-KR");
const fmtPct = n => n === null ? "-" : (n > 0 ? "+" : "") + n.toFixed(2) + "%";
const cls = n => n === null ? "" : (n > 0 ? "up" : n < 0 ? "down" : "");

function renderTable(id, list) {
  const tb = document.querySelector("#" + id + " tbody");
  tb.textContent = "";
  for (const r of list) {
    const tr = document.createElement("tr");
    const mark = r.bad ? " (읽을 수 없음)"
               : r.mismatch ? " (상태 불일치 — 확인 필요)"
               : (r.halted ? " (거래정지)" : "");
    cell(tr, (r.p.name || r.p.code || "?") + mark);
    cell(tr, fmt(r.buy));
    cell(tr, fmt(r.now));
    cell(tr, fmtPct(r.ret), cls(r.ret));
    cell(tr, r.held === null ? "범위 밖" : r.held + "일");
    cell(tr, r.p.source);
    tb.appendChild(tr);
  }
}

// 지수 대비 수익률(설계 §6-2) — from/to 두 날짜 모두 benchmark_history[idx]
// 에 있어야 계산된다. 벗어나면(250거래일 밖, 또는 그 지수가 그날 전부
// 실패해 history 자체에 키가 없음) null — 클램프하지 않는다.
function benchReturn(quotes, idx, from, to) {
  if (!from || !to) return null;
  const h = (quotes.benchmark_history || {})[idx];
  if (!h) return null;
  const a = h[from], b = h[to];
  if (typeof a !== "number" || typeof b !== "number") return null;
  return pct(a, b);
}

function renderSummary(list, quotes) {
  const done = list.filter(r => r.closed && r.ret !== null);
  const box = document.getElementById("summary");
  box.textContent = "";
  const add = (label, value) => {
    const d = document.createElement("div");
    const b = document.createElement("b"); b.textContent = value;
    const s = document.createElement("span"); s.textContent = " " + label;
    d.appendChild(b); d.appendChild(s); box.appendChild(d);
  };
  const wins = done.filter(r => r.ret > 0).length;
  add("종결", done.length + "건");
  add("승률", done.length ? Math.round((wins / done.length) * 100) + "%" : "-");
  const avg = done.length ? done.reduce((s, r) => s + r.ret, 0) / done.length : null;
  add("평균 수익률", fmtPct(avg));

  // 보유일수는 승률·평균수익률과 분모가 다르다(비판 포인트 4) — 매수일이
  // 250거래일 달력 밖이면 held 는 정직하게 null 이지 0 이 아니다. 승률·
  // 평균수익률은 매수가/매도가만 있으면 계산되지만 평균보유는 달력
  // 범위도 있어야 계산된다 — 계산 가능 조건 자체가 다른 지표라서 분모를
  // 일부러 맞추지 않는다. 맞추려고 held=null 인 종목을 승률에서도 빼면
  // "달력이 짧아서 보유일수를 모르는" 것 때문에 승률까지 왜곡된다.
  const held = done.filter(r => r.held !== null);
  add("평균 보유", held.length
    ? (held.reduce((s, r) => s + r.held, 0) / held.length).toFixed(1) + "일" : "-");

  // 출처별 — 이 트래커의 존재 이유
  // 출처는 일부러 고정 목록으로 검증하지 않는다 — 스크리너가 하나 늘면
  // 목록이 막는다. 대신 아는 넷이 아니면 화면에서 구분해 보여준다.
  const KNOWN = ["수동", "상단눌림", "상대강도", "눌림베팅", "종가베팅"];
  const bySrc = {};
  for (const r of done) {
    const key = KNOWN.includes(r.p.source) ? r.p.source : `${r.p.source} (?)`;
    (bySrc[key] ||= []).push(r);
  }
  const IDX = ["KOSPI", "KOSDAQ"];
  for (const [src, arr] of Object.entries(bySrc)) {
    const m = arr.reduce((s, r) => s + r.ret, 0) / arr.length;
    add(src + " (" + arr.length + ")", fmtPct(m));

    // 지수 대비 — "장이 좋아서 번 것"과 "스크리너가 좋아서 번 것"을 가른다
    // (설계 §6-2, benchmark_history 를 모으는 이유 그 자체). 종목별로
    // 매수일→매도일 구간의 지수 수익률을 구해 실현 수익률과 비교한 뒤,
    // 이 출처의 종결 종목 전체로 평균한다. 두 날짜가 다 있는 종목만
        // 평균에 들어간다(위 평균보유와 같은 이유 — 클램프하지 않는다).
    for (const idx of IDX) {
      const alphas = arr
        .map(r => {
          const ir = benchReturn(quotes, idx, r.buyDate, r.sellDate);
          return ir === null ? null : r.ret - ir;
        })
        .filter(a => a !== null);
      const am = alphas.length ? alphas.reduce((s, a) => s + a, 0) / alphas.length : null;
      add(src + " 대비 " + idx, fmtPct(am));
    }
  }
}

// 지수 현재 레벨 — 표시용(설계 §6-2). 위 renderSummary 의 "대비 KOSPI/
// KOSDAQ" 초과수익 카드와 헷갈리지 않도록 "지수"를 붙여 구분한다.
function renderBenchmark(quotes) {
  const b = quotes.benchmark || {};
  const box = document.getElementById("summary");
  for (const [name, val] of Object.entries(b)) {
    const d = document.createElement("div");
    const t = document.createElement("b"); t.textContent = val.toLocaleString("ko-KR");
    const s = document.createElement("span"); s.textContent = " " + name + " 지수";
    d.appendChild(t); d.appendChild(s); box.appendChild(d);
  }
}

function renderStale(quotes, flags) {
  flags = flags || {};
  const el = document.getElementById("stale");
  const at = document.getElementById("asof");
  const t = quotes.as_of_kst;
  const days = quotes.trading_days || [];
  const confirmedDate = days.length ? days[days.length - 1] : null;

  if (t) {
    let line = "마지막 갱신 " + t.replace("T", " ").slice(0, 16);
    if (quotes.is_final) {
      // is_final 확정가의 날짜는 as_of_kst 가 아니라 trading_days 의
      // 마지막 값에서 읽는다(비판 포인트 3) — close.py 의 08시 확정 런은
      // "어제" 종가를 커밋하면서 "방금" 시각을 as_of_kst 로 찍는다
      // (close.py: latest=days[-1], 스냅샷=quotes.build(..., now_kst())).
      // as_of_kst 옆에 그냥 "종가 확정"만 붙이면 오늘 새벽 시각이 마치
      // 그 시각의 종가인 것처럼 보인다 — 실제로는 하루 전 종가다.
      line += confirmedDate ? " (" + confirmedDate + " 종가 확정)" : " (종가 확정)";
    }
    at.textContent = line;
  } else {
    at.textContent = "데이터 없음";
  }

  // 경고는 여러 종류다. 전부 조용히 지나가면 안 되는 것들이라 같은
  // 배지에 모은다 — 화면 어디에도 안 보이면 없는 셈이 되는 값들이다.
  const msgs = [];

  // 로드 자체의 실패를 최우선으로 알린다(비판 포인트 1) — "정말 보유가
  // 없다"와 "받아오다 실패했다"는 다른 사실인데, 후자를 전자로 보이게
  // 두면 화면이 거짓을 말하는 셈이다.
  if (flags.positionsFailed) {
    msgs.push("positions.json을 불러오지 못했습니다 — 실제로 보유가 없는 것인지, " +
      "네트워크 문제로 못 받아온 것인지 이 화면만으로는 알 수 없습니다. 새로고침해주세요.");
  }
  if (flags.quotesFailed) {
    msgs.push("quotes.json을 불러오지 못했습니다 — 아래 표시된 값은 신뢰할 수 없습니다. 새로고침해주세요.");
  }

  if (t) {
    const mins = (Date.now() - new Date(t).getTime()) / 60000;
    if (mins > STALE_MIN) {
      msgs.push("갱신이 " + Math.round(mins) + "분째 없습니다. 휴장이거나 수집이 멈춘 상태일 수 있습니다.");
    }
  } else if (!flags.quotesFailed) {
    msgs.push("아직 발행된 데이터가 없습니다.");
  }

  const dropped = quotes.positions_dropped || 0;
  if (dropped) {
    // 손상된 기록은 시세가 안 붙는다. 화면에서 조용히 사라지면 안 된다.
    msgs.push("기록 " + dropped + "건을 읽지 못했습니다. positions.json 을 확인해주세요.");
  }

  // fail_count/missing 도 positions_dropped 와 같은 배지에(비판 포인트 3) —
  // 개별 행에는 "-"로 보이지만 합계로는 화면 어디에도 없었다.
  const failCount = quotes.fail_count || 0;
  if (failCount) {
    const missing = quotes.missing || [];
    msgs.push("시세 " + failCount + "건을 못 받았습니다" +
      (missing.length ? " (" + missing.join(", ") + ")" : "") + ".");
  }

  const benchFailed = quotes.benchmark_failed || [];
  if (benchFailed.length) {
    msgs.push("지수 " + benchFailed.join(", ") + " 조회에 실패했습니다 — 관련 비교값이 빠질 수 있습니다.");
  }

  el.hidden = msgs.length === 0;
  el.textContent = msgs.join(" / ");
}
