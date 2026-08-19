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
// 12. findOpenPosition 이 rows() 와 같은 "읽을 수 있는가"(isReadablePosition)
//     기준을 공유한다 — 로컬 fixture 로 실제 브라우저에서 통합 검증하다가
//     발견했다: status="open" 인데 buys=[] 인 손상 레코드(손편집으로만
//     가능)가 있으면, 이 가드 없이는 얼마에 샀는지도 모르는 기록을 그냥
//     "보유 중"으로 믿고 매도 모드로 전환해버린다.
//
// 2라운드 리뷰(실제 값 25개를 손계산으로 대조, 실브라우저 통합 검증) 반영:
//
// 13. main() 에 오류 경계가 없었다 — IIFE에 .catch 가 없고 window.onerror
//     류 핸들러도 없어서, 렌더 중 한 곳(예: benchmark 값에 null 하나만
//     섞여도 toLocaleString 이 던진다)이 던지면 그 아래 코드 전체(매입일
//     기본값·master.json 요청·자동완성·매도 판정)가 조용히 실행되지 않고
//     콘솔에만 남았다 — 정확히 설계가 이름 붙인 "겉보기엔 멀쩡한데 실은
//     고장난 화면"이었다. addStaleMessage/reportFatal 을 추가해 main()
//     호출과 렌더 블록을 각각 감싸고, window 의 error/unhandledrejection
//     도 같은 경로로 보낸다. 렌더 블록은 별도 try 로 감싸 그 실패가
//     아래(매입일 기본값·master.json 로드·자동완성/모드 배선)까지 끌고
//     내려가지 않게 했다 — master.json 을 첫 페인트 앞으로 다시 당기지는
//     않는다(항목 2 의 이유가 그대로 유효하다).
// 14. findOpenPosition 이 hasExitRecorded 도 확인한다 — status="open" 인데
//     exits 가 이미 있는 행은 rows() 가 이미 종결(closed, mismatch)로
//     보여주고 있는데, 이 가드가 없으면 같은 코드를 폼에서 고르는 순간
//     매도 모드로 전환되어 두 번째 exits 항목이 append 된다(apply_sell 은
//     id 중복 검사가 없다) — exitPrice() 가 마지막 값을 쓰므로 원래
//     매도가가 조용히 새 값으로 덮인다. 항목 12 와 같은 종류의 결함.
// 15. is_final 스냅샷에도 "몇 분째 갱신 없음"을 물었다 — quotes.yml 은
//     평일 09:00~15:30, close.py 는 17시·08시에만 돈다. 17:40 이후 다음날
//     09:00 전까지, 그리고 금요일 저녁부터 월요일 아침까지 계속 이
//     경보가 (정확한) 확정 종가를 두고 울렸다. is_final 이면 "몇 분"
//     대신 확정일(trading_days 마지막 값)과 오늘(KST) 날짜 차이가
//     STALE_CONFIRM_DAYS 를 넘는지로 판정한다 — 장중 수집이 실제로 멈춘
//     경우(is_final=false)는 그대로 "몇 분째"로 잡는다.
// 16. fillCandidates/resolveCode 가 라틴 문자를 대소문자 구분해서 비교했다
//     — #q 는 autocapitalize="off" 라 폰 키보드가 정확히 소문자를
//     만들어내는데("SK" 입력 의도가 "sk"로 찍힘), 그 소문자가 자동완성·
//     코드 해석 어느 쪽에서도 안 걸렸다. 양쪽 비교를 대소문자 무관으로
//     바꿨다 — 한글은 toUpperCase() 에 영향받지 않는다.
// 17. adjustments 가 있는 포지션은 가격 파생값(매입가·현재가·수익률)을
//     아예 계산하지 않는다 — adjustments 항목에 날짜가 없어서, 분할이
//     이 포지션의 보유기간 안에서 일어났는지(조정이 맞다) 매수 전/매도
//     후에 일어나 애초에 조정이 필요 없는지 페이지가 구분할 방법이
//     없다. 무조건 조정하면(닫힌 포지션, 분할 후 매수 등) 그럴듯한 틀린
//     숫자가 나오고, 무조건 안 하는 것도 틀릴 수 있다 — 그래서 어느
//     쪽도 확신할 수 없을 땐 계산 자체를 하지 않는다. needsAdjustReview
//     로 표시하고(rows), ret 를 null 로 둬 done 에서 자동으로 빠진다
//     (renderSummary 가 이미 하던 필터를 그대로 탄다).
//
// 검토했지만 바꾸지 않은 것(각 지점 주석에 근거):
// fillCandidates 의 앞/중간 분리(실제 4,299종목 데이터로 정확성·성능
// 확인 — 1ms 미만, 대소문자 처리만 항목 16 에서 추가), resolveCode 의
// 이름 완전일치 폴백(실측 데이터 중복 이름 0건), renderSummary 의
// 승률/평균수익률 대 평균보유 분모 차이(의도된 동작 — 계산 가능 조건
// 자체가 다르다), ±30% 오타 가드가 신규 매수엔 구조적으로 못 걸리는 것
// (quotes.quotes 자체가 보유 중 종목만 담고 있어 페이지가 대안 시세를
// 구할 방법이 없다 — master.json 에 시가총액 페이지의 현재가 컬럼을
// 얹는 별도 과제가 이걸 추가 요청 없이 풀 수 있다고 확인됨, 그쪽에서
// 처리 예정이라 여기서는 손대지 않았다).

const RAW = "https://raw.githubusercontent.com/AMID815/mouigosa/data/";
const REPO = "https://github.com/AMID815/mouigosa";
const STALE_MIN = 40;                // 30분 주기 + 여유 — 장중(is_final=false)에만 쓴다(항목 15)
const STALE_CONFIRM_DAYS = 4;        // 확정 종가가 이보다 오래 그대로면 경보 — 주말+연휴 흡수용 여유

// #stale 배지에 메시지 한 줄을 추가한다 — <ul><li> 로 쌓는다(리뷰: 163자
// 한 줄로 이어붙이면 375px 화면에서 102px 를 먹는다). textContent 로만
// 채운다. renderStale·reportFatal·master.json 로드 실패 알림이 전부 이
// 경로 하나로 모인다 — 호출 순서와 무관하게 항상 같은 모양으로 쌓인다.
function addStaleMessage(msg) {
  const el = document.getElementById("stale");
  if (!el) return;
  let ul = el.querySelector("ul");
  if (!ul) {
    ul = document.createElement("ul");
    ul.style.margin = "0";
    ul.style.paddingLeft = "1.2em";
    el.appendChild(ul);
  }
  const li = document.createElement("li");
  li.textContent = msg;
  ul.appendChild(li);
  el.hidden = false;
}

// 오류 경계(항목 13) — main() 에 .catch 도, window.onerror 류 핸들러도
// 없었다. 렌더 어딘가에서 한 번만 던져도(예: benchmark 값에 null 이
// 섞여 toLocaleString 이 던짐) 콘솔에만 남고 화면은 "고장난 채로 멀쩡해
// 보이는" 상태가 됐다 — 설계가 이름 붙인 그 실패 형태 그 자체. 어디서
// 나든 여기로 모아 배지에 남긴다.
function reportFatal(e) {
  console.error("치명적 오류:", e);
  const msg = e && e.message ? e.message : String(e);
  addStaleMessage("페이지 스크립트 오류로 일부 기능이 동작하지 않을 수 있습니다: " + msg
    + " — 새로고침해도 반복되면 콘솔을 확인해주세요.");
}

window.addEventListener("error", e => reportFatal(e.error || e.message));
window.addEventListener("unhandledrejection", e => reportFatal(e.reason));

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
// 나눗셈 방향 검증 — 구체적 예시: 5:1 분할, 매입가 100,000원.
//   분할 후 네이버 종가는 소급 조정되어(설계 §6-3 실측: 알테오젠 사례)
//   같은 가치가 대략 100,000/5 = 20,000원대로 보인다(주수만 5배로 늘고
//   가치는 그대로). ratio=5로 나누면 adjustedBuy = 100,000/5 = 20,000 —
//   오늘 시세(20,000원대)와 같은 축이 되어 수익률이 0% 근처로 정확히
//   나온다. 나누지 않으면 pct(100000, 20000) = -80% 로 계산되어 위
//   주석이 말하는 증상과 정확히 일치한다 — 나누는 방향이 맞다는 뜻이다.
//   ratio 는 "분할 후 주수 / 분할 전 주수"(정배수 분할이면 5 같은 값,
//   1보다 큼) 관례를 전제한다 — 이 필드를 쓰는 첫 쓰기 코드가 이 관례를
//   지켜야 한다.
//
// ⚠ 이 방향 검증은 "매수 시점이 분할 이전이고 지금도 보유 중"인 경우만
// 확인한 것이다(항목 17) — adjustments 항목에 날짜가 없어서, 종결된
// 포지션(매도가도 이미 원시 거래가라 조정이 필요 없을 수 있다)이나 분할
// "이후"에 산 포지션(매수가가 이미 조정된 축이라 또 나누면 안 된다)은
// 이 함수만으로는 옳게 처리할 수 없다 — 호출자(rows)가 그 두 경우를
// needsAdjustReview 로 걸러내고 나서만 이 함수를 부른다.
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

// buys[0].price 를 안전하게 읽을 수 있는가 — rows() 의 "읽을 수 없음" 판정과
// findOpenPosition() 의 매도 대상 판정이 이 기준을 공유한다(통합 테스트로
// 발견: 손편집으로 status="open" 인데 buys=[] 인 손상 레코드가 있으면,
// 이 검사 없이는 findOpenPosition 이 그걸 "정상적으로 보유 중"이라고 믿고
// 매도 모드로 전환해버린다 — 실제로는 얼마에 샀는지조차 모르는 기록인데
// 매도가를 받아 이슈를 연다).
function isReadablePosition(p) {
  return Array.isArray(p.buys) && p.buys.length > 0 && typeof p.buys[0]?.price === "number";
}

// 실제로 매도 기록이 있는가 — rows() 의 closed 판정과 findOpenPosition()
// 의 매도-대상 판정이 이 기준을 공유한다(항목 8, 14). 공유하지 않으면
// status="open" 인데 exits 가 이미 있는 행(rows() 는 이미 종결로 보여줌)을
// findOpenPosition 이 여전히 매도 가능이라고 믿어, 같은 종목을 폼에서
// 다시 고르면 두 번째 exits 항목이 append 된다(apply_sell 은 id 중복
// 검사가 없다) — exitPrice() 가 마지막 값을 쓰므로 원래 매도가가 조용히
// 새 값으로 덮인다.
function hasExitRecorded(p) {
  return Array.isArray(p.exits) && p.exits.length > 0;
}

function rows(state, quotes) {
  const days = quotes.trading_days || [];
  const dayIndex = new Map(days.map((d, i) => [d, i]));
  const last = days.length ? days[days.length - 1] : null;
  return (state.positions || []).map(p => {
    // 파이썬이 격리한(quarantined) 기록도 여기로 그대로 온다 — 페이지에는
    // normalize 가 없다. 화면에서 조용히 사라지면 안 되므로, 던지지 말고
    // '읽을 수 없음' 으로 표시한다.
    if (!isReadablePosition(p)) {
      return { p, bad: true, buy: null, now: null, ret: null, held: null,
               closed: p.status === "closed", mismatch: false,
               needsAdjustReview: false, halted: false,
               buyDate: null, sellDate: null };
    }

    // status 와 exits 가 서로 다른 이야기를 할 수 있다(항목 8) —
    // apply_sell() 은 둘을 원자적으로 같이 바꾸므로 정상 경로에서는 절대
    // 어긋나지 않지만, positions.json 은 amend 연산이 없어 손편집이
    // 유일한 수리 경로다(구현계획.md 코드리뷰 이월). 손편집으로
    //   (a) status="closed" 인데 exits=[] (매도 기록을 빠뜨림), 또는
    //   (b) exits 는 있는데 status="open" 로 남음(되돌리는 걸 잊음)
    // 이 생길 수 있다. (a)를 무시하고 종전처럼 "오늘까지 보유"를 계산하면
    // 종결 표시된 행에 실시간 시세가 "현재가"인 척 붙는다(더 구체적인
    // 사실인 exits 를 무시하는 것) — 그래서 exits 유무를 closed 판정의
    // 1순위로 쓰고, 어긋나면 mismatch 로 표시해 화면에서 드러낸다.
    const hasExit = hasExitRecorded(p);
    const statusClosed = p.status === "closed";
    const mismatch = hasExit !== statusClosed;
    const closed = hasExit || statusClosed;

    // adjustments 에 날짜가 없다(항목 17) — 이 포지션에 분할 조정 항목이
    // 하나라도 있으면, 그게 보유기간 "안"에서 일어나 조정이 맞는지 매수
    // 전/매도 후라 조정하면 안 되는지 이 페이지는 구분할 방법이 없다.
    // 어느 쪽으로 계산해도 그럴듯한 틀린 숫자가 나올 수 있으니, 가격
    // 파생값(buy/now/ret) 은 아예 계산하지 않는다 — 보유일수는 날짜만
    // 있으면 되므로(가격 조정과 무관) 그대로 계산한다.
    const needsAdjustReview = Array.isArray(p.adjustments) && p.adjustments.length > 0;
    if (needsAdjustReview) {
      const until = hasExit ? p.exits[p.exits.length - 1].date : (closed ? null : last);
      return {
        p, buy: null, now: null, ret: null,
        held: heldDays(dayIndex, p.buys[0].date, until),
        closed, mismatch, needsAdjustReview, halted: false,
        buyDate: p.buys[0].date, sellDate: hasExit ? until : null,
      };
    }

    const buy = adjustedBuy(p);   // adjustments 가 비어있으므로 avgBuy(p) 와 동일하다
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
      closed, mismatch, needsAdjustReview,
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
    // 독립된 문제들이라 동시에 나올 수 있다(예: 상태 불일치이면서 동시에
    // 거래정지) — 우선순위 삼항연산자로 하나만 고르면 나머지가 조용히
    // 가려진다. 전부 모아서 보여준다.
    let mark = "";
    if (r.bad) {
      mark = " (읽을 수 없음)";
    } else {
      const flags = [];
      if (r.needsAdjustReview) flags.push("액면조정 확인 필요");
      if (r.mismatch) flags.push("상태 불일치");
      if (r.halted) flags.push("거래정지");
      if (flags.length) mark = " (" + flags.join(", ") + ")";
    }
    cell(tr, (r.p.name || r.p.code || "?") + mark);
    cell(tr, fmt(r.buy));
    cell(tr, fmt(r.now));
    cell(tr, fmtPct(r.ret), cls(r.ret));
    cell(tr, r.held === null ? "범위 밖" : r.held + "일");
    cell(tr, r.p.source || "(출처 없음)");   // positions.json 은 normalize() 를 안 거친다 — 필드 누락 가능
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

  // 보유일수는 승률·평균수익률과 분모가 다르다 — 매수일이
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
    // positions.json 은 normalize() 를 안 거치므로 source 가 아예 없을 수
    // 있다 — 그대로 두면 "undefined (?)" 타일이 뜬다.
    const src = r.p.source || "(출처 없음)";
    const key = KNOWN.includes(src) ? src : `${src} (?)`;
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
    // val 이 숫자가 아니면(예: 지수 조회가 부분 실패해 null 이 섞임)
    // toLocaleString 이 던진다 — 카드 하나를 건너뛰는 게 렌더 전체를
    // 막는 것보다 낫다(항목 13, F1). 이런 값은 quotes.build 가 만들지
    // 않지만, main() 에도 오류 경계를 둔 것과 같은 이유로 여기서도 방어한다.
    if (typeof val !== "number") continue;
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
      // 마지막 값에서 읽는다(항목 4) — close.py 의 08시 확정 런은
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

  // 로드 자체의 실패를 최우선으로 알린다(항목 1) — "정말 보유가
  // 없다"와 "받아오다 실패했다"는 다른 사실인데, 후자를 전자로 보이게
  // 두면 화면이 거짓을 말하는 셈이다.
  if (flags.positionsFailed) {
    msgs.push("positions.json을 불러오지 못했습니다 — 실제로 보유가 없는 것인지, " +
      "네트워크 문제로 못 받아온 것인지 이 화면만으로는 알 수 없습니다. 새로고침해주세요.");
  }
  if (flags.quotesFailed) {
    msgs.push("quotes.json을 불러오지 못했습니다 — 아래 표시된 값은 신뢰할 수 없습니다. 새로고침해주세요.");
  }

  // "몇 분째 갱신 없음"은 장중 스냅샷(is_final=false, quotes.py 가 30분
  // 마다 찍음)에만 묻는다(항목 15) — close.py 는 17시·08시 하루 두 번만
  // 돌고, is_final 스냅샷은 17:40 부터 다음날 09:00 전까지, 그리고
  // 금요일 저녁부터 월요일 아침까지 정상적으로 "오래" 그대로다. 그
  // 동안 "몇 분째"로 물으면 정확한 확정 종가를 두고 매번 오경보가 뜬다.
  // is_final 이면 대신 확정된 날짜 자체가 오늘(KST)과 며칠 차이나는지로
  // 판정한다 — 연휴가 겹쳐도 잘못 울리지 않도록 STALE_CONFIRM_DAYS 만큼
  // 여유를 둔다(그래도 아주 긴 연휴가 겹치면 드물게 울릴 수 있다 — 페이지가
  // 미래 휴장일을 미리 알 방법이 없어 감수한 트레이드오프다).
  if (t) {
    if (!quotes.is_final) {
      const mins = (Date.now() - new Date(t).getTime()) / 60000;
      if (mins > STALE_MIN) {
        msgs.push("갱신이 " + Math.round(mins) + "분째 없습니다. 휴장이거나 수집이 멈춘 상태일 수 있습니다.");
      }
    } else if (confirmedDate) {
      const kstToday = new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10);
      const daysSince = Math.floor(
        (new Date(kstToday) - new Date(confirmedDate)) / 86400000);
      if (daysSince > STALE_CONFIRM_DAYS) {
        msgs.push("확정 종가가 " + daysSince + "일째 갱신되지 않았습니다(" + confirmedDate
          + "). 파이프라인이 멈췄을 수 있습니다.");
      }
    }
  } else if (!flags.quotesFailed) {
    msgs.push("아직 발행된 데이터가 없습니다.");
  }

  const dropped = quotes.positions_dropped || 0;
  if (dropped) {
    // 손상된 기록은 시세가 안 붙는다. 화면에서 조용히 사라지면 안 된다.
    msgs.push("기록 " + dropped + "건을 읽지 못했습니다. positions.json 을 확인해주세요.");
  }

  // fail_count/missing 도 positions_dropped 와 같은 배지에(항목 3) —
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

  // <ul><li> 로 쌓는다(항목: 163자 한 줄로 이어붙이면 375px 화면에서
  // 102px 를 먹는다) — addStaleMessage 가 el 을 비우지 않고 li 만
  // 추가하므로, 여기서 먼저 el 을 완전히 리셋한다(재호출 대비).
  el.textContent = "";
  for (const m of msgs) addStaleMessage(m);
  el.hidden = msgs.length === 0;
}

// ── Task 13: 입력 폼 → 이슈 URL ─────────────────────────────────────────

let MASTER = [], NAMES = new Map(), STATE = { positions: [] }, QUOTES = {};
let masterLoadFailed = false;    // 제출 시 안내 문구를 바꾸는 데만 쓴다

function fillCandidates(q) {
  const dl = document.getElementById("cands");
  dl.textContent = "";
  if (q.length < 1) return;
  // MASTER 는 시가총액 순 배열이다. 앞에서부터 20개를 그냥 자르면 안 되고
  // (그러면 질의와 무관하게 큰 회사만 나온다) 매칭된 것 중에서 순서를 지킨다.
  //
  // 실측(4,299종목 실제 master.json): "삼" 입력 시 360건만 스캔하고
  // 20건에서 멈춘다(삼성 계열이 대형주라 앞쪽에서 빨리 찬다), "SK" 는
  // 1,192건 스캔, 전혀 안 걸리는 질의도 전체 스캔에 약 1.2ms(개발 PC,
  // 벤치). 브라우저 JS 엔진에서는 이보다 빠르면 빨랐지 느리지 않다 —
  // 입력 이벤트마다 다시 돌려도 체감 지연이 없다.
  //
  // 대소문자 무관 비교(항목 16) — #q 는 autocapitalize="off" 라 폰
  // 키보드가 "SK"를 정확히 "sk"로 만들어낸다. 코드는 이미 항상 대문자
  // (master.json 실측)라 query 쪽만 올려도 되지만, 이름 쪽("NAVER" 등
  // 라틴 종목명)은 양쪽 다 올려야 맞는다. 한글은 toUpperCase() 에
  // 영향받지 않는다.
  const qU = q.toUpperCase();
  const 앞 = [], 중간 = [];
  for (const [code, name] of MASTER) {
    const nameU = name.toUpperCase();
    if (code === qU || code.startsWith(qU) || nameU.startsWith(qU)) 앞.push([code, name]);
    else if (nameU.includes(qU)) 중간.push([code, name]);
    if (앞.length >= 20) break;
  }
  for (const [code, name] of 앞.concat(중간).slice(0, 20)) {
    const o = document.createElement("option");
    o.value = name + " (" + code + ")";     // value 는 textContent 경로가 아니다
    dl.appendChild(o);
  }
}

function resolveCode(text) {
  // 종목코드는 영숫자 6자다 — 숫자 6자가 아니다 (설계 §6-1, 실측 375종목).
  // 대소문자도 허용하고 대문자로 올린다(항목 16) — datalist 선택값은
  // 항상 대문자로 조립되지만(master.json 이 항상 대문자), 손으로 붙여
  // 넣으면 소문자가 섞일 수 있다.
  const m = text.match(/\(([0-9A-Za-z]{6})\)\s*$/);
  if (m) return m[1].toUpperCase();
  const t = text.trim().toUpperCase();
  if (/^[0-9A-Z]{6}$/.test(t) && NAMES.has(t)) return t;
  // 이름 완전일치 폴백 — 실측(2026-08-20, 4,299종목) 중복 이름 0건 확인.
  // 대소문자 무관 비교(항목 16) — "NAVER"를 폰에서 "naver"로 치면
  // 원래 실패했다. 그래도 미래에 상장폐지·재상장 등으로 이름이 겹치면
  // 시가총액 순으로 먼저 온 것을 고른다(가장 그럴듯한 후보).
  for (const [code, name] of MASTER) if (name.toUpperCase() === t) return code;
  return null;
}

function findOpenPosition(code) {
  // 두 가드를 같이 건다(항목 12, 14):
  //   isReadablePosition — 매수가를 알 수 없는 손상 레코드를 "보유 중이라
  //     매도 가능"으로 착각하면 안 된다(위 isReadablePosition 옆 주석).
  //   !hasExitRecorded — status="open" 인데 exits 가 이미 있는 행은
  //     rows() 가 이미 종결(mismatch)로 보여주고 있다. 이 가드가 없으면
  //     같은 코드를 폼에서 다시 고르는 순간 매도 모드로 전환되어 두
  //     번째 exits 항목이 append 되고(apply_sell 은 id 중복 검사가
  //     없다), exitPrice() 가 마지막 값을 쓰므로 원래 매도가가 조용히
  //     새 값으로 덮인다(위 hasExitRecorded 옆 주석).
  return STATE.positions.find(p => p.code === code && p.status === "open"
                                    && isReadablePosition(p) && !hasExitRecorded(p));
}

// #price 는 type=number 가 아니라 text+inputmode=numeric 이다(Task 11
// 계약) — "247,500"처럼 콤마 포함으로 붙여넣으면 type=number 입력란은
// 값을 통째로 버린다. Number() 에 넣기 전에 콤마·공백을 지운다(항목 6) —
// 안 지우면 Number("247,500") 은 NaN 이라 "매입가를 확인해주세요"로
// 막히는데, 사용자 눈엔 분명 맞는 값을 넣었는데 왜 막히는지 알 길이 없다.
function parsePrice(raw) {
  return Number(String(raw).replace(/[,\s]/g, ""));
}

// Task 11 계약: #q 에 고른 종목이 보유 중(open)인 코드와 일치하면 매도
// 모드로 전환하되, 그 사실을 화면에 드러낸다. 매입 모드 복귀 시 반대로
// 되돌린다.
function applyMode(isSell) {
  const modeEl = document.getElementById("mode");
  const label = document.getElementById("price-label");
  const srcField = document.getElementById("source-field");
  const form = document.getElementById("form");
  const btn = document.getElementById("submit-btn");
  if (isSell) {
    modeEl.hidden = false;
    modeEl.textContent = "매도 입력 — 보유 중인 종목입니다";
    label.textContent = "매도가";
    srcField.hidden = true;      // 매도에는 출처가 의미 없다
    form.dataset.mode = "sell";
    btn.textContent = "매도 이슈 열기";
  } else {
    modeEl.hidden = true;
    modeEl.textContent = "";
    label.textContent = "매입가";
    srcField.hidden = false;
    form.dataset.mode = "buy";
    btn.textContent = "깃허브에서 저장";
  }
}

function updateMode() {
  // 종목을 "고르는 시점"에 판정한다 — 제출 시점까지 미루면 그 전까지
  // 매입가 칸에 매도가를 조용히 입력하게 둔다(항목 7, Task 11 지시문이
  // 명시한 결함). resolveCode 가 실패하면(아직 완전히 선택되지 않은
  // 입력 중) 매입 모드로 되돌린다 — 직전에 다른 보유 종목을 골랐다가
  // 지우는 중이라면 매도 모드가 그대로 남아있는 쪽이 더 위험하다.
  const code = resolveCode(document.getElementById("q").value);
  applyMode(!!(code && findOpenPosition(code)));
}

function issueUrl(title, payload) {
  const body = "모의고사 입력\n\n```json\n" + JSON.stringify(payload) + "\n```";
  return REPO + "/issues/new?title=" + encodeURIComponent(title)
              + "&body=" + encodeURIComponent(body);
}

function onSubmit(ev) {
  ev.preventDefault();
  const text = document.getElementById("q").value;
  const code = resolveCode(text);
  if (!code) {
    return alert(masterLoadFailed
      ? "종목 목록을 불러오지 못해 코드를 확인할 수 없습니다. 새로고침 후 다시 시도해주세요."
      : "종목을 목록에서 골라주세요.");
  }
  const price = parsePrice(document.getElementById("price").value);
  const date = document.getElementById("date").value;
  if (!(price > 0)) return alert("매입가를 확인해주세요.");
  if (!date) return alert("매입일을 골라주세요.");

  const open = findOpenPosition(code);

  // 오타 방지: 직전 종가 대비 ±30% 를 벗어나면 되묻는다.
  //
  // quotes.quotes 는 "지금 보유 중(open)"인 종목만 담는다(quotes.py
  // open_codes 가 status==open 인 코드만 조회한다). 매도는 이 종목이
  // 이미 open 이었어야 하므로 q 가 항상 존재해 가드가 반드시 걸린다.
  // 반대로 신규 매수(아직 한 번도 안 산 종목)는 이 코드가 quotes.quotes
  // 에 애초에 없으므로 q 가 undefined 라 가드가 구조적으로 통과한다 —
  // 페이지가 CORS 로 네이버를 직접 못 불러서(설계 §6-2) 보유 중이 아닌
  // 임의 종목의 참고가를 별도로 구할 방법이 없기 때문이다. 이건 이
  // 파일만으로는 못 고친다 — master.py 가 이미 매일 훑는 시가총액
  // 87페이지에 현재가 컬럼이 있어(parse_market_sum 이 이미 정규식으로
  // 잡는 표 안) 추가 요청 없이 master.json 에 실을 수 있다는 게 확인돼
  // 있고, 그 작업은 별도 과제로 진행 중이다 — 여기서는 그 데이터가
  // 없다는 전제로 그대로 둔다.
  const q = (QUOTES.quotes || {})[code];
  if (q && Math.abs(pct(q.price, price)) > 30) {
    if (!confirm("최근 종가 " + fmt(q.price) + "원과 " + Math.round(Math.abs(pct(q.price, price)))
                 + "% 차이입니다. 그대로 진행할까요?")) return;
  }

  const payload = open
    ? { op: "sell", code, price, date, reason: document.getElementById("memo").value }
    : { op: "buy", code, name: NAMES.get(code) || code, price, date,
        source: document.getElementById("source").value,
        memo: document.getElementById("memo").value };
  const url = issueUrl((open ? "SELL " : "BUY ") + (NAMES.get(code) || code), payload);

  // 새 탭으로 연다 — 트래커 화면은 그대로 두고 이슈만 따로 제출한 뒤
  // 돌아와 다음 기록을 이어 넣을 수 있게. 항목 11 — 팝업이 막히면
  // (모바일 인앱 브라우저 등) window.open 이 null 을 돌려준다. 그때는
  // 조용히 아무 일도 안 일어나는 대신 현재 탭에서 이동한다 — 버튼을
  // 눌렀는데 반응이 없어 보이는 것보다 낫다. 제출 핸들러 안에서 동기적
  // 으로만 호출하므로(중간에 await 없음) 사용자 제스처가 살아있어
  // 팝업 차단을 안 타는 게 보통이다 — confirm() 이 끼어드는 경우에도
  // 같은 태스크 안에서 동기 실행이라 활성화 상태가 유지된다.
  const win = window.open(url, "_blank", "noopener");
  if (!win) location.href = url;
}

document.getElementById("q").addEventListener("input", e => {
  fillCandidates(e.target.value);
  updateMode();
});
document.getElementById("form").addEventListener("submit", onSubmit);

(async function main() {
  // KST 기준 "오늘" 문자열 — master.json 캐시버스터(하루 한 번만 바뀌면
  // 됨)와 매입일 기본값(아래) 둘 다에 쓴다. 기기 로캘에 기대지 않고
  // UTC+9 를 명시적으로 더한다 — 파이썬 쪽 KST = timezone(timedelta(hours=9))
  // 와 같은 근거. Date.now()+9시간은 항상 파싱 가능한 10자리 문자열을
  // 내므로 이 값 자체가 비어있을 일은 없다.
  const kstToday = new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10);

  // positions.json·quotes.json 만 먼저 받는다 — 표를 그리는 데 필요한
  // 전부다. master.json(207KB)은 자동완성에만 쓰이므로 이 Promise.all
  // 밖에서, 표가 그려진 뒤에 받는다(항목 2 — 첫 페인트를 막지 않는다).
  const [posRes, qtRes] = await Promise.all([
    load("positions.json", { positions: [] }, { allow404: true }),
    load("quotes.json", {}),
  ]);
  STATE = posRes.data;
  QUOTES = qtRes.data;

  // 렌더는 별도 try 로 감싼다(항목 13, F1) — 여기서 하나라도 던지면(예:
  // benchmark 값에 null 이 섞여 renderBenchmark 가 던짐) 그 아래 폼
  // 배선(매입일 기본값·master.json 로드·자동완성/모드)까지 실행이
  // 멈춰서, 표는 그려졌는데 폼은 고장난 "겉보기엔 멀쩡한" 상태가 된다.
  // master.json 을 이 앞으로 다시 당기지는 않는다 — 그러면 항목 2 가
  // 고친 첫 페인트 지연이 되살아난다.
  try {
    renderStale(QUOTES, { positionsFailed: !posRes.ok, quotesFailed: !qtRes.ok });
    const all = rows(STATE, QUOTES);
    renderTable("open", all.filter(r => !r.closed));
    renderTable("closed", all.filter(r => r.closed));
    renderSummary(all, QUOTES);
    renderBenchmark(QUOTES);
  } catch (e) {
    reportFatal(e);
  }

  // 매입일 기본값 — 저녁에 그날 매매를 몰아 적는 게 가장 흔한 경로지만,
  // 장중(정규장 마감 15:31~32 전)에 방금 산 걸 바로 적는 경우도 있다.
  // trading_days 의 마지막 값은 그 시간대엔 아직 "어제"다(naver.py:
  // 당일 봉은 마감 뒤에야 나온다) — 그대로 기본값으로 쓰면 장중 입력마다
  // 매입일이 어제로 잘못 채워진다(항목 10). 오늘(KST) 날짜를 기본값으로
  // 쓰면 장중·마감 후 둘 다 맞는다. 장이 안 열린 날(주말 등)이면
  // 사용자가 손으로 고치면 되는데, 그 반대(장중에 매번 어제로 잘못
  // 채워지는 것)보다 드문 불편이다.
  document.getElementById("date").value = kstToday;

  // master.json 은 표 렌더와 무관하니 여기서부터 비동기로 받는다(항목 2).
  // cacheMode:"default" — no-store 를 계속 쓰면 같은 날 안에 새로고침할
  // 때마다 207KB 를 매번 다시 받는다. 캐시버스터가 이미 날짜라 브라우저
  // HTTP 캐시가 자연히 하루 단위로 갱신된다.
  const msRes = await load("master.json", { items: [] },
                            { buster: kstToday, cacheMode: "default" });
  MASTER = Array.isArray(msRes.data.items) ? msRes.data.items : [];
  NAMES = new Map(MASTER);
  masterLoadFailed = !msRes.ok;
  if (masterLoadFailed) {
    // 실패해도 화면 어디에도 안 보이던 유일한 실패 지점이었다 — 표는
    // 그려지고 배지도 안 뜨고 자동완성은 그냥 조용히 빈 채로 남아,
    // 사용자가 폼을 다 채우고 제출을 눌러야 비로소(alert 로) 알게 됐다.
    addStaleMessage("종목 목록(master.json)을 불러오지 못했습니다 — 자동완성과 "
      + "매도 판정이 동작하지 않습니다. 새로고침해주세요.");
  }
  // 표가 그려지는 동안 사용자가 이미 입력을 시작했을 수 있으니, 마스터가
  // 늦게 도착하면 지금 값 기준으로 자동완성·모드를 한 번 더 채운다.
  fillCandidates(document.getElementById("q").value);
  updateMode();
})().catch(reportFatal);   // 항목 13, F1 — 위 개별 try 가 못 잡는 나머지 전부
