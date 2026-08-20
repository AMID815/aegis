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
// 3라운드(master.json 매입가 참조 과제) 반영:
//
// 18. ±30% 오타 가드가 신규 매수(quotes.quotes 에 없는 코드)엔 구조적으로
//     못 걸리던 걸 고쳤다 — master.json 의 items 가 [코드, 이름] 에서
//     [코드, 이름, 가격] 으로 늘었다(master.py: naver.parse_market_sum 이
//     시가총액 페이지에서 이미 훑던 표의 현재가 컬럼을 추가 요청 없이
//     실었다, 2026-08-20 실측 4,299종목 전수 확인). referencePrice(code)
//     가 quotes.quotes 를 먼저 보고 없으면 MASTER_PRICES(master.json 에서
//     뽑은 코드→가격 Map)로 폴백한다 — 매도(항상 quotes 에 있다)와 신규
//     매수(quotes 에 없다) 양쪽에 같은 함수 하나를 쓴다. 두 참조 모두
//     없으면(코드가 아직 master 에도 없거나, 가격을 못 읽어 null이거나,
//     master.json 로드 자체가 실패했으면) 조용히 가드를 건너뛴다 — 기존
//     "q 가 undefined 면 그냥 안 묻는다" 패턴을 그대로 확장한 것이다.
//     master.json 로드 실패는 이미 이전부터 별도 배지로 알리고 있었는데
//     (masterLoadFailed), 이제 그 실패가 매입 가드에도 영향을 준다는
//     문구를 덧붙였다 — 파일 전체가 없다는 "구조적" 실패는 계속
//     소리내어 알리고, 종목 하나에 참고가가 없는 "개별" 경우는 계속
//     조용히 넘어간다(항목 8 이 positions.json 에서 쓰는 것과 같은
//     구분 — 구조 손상은 크게, 개별 누락은 조용히).
//     [코드, 이름] 만 읽던 기존 JS(배열 구조분해·`new Map(MASTER)`)는
//     세 번째 요소가 늘어도 그대로 동작한다 — 실브라우저로 확인함(커밋
//     메시지 참조). ±30% 라는 문턱 값 자체는 그대로 뒀다 — master.json
//     참조가 quotes.json 보다 며칠 더 오래됐을 수 있어도, 상한가가 이미
//     같은 크기(±30%)라 문턱을 넓히면 진짜 오타를 더 자주 놓치고,
//     좁히면 정상적인 상한가 매수마다 헛되이 되묻는다 — 확인창 한 번의
//     비용과 오타 하나가 종목 실현손익을 -90%로 오염시키는 비용(§11)은
//     대칭이 아니라서, 기존 값을 재검토할 근거를 찾지 못했다.
//
// 검토했지만 바꾸지 않은 것(각 지점 주석에 근거):
// fillCandidates 의 앞/중간 분리(실제 4,299종목 데이터로 정확성·성능
// 확인 — 1ms 미만, 대소문자 처리만 항목 16 에서 추가), resolveCode 의
// 이름 완전일치 폴백(실측 데이터 중복 이름 0건), renderSummary 의
// 승률/평균수익률 대 평균보유 분모 차이(의도된 동작 — 계산 가능 조건
// 자체가 다르다).

const RAW = "https://raw.githubusercontent.com/AMID815/mouigosa/data/";
const REPO = "https://github.com/AMID815/mouigosa";
const STALE_MIN = 40;                // 30분 주기 + 여유 — 장중(is_final=false)에만 쓴다(항목 15)
const STALE_CONFIRM_DAYS = 4;        // 확정 종가가 이보다 오래 그대로면 경보 — 주말+연휴 흡수용 여유

// Cloudflare Worker 쓰기 프록시 주소(2026-08-20 배포로 채워짐; 절차는
// worker/README.md). index.html 의 CSP connect-src 안 같은 문자열도 함께 바꿔야
// 한다(둘 중 하나만 바꾸면 CSP 가 요청을 막는데, isWorkerConfigured() 는 이
// 문자열만 보고 판단하므로 "설정된 것"으로 오판해 fetch 를 시도했다가
// CSP 위반으로 실패한다 — tryWorker() 의 catch 가 이것도 네트워크 실패와
// 똑같이 처리해 폴백으로 넘어가므로 사용자 경험은 안전하지만, 의도한 대로
// Worker 를 쓰고 있는지는 README 4단계대로 두 곳 다 바꿨는지 확인해야 안다).
const WORKER_URL = "https://mouigosa-intake.amid815.workers.dev";

// 이 자리표시자로 남아있는 동안은 fetch 자체를 시도하지 않는다 — 어차피
// 실패할 요청을 매번 던져 콘솔에 오류만 쌓는 대신, "미설정"임을 바로
// 판단해 곧장 깃허브 폴백으로 넘어간다(Worker 미배포 상태에서도 이 화면이
// 예전(Task 13)과 똑같이 동작해야 한다는 요구 그대로).
function isWorkerConfigured() {
  return !WORKER_URL.includes("REPLACE_WITH_YOUR_WORKER_URL");
}

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
    // orders/auto 는 이 함수 자신은 안 쓴다 — nameCell (렌더 쪽)이 자동
    // 예외 표시·토글 버튼을 그리는 데 쓴다. 갈래마다 따로 넣으면 하나라도
    // 빠뜨려 nameCell 이 undefined 를 만나기 쉬우니, 갈래를 타기 전에
    // 한 번만 계산해 모든 return 문에 그대로 얹는다.
    const orders = p.orders || {};
    const auto = p.auto !== false;

    // 지정가 관찰(watch) 대기 기록 — 아직 아무것도 안 샀으므로 buys 가
    // 정상적으로 비어 있다. isReadablePosition 기준(아래)으로 판정하면
    // "읽을 수 없음"으로 잘못 뜬다 — 이 기록은 손상이 아니라 정상적인
    // 대기 상태다. 매입가/현재가/수익률은 아직 의미가 없으므로(1차 매수도
    // 안 됐다) 지정가를 "매입가" 칸에 목표로 보여주고 나머지는 비운다.
    if (p.status === "pending") {
      const watchPrice = p.watch && typeof p.watch.price === "number" ? p.watch.price : null;
      return { p, pending: true, bad: false, buy: watchPrice, now: null, ret: null,
               held: null, closed: false, mismatch: false, needsAdjustReview: false,
               halted: false, buyDate: null, sellDate: null, orders, auto };
    }

    // 파이썬이 격리한(quarantined) 기록도 여기로 그대로 온다 — 페이지에는
    // normalize 가 없다. 화면에서 조용히 사라지면 안 되므로, 던지지 말고
    // '읽을 수 없음' 으로 표시한다.
    if (!isReadablePosition(p)) {
      return { p, bad: true, pending: false, buy: null, now: null, ret: null, held: null,
               closed: p.status === "closed", mismatch: false,
               needsAdjustReview: false, halted: false,
               buyDate: null, sellDate: null, orders, auto };
    }

    // status 와 exits 가 서로 다른 이야기를 할 수 있다(항목 8) —
    // apply_sell() 은 둘을 원자적으로 같이 바꾸므로 정상 경로에서는 절대
    // 어긋나지 않는다. amend(Task 15, scripts/models.py apply_amend)가
    // 생긴 뒤에도 이 어긋남 자체는 amend 로 못 고친다 — status 는 amend
    // 화이트리스트 밖이라 아예 못 바꾸고, exits 도 amend 로는 새로 못
    // 만들고 못 지운다(이미 있는 exits[0] 의 price/date/reason 만 고칠 수
    // 있다). 그래서 손편집이 여전히 유일한 수리 경로다. 손편집으로
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
        p, pending: false, buy: null, now: null, ret: null,
        held: heldDays(dayIndex, p.buys[0].date, until),
        closed, mismatch, needsAdjustReview, halted: false,
        buyDate: p.buys[0].date, sellDate: hasExit ? until : null,
        orders, auto,
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
      p, pending: false, buy, now,
      ret: now === null ? null : pct(buy, now),
      held: heldDays(dayIndex, p.buys[0].date, until),
      closed, mismatch, needsAdjustReview,
      halted: !!(q && q.status !== "tradable"),
      buyDate: p.buys[0].date,
      sellDate: sold !== null ? until : null,
      orders, auto,
    };
  });
}

function cell(tr, text, cls) {
  const td = document.createElement("td");
  td.textContent = text;                    // innerHTML 금지
  if (cls) td.className = cls;
  tr.appendChild(td);
}

// 종목명 칸 — Task 15 "고치기" 버튼을 여기 얹는다. 새 열을 만들지 않고
// 기존 첫 열 안에 이름과 버튼을 나란히 둔다(375px 가로 스크롤 표에서
// 열을 늘리면 중요한 숫자들이 더 밀려난다 — 구현계획.md 리뷰). 이름은
// createElement + textContent 로만 넣는다(innerHTML 금지, 종목명이 DOM에
// 닿는 가장 위험한 지점).
//
// 버튼은 r.bad(읽을 수 없는 기록)이거나 id 가 없는 기록에는 안 붙인다 —
// bad 기록은 어차피 이 파일 전체가 intake.py 의 최상위 손상 가드에
// 걸려 어떤 op 도 반영될 수 없다(정상 기록까지 포함해서). "고치기"를
// 눌러 이슈를 열어도 절대 반영될 수 없는 버튼을 보여주는 것보다,
// 아예 안 보여주는 쪽이 정직하다.
function nameCell(tr, r, mark) {
  // <td> 자체는 손대지 않는다 — 일반 table-cell 로 남겨 다른 열과 같은
  // 폭 협상 규칙을 그대로 따르게 하고, flex 는 안에 넣는 별도 div 에만
  // 준다(style.css .name-cell 옆 주석 — <td> 에 직접 display:flex 를
  // 주면 브라우저별로 table-cell 참여 여부가 갈릴 수 있는 지점이다).
  const td = document.createElement("td");
  const wrap = document.createElement("div");
  wrap.className = "name-cell";
  const span = document.createElement("span");
  span.textContent = (r.p.name || r.p.code || "?") + mark;
  wrap.appendChild(span);
  if (!r.bad && typeof r.p.id === "string" && r.p.id) {
    // 대기(pending) 기록에는 고치기를 달지 않는다. 달면 startAmend 가
    // isReadablePosition(buys 가 비어 있어 false)에서 막으면서 "이 기록은
    // 형식이 올바르지 않아 고칠 수 없습니다" 라고 말하는데, 그건 거짓이다
    // — 손상된 게 아니라 아직 안 산 것뿐이다. 사용자가 파일이 깨졌다고
    // 믿고 손편집하러 가게 만드는, amend 가 없애려던 바로 그 루프다.
    // (지정가 자체를 고치는 건 아직 연산이 없다 — 지우고 다시 넣는다.)
    if (!r.pending) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "amend-btn";
    btn.textContent = "고치기";
    btn.dataset.id = r.p.id;
    btn.setAttribute("aria-label", "고치기: " + (r.p.name || r.p.code || "?"));
    wrap.appendChild(btn);
    }

    // 자동/수동 토글 — 종결된 기록(closed)은 더 이상 물타기·익절·손절의
    // 대상이 아니므로(전부 이미 끝났다) 보여줄 이유가 없다. 열려 있거나
    // (open) 아직 체결 전(pending)인 기록에만 단다 — 이 두 상태만 앞으로
    // 자동 매매가 실제로 일어날 수 있다.
    if (!r.closed) {
      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.className = "auto-toggle-btn";
      toggleBtn.textContent = r.auto === false ? "자동 전환" : "수동 전환";
      toggleBtn.dataset.id = r.p.id;
      toggleBtn.dataset.code = r.p.code;
      toggleBtn.dataset.nextAuto = r.auto === false ? "true" : "false";   // 누르면 될 다음 값
      toggleBtn.setAttribute("aria-label",
        (r.auto === false ? "자동 매매로 전환: " : "자동 매매 예외(수동)로 전환: ")
        + (r.p.name || r.p.code || "?"));
      wrap.appendChild(toggleBtn);
    }
  }
  td.appendChild(wrap);

  // 자동 예외로 지정된 기록은 표에서 바로 구분되어야 한다. 안 그러면
  // "왜 이 종목만 자동 체결이 안 되지" 를 알 방법이 없다. r.bad 여부와
  // 무관하게 확인한다 — 손상된 기록이라도 저장된 auto:false 는 여전히
  // 사실이라, 그 상태를 굳이 이 표시에서만 숨길 이유가 없다(위 wrap 은
  // r.bad 면 고치기/토글 버튼이 없을 뿐 이름 자체는 항상 그린다).
  if (r.auto === false) {
    const s = document.createElement("span");
    s.className = "manual-mark";
    s.textContent = " [수동]";
    s.title = "자동 매매 예외 — 물타기·익절·손절이 모두 멈춰 있습니다";
    td.appendChild(s);
  }
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
    } else if (r.pending) {
      // pending 은 구조적으로 bad/needsAdjustReview/mismatch/halted 어느
      // 것도 동시에 될 수 없다(아직 buys 자체가 없다) — 괄호 플래그 목록과
      // 섞이지 않는 대괄호로 확실히 구분한다.
      mark = " [대기]";
    } else {
      const flags = [];
      if (r.needsAdjustReview) flags.push("액면조정 확인 필요");
      if (r.mismatch) flags.push("상태 불일치");
      if (r.halted) flags.push("거래정지");
      if (flags.length) mark = " (" + flags.join(", ") + ")";
    }
    nameCell(tr, r, mark);
    cell(tr, fmt(r.buy));
    cell(tr, fmt(r.now));
    cell(tr, fmtPct(r.ret), cls(r.ret));
    // pending 은 아직 보유가 시작되지 않아 "범위 밖"(=달력 범위 밖이라 못
    // 구함)이라는 문구가 사실과 다르게 읽힌다 — 아직 세기 시작도 안 했다는
    // 뜻으로 "-" 를 쓴다.
    cell(tr, r.pending ? "-" : (r.held === null ? "범위 밖" : r.held + "일"));
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

  // 미결 건수 — 설계 §11 의 한계를 화면이 드러내야 한다. 2차·3차가 끝내
  // 안 걸리고 익절도 안 닿은 종목은 손절 경로가 없어 영원히 열려 있다.
  // 이걸 안 보여주면 승률이 "닫힌 것 중 이긴 비율"이라는 사실이 가려져서,
  // 미결이 쌓일수록 실제보다 좋아 보인다.
  const openRows = list.filter(r => !r.closed && !r.bad && !r.pending);
  add("미결", openRows.length + "건");
  const openHeld = openRows.filter(r => r.held !== null);
  add("미결 평균 보유", openHeld.length
    ? (openHeld.reduce((s, r) => s + r.held, 0) / openHeld.length).toFixed(1) + "일" : "-");

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
let MASTER_PRICES = new Map();   // 코드 → 가격(있으면 int, 없으면 null) — 항목 18
let masterLoadFailed = false;    // 제출 시 안내 문구를 바꾸는 데만 쓴다

// Task 15: amend 모드 상태. null 이면 매입/매도 모드(#q 로 암묵 전환).
// 값이 있으면 amend 모드 — #q 를 바꿔도 매입/매도로 되돌아가지 않고,
// #cancel-btn 으로만 나간다. 이 객체는 "고치기"를 누른 시점의 스냅샷이다
// (STATE 에서 읽은 값 — 재조회가 아니다). 그게 왜 맞는지는 buildAmendPatch
// 옆 주석 참조(diff 기준을 뭘로 잡을지의 핵심 결정).
let amendTarget = null;

// KST 기준 "오늘" 문자열 하나로 통일한다 — main() 의 매입일 기본값과
// exitAmendMode() 의 리셋이 서로 다른 계산을 하면 자정 근처에서 하루
// 어긋날 수 있다.
function kstTodayStr() {
  return new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10);
}

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

// 오타 가드(onSubmit)의 참고가 — 항목 18. quotes.quotes 는 "지금 보유
// 중(open)"인 종목만 담는다(quotes.py open_codes 가 status==open 인
// 코드만 조회한다). 매도는 이 종목이 이미 open 이었어야 하므로 대부분
// q 가 있어 그 값을 그대로 쓴다. 신규 매수(아직 한 번도 안 산 종목)는
// 이 코드가 quotes.quotes 에 애초에 없다 — master.json 의 시가총액
// 현재가 컬럼(naver.parse_market_sum, master.py 가 매일 갱신)으로
// 폴백한다. 둘 다 없으면(코드가 master 에도 없거나, 가격을 못 읽어
// null이거나, master.json 로드 자체가 실패해 MASTER_PRICES 가 비어
// 있으면) null 을 돌려준다 — 호출자가 그 경우 가드를 조용히 건너뛴다.
// 개별 종목 하나에 참고가가 없는 흔한 경우(신규상장 등)마다 확인창을
// 띄우면, 정말 오타를 잡아야 할 때 사용자가 반사적으로 넘기게 된다 —
// master.json 로드 자체가 실패한 "구조적" 경우는 이미 별도 배지로
// 알린다(masterLoadFailed, main() 참조).
function referencePrice(code) {
  const q = (QUOTES.quotes || {})[code];
  if (q) return q.price;
  const m = MASTER_PRICES.get(code);
  return (m === undefined || m === null) ? null : m;
}

// #price 는 type=number 가 아니라 text+inputmode=numeric 이다(Task 11
// 계약) — "247,500"처럼 콤마 포함으로 붙여넣으면 type=number 입력란은
// 값을 통째로 버린다. Number() 에 넣기 전에 콤마·공백을 지운다(항목 6) —
// 안 지우면 Number("247,500") 은 NaN 이라 "매입가를 확인해주세요"로
// 막히는데, 사용자 눈엔 분명 맞는 값을 넣었는데 왜 막히는지 알 길이 없다.
function parsePrice(raw) {
  return Number(String(raw).replace(/[,\s]/g, ""));
}

// 매입/매도/amend 세 모드가 건드리는 요소 8개(#mode, #price-label,
// #source-field, #form[data-mode], #submit-btn, #cancel-btn,
// #signal-date-field, exit-* 필드 3개)를 **한 함수가 모드마다 전부**
// 설정한다 — 리뷰 C2 이전에는 applyMode(매입/매도)와 applyModeAmend(amend)
// 가 서로 다른 부분집합만 건드려서, updateMode() 가 amend 도중 실수로
// 불리면(main() 끝의 가드 없는 호출 — master.json 로딩 중 버튼 클릭)
// #mode/#price-label/... 은 매도 모드로 바뀌는데 #cancel-btn/
// exit-*-field 는 amend 상태 그대로 남아 화면과 amendTarget 이 서로 다른
// 이야기를 하는 상태가 됐다(실측: 화면은 "매도가"인데 실제로 제출되는
// 값은 buy.price 로 들어감). 한 함수가 모드마다 8개 전부를 명시적으로
// 정하면 이 종류의 부분 갱신 자체가 불가능하다.
function applyMode(mode, opts) {
  opts = opts || {};
  const modeEl = document.getElementById("mode");
  const label = document.getElementById("price-label");
  const priceField = document.getElementById("price-field");
  const price = document.getElementById("price");
  const srcField = document.getElementById("source-field");
  const form = document.getElementById("form");
  const btn = document.getElementById("submit-btn");
  const cancelBtn = document.getElementById("cancel-btn");
  const sigField = document.getElementById("signal-date-field");

  form.dataset.mode = mode;

  if (mode === "sell") {
    modeEl.hidden = false;
    modeEl.textContent = "매도 입력 — 보유 중인 종목입니다";
    label.textContent = "매도가";
    priceField.hidden = false;
    price.required = true;
    srcField.hidden = true;      // 매도에는 출처가 의미 없다
    btn.textContent = "매도 저장";   // Worker 연동 전엔 "매도 이슈 열기" — 이제 주 경로가 깃허브 이슈를 직접 열지 않는다
    cancelBtn.hidden = true;
    sigField.hidden = true;
    setExitFieldsVisible(false);
    setWatchFieldVisible(false);
  } else if (mode === "amend") {
    modeEl.hidden = false;
    modeEl.textContent = "고치기 — 기존 기록을 고치는 중입니다";
    label.textContent = "매입가";
    priceField.hidden = false;
    price.required = true;
    srcField.hidden = false;
    btn.textContent = "고치기 반영";
    cancelBtn.hidden = false;
    sigField.hidden = false;
    setExitFieldsVisible(!!opts.hasExit);
    setWatchFieldVisible(false);
  } else if (mode === "watch") {
    // Task 13(지정가 관찰) — #price 대신 #watch-price 를 받는다. 매입가
    // 필드를 숨기는 김에 required 도 같이 끈다(아래 setWatchFieldVisible
    // 옆 주석과 같은 이유 — 숨은 필드에 required 가 남으면 submit 자체가
    // 죽는다). #source-field 는 켜 둔다 — 관찰도 어느 스크리너의 신호로
    // 시작한 것일 수 있어 출처가 여전히 의미 있다(지시문).
    modeEl.hidden = false;
    modeEl.textContent = "지정가 관찰 — 목표가에 닿으면 1차 매수가 자동 체결됩니다";
    label.textContent = "매입가";   // 숨어서 안 보이지만, buy 로 되돌아갈 때 바로 맞는 문구가 되도록 미리 맞춰둔다
    priceField.hidden = true;
    price.required = false;
    srcField.hidden = false;
    btn.textContent = "관찰 시작";
    cancelBtn.hidden = true;
    sigField.hidden = true;
    setExitFieldsVisible(false);
    setWatchFieldVisible(true);
  } else {   // "buy" — 기본값
    modeEl.hidden = true;
    modeEl.textContent = "";
    label.textContent = "매입가";
    priceField.hidden = false;
    price.required = true;
    srcField.hidden = false;
    btn.textContent = "저장";   // Worker 연동 전엔 "깃허브에서 저장" — 이제 주 경로가 깃허브 이슈를 직접 열지 않는다
    cancelBtn.hidden = true;
    sigField.hidden = true;
    setExitFieldsVisible(false);
    setWatchFieldVisible(false);
  }
}

function updateMode() {
  // 종목을 "고르는 시점"에 판정한다 — 제출 시점까지 미루면 그 전까지
  // 매입가 칸에 매도가를 조용히 입력하게 둔다(항목 7, Task 11 지시문이
  // 명시한 결함). resolveCode 가 실패하면(아직 완전히 선택되지 않은
  // 입력 중) 매입 모드로 되돌린다 — 직전에 다른 보유 종목을 골랐다가
  // 지우는 중이라면 매도 모드가 그대로 남아있는 쪽이 더 위험하다.
  //
  // 호출하는 쪽(#q 입력 리스너, main() 끝)이 전부 amendTarget 가드를
  // 진 채로 불러야 한다 — 리뷰 C2: main() 끝의 호출에 가드가 빠져 있어,
  // master.json 로딩 중(await 이후) amend 로 이미 들어간 상태에서 이
  // 함수가 다시 불리면 방금 amend 로 고르고 있던 "보유 중" 종목이 그대로
  // findOpenPosition 에 걸려 매도 모드로 화면을 덮어썼다. 방어를 이
  // 함수 안에도 한 번 더 둔다 — 호출부 가드가 나중에 또 빠지더라도
  // amend 도중에는 최소한 이 함수 자체가 아무 것도 안 하게.
  if (amendTarget) return;
  // Task 13(지정가 관찰) — #entry-mode 가 "watch" 면 #q 로 고른 종목의
  // 보유 여부와 무관하게 관찰 모드를 유지한다. 이 가드가 없으면, 이미
  // 보유 중인 종목의 코드를 입력하는 순간(드물지만 막을 이유도 없는
  // 경우) findOpenPosition 이 걸려 사용자가 방금 고른 "지정가 관찰"을
  // 코드가 조용히 "매도"로 되돌려버린다.
  const entryMode = document.getElementById("entry-mode").value;
  if (entryMode === "watch") {
    applyMode("watch");
    return;
  }
  const code = resolveCode(document.getElementById("q").value);
  applyMode(code && findOpenPosition(code) ? "sell" : "buy");
}

// ── Task 15: amend 모드 ──────────────────────────────────────────────────

// hidden 인 컨트롤에 required 가 걸려 있으면 constraint validation 이
// 포커스할 수 없는 요소에서 막혀 submit 이벤트 자체가 안 나간다(리뷰
// C1, 실측 — 매입/매도/열린 기록 amend 전부 이렇게 죽어 있었다). 그래서
// index.html 은 이 두 입력에 정적 required 를 안 두고, 이 함수가 보일 때만
// required 를 켠다 — hidden 토글과 required 토글을 한 곳에서 같이 관리해
// 서로 어긋날 수 없게 한다.
function setExitFieldsVisible(v) {
  document.getElementById("exit-price-field").hidden = !v;
  document.getElementById("exit-date-field").hidden = !v;
  document.getElementById("exit-reason-field").hidden = !v;
  document.getElementById("exit-price").required = v;
  document.getElementById("exit-date").required = v;
}

// Task 13(지정가 관찰) — #watch-price 도 같은 함정을 갖고 있다: hidden 인
// 컨트롤에 required 가 남아 있으면 그 필드에서 constraint validation 이
// 막혀 submit 이벤트 자체가 안 나간다(위 setExitFieldsVisible 옆 주석,
// 리뷰 C1 이 실제로 겪은 사고). hidden 과 required 를 항상 한 자리에서
// 같이 켜고 끈다.
function setWatchFieldVisible(v) {
  document.getElementById("watch-field").hidden = !v;
  document.getElementById("watch-price").required = v;
}

// #source 는 고정 5개 옵션 select 다(매입 모드는 항상 이 중 하나만 쓴다).
// amend 로 고치는 기존 기록의 source 는 그 5개 밖의 임의 문자열일 수
// 있다(models._text 는 20자 이하 문자열이면 뭐든 받는다 — 손편집이든,
// 향후 다른 값이든). select 에 없는 값을 그냥 .value = x 로 넣으면
// 브라우저는 선택을 못 만들고 빈 채로 남는다 — 그 상태로 diff 를 돌리면
// "출처를 안 건드렸는데 ''로 바뀐 것"처럼 보여 source:"" 를 보내고,
// 이건 서버에서 "수동"으로 리셋된다(구현계획.md 실측) — 손 안 댄 필드를
// 지워버리는 바로 그 사고. 목록에 없는 값이면 임시 옵션을 추가해서
// 진짜로 선택 가능하게 만든다.
function setSourceSelectValue(value) {
  const sel = document.getElementById("source");
  const known = Array.from(sel.options).some(o => o.value === value);
  if (!known) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value;
    opt.dataset.amendExtra = "1";
    sel.appendChild(opt);
  }
  sel.value = value;
}

function clearExtraSourceOptions() {
  document.getElementById("source").querySelectorAll('option[data-amend-extra="1"]')
    .forEach(o => o.remove());
}

// "고치기" 버튼(renderTable/nameCell 이 만든다)의 위임 클릭 핸들러 — 표는
// 매 렌더마다 tbody 를 통째로 비우므로(renderTable), 리스너는 살아있는
// 상위 <table> 에 한 번만 건다.
function onAmendButtonClick(e) {
  const btn = e.target.closest(".amend-btn");
  if (!btn) return;
  startAmend(btn.dataset.id);
}

// 자동/수동 토글 — 같은 위임 클릭 패턴을 쓴다(위 onAmendButtonClick 과
// 같은 이유: renderTable 이 매 렌더마다 tbody 를 통째로 비운다). 고치기와
// 달리 폼을 거치지 않고 즉시 쓰기 요청을 내보내므로(리뷰할 폼 화면이
// 없다), 그 자리에서 confirm() 으로 한 번 확인한다 — 특히 수동 전환은
// 물타기·익절·손절을 전부 멈추는 결정이라 실수로 누른 걸 되돌리기 전에
// 최소한 한 번은 되묻는 게 맞다고 판단했다.
function onAutoToggleButtonClick(e) {
  const btn = e.target.closest(".auto-toggle-btn");
  if (!btn) return;
  const id = btn.dataset.id;
  const code = btn.dataset.code;
  const nextAuto = btn.dataset.nextAuto === "true";
  const p = STATE.positions.find(x => x.id === id);
  const name = (p && (p.name || p.code)) || code;
  const question = nextAuto
    ? "\"" + name + "\" 을(를) 다시 자동 매매로 되돌릴까요? (물타기·익절·손절이 다시 자동으로 걸립니다)"
    : "\"" + name + "\" 을(를) 수동으로 전환할까요? (물타기·익절·손절이 모두 멈춥니다)";
  if (!confirm(question)) return;
  // await 하지 않는다 — writeRecord() 의 첫 줄(window.open)이 아직 이
  // 클릭 이벤트와 같은 동기 구간 안에서 실행돼야(async 함수는 첫 await
  // 전까지 호출자와 같은 태스크에서 그대로 실행된다) 팝업 차단을 피할 수
  // 있다(onSubmit 옆 주석과 같은 요령). 실패해도 결과는 renderResult()가
  // 화면에 남기고, 남는 예외는 전역 unhandledrejection 경계(reportFatal)
  // 가 받는다.
  writeRecord({ op: "auto", id, was: code, auto: nextAuto },
              (nextAuto ? "AUTO-ON " : "AUTO-OFF ") + name, name);
}

// id 로 STATE 에서 기록을 찾아 amend 폼을 채운다. **재조회하지 않는다** —
// 이미 로드된 STATE 를 그대로 쓴다. 이게 diff 기준(어떤 필드를 "안 바뀜"
// 으로 볼지)이 되어야 다음 문제를 피한다: 만약 여기서 다시 fetch 해서
// 그 값으로 폼을 채우면, 그 사이(폼을 열고 제출하기 전) 다른 기기가 이
// 기록의 다른 필드를 이미 고쳤을 때 — 사용자가 손대지 않은 그 필드가
// 최신값과 달라 보여서 "바뀐 것"으로 오인되어 patch 에 실리고, 최신값을
// 조용히 되돌려버린다(구현계획.md 가 지목한 "낡은 값을 되살리는" 실패
// 모드). STATE 기준으로 채우면, 그 필드는 폼에도 여전히 옛 값이 그대로
// 보이고 diff 도 "안 바뀜"으로 보여 patch 에서 빠진다 — 사용자가 안 만진
// 필드를 결과적으로 안전하게 건드리지 않는다. 신원 확인(was/was_price)은
// 여기서 하지 않는다 — 제출 직전 재조회(onAmendSubmit)가 그 몫이다.
function startAmend(id) {
  // 이미 다른 기록을 amend 중이면(다른 행의 "고치기"를 눌렀다) 지금까지
  // 입력한 내용은 서버에 전혀 안 남아 있다 — 조용히 버리면 사용자가
  // 모르고 잃을 수 있으니 한 번 확인한다. 같은 기록을 다시 누른 경우는
  // (id 가 같으면) 그냥 STATE 기준으로 다시 채운다 — 되물을 이유가 없다.
  if (amendTarget && amendTarget.id !== id) {
    if (!confirm("다른 기록을 고치는 중입니다. 지금 입력한 내용을 버리고 이 기록을 고칠까요?")) return;
  }
  const p = STATE.positions.find(x => x.id === id);
  if (!p || !isReadablePosition(p)) {
    alert("이 기록은 형식이 올바르지 않아 고칠 수 없습니다.");
    return;
  }
  let exitBaseline = null;
  if (hasExitRecorded(p)) {
    const e0 = p.exits[0];
    // 저장된 exits[0] 자체가 손상됐으면(문자열 원소, price/date 누락 등 —
    // 손편집으로만 가능) 그 값을 폼에 채울 수 없다. exit 필드를 숨긴 채
    // 매수/종목/출처/메모/시그널일만 고칠 수 있게 한다 — apply_amend 도
    // 이런 기록에서 exit 를 굳이 요구하지 않으면 손상 검사를 하지 않는다.
    if (e0 && typeof e0.price === "number" && typeof e0.date === "string") {
      exitBaseline = {
        price: e0.price, date: e0.date,
        reason: typeof e0.reason === "string" ? e0.reason : "",
      };
    }
  }

  amendTarget = {
    id: p.id,
    code: p.code,
    // normalize() 의 기본값 규칙과 맞춘다 — 서버도 amend 적용 전에
    // normalize() 를 거치므로, "현재 값"의 정의가 서로 달라 없는 필드를
    // 있는 것처럼 보내는 일이 없게 한다.
    name: p.name || p.code,
    source: p.source || "수동",
    memo: p.memo || "",
    signalDate: p.signal_date || null,
    buyPrice: p.buys[0].price,
    buyDate: p.buys[0].date,
    exit: exitBaseline,   // null 이면 이 amend 는 exit 를 건드릴 수 없다
  };

  clearExtraSourceOptions();
  document.getElementById("q").value = amendTarget.name + " (" + amendTarget.code + ")";
  document.getElementById("price").value = String(amendTarget.buyPrice);
  document.getElementById("date").value = amendTarget.buyDate;
  setSourceSelectValue(amendTarget.source);
  document.getElementById("memo").value = amendTarget.memo;
  document.getElementById("signal-date").value = amendTarget.signalDate || "";
  if (exitBaseline) {
    document.getElementById("exit-price").value = String(exitBaseline.price);
    document.getElementById("exit-date").value = exitBaseline.date;
    document.getElementById("exit-reason").value = exitBaseline.reason;
  } else {
    document.getElementById("exit-price").value = "";
    document.getElementById("exit-date").value = "";
    document.getElementById("exit-reason").value = "";
  }

  applyMode("amend", { hasExit: !!exitBaseline });

  // adjustments 가 있는 기록은 표에 매입가/현재가/수익률이 전부 "-"로
  // 보인다(항목 17 — 조정 방향을 판단할 근거가 없어 계산 자체를 건너뛴다).
  // amend 는 adjustments 를 건드리지 않고, 여기 채운 매입가는 조정되지
  // 않은 원본 저장값(p.buys[0].price)이다 — 표시값("-")과 다르게 보여
  // 헷갈릴 수 있으니 그 사실을 그대로 알린다. 버튼 자체를 막지 않는 이유:
  // code/name/source/memo/signal_date, 그리고 buy/exit 의 값 자체를
  // 고치는 데는 adjustments 유무가 아무 영향이 없다 — 화면 파생값 계산만
  // adjustments 때문에 보류된 것이지, 저장된 원본값은 이 기록도 다른
  // 기록과 똑같이 정상이다.
  if (Array.isArray(p.adjustments) && p.adjustments.length) {
    document.getElementById("mode").textContent +=
      " (액면조정 기록 있음 — 매입가는 조정 전 원본 저장값이며, 고치기는 조정값을 건드리지 않습니다)";
  }

  document.getElementById("form").scrollIntoView({ behavior: "smooth", block: "start" });
}

// amend 를 명시적으로 나간다(#cancel-btn, index.html 계약; onAmendSubmit
// 성공 후에도 부른다 — 아래 참조) — 매입/매도는 #q 로 암묵 전환되지만
// amend 는 그렇지 않다(항목: "화면 - 지켜야 할 것"). applyMode("buy") 가
// #cancel-btn/#signal-date-field/exit-* 를 포함해 여덟 요소를 전부
// 매입 모드로 되돌리므로 여기서 따로 되돌리지 않는다(리뷰 C2 — 모드별
// 요소를 두 곳에서 나눠 관리하던 게 문제의 근원이었다).
function exitAmendMode() {
  amendTarget = null;
  clearExtraSourceOptions();
  document.getElementById("q").value = "";
  document.getElementById("price").value = "";
  document.getElementById("date").value = kstTodayStr();
  document.getElementById("source").value = "수동";
  document.getElementById("memo").value = "";
  document.getElementById("signal-date").value = "";
  document.getElementById("exit-price").value = "";
  document.getElementById("exit-date").value = "";
  document.getElementById("exit-reason").value = "";
  // amend 로 들어오기 전에 "지정가 관찰"을 골라뒀을 수 있다 — applyMode("buy")
  // 는 화면을 강제로 매입 모드로 되돌리는데, #entry-mode 를 그대로 두면
  // 셀렉트는 "관찰"을 가리키면서 화면은 매입가 칸을 보여주는 어긋난
  // 상태가 된다(다음 #entry-mode change 나 #q input 이 있기 전까지).
  document.getElementById("entry-mode").value = "buy";
  document.getElementById("watch-price").value = "";
  applyMode("buy");
  fillCandidates("");
}

// amendTarget(고치기를 누른 시점의 스냅샷) 과 현재 폼 값을 비교해 **바뀐
// 필드만** 담은 patch 를 만든다(구현계획.md "안 고친 키는 아예 빼고
// 보낸다" — patch 는 키의 유무로 판단하지 값이 비었는지로 판단하지
// 않는다). code 는 바뀔 때만 name 과 함께 싣는다 — name 을 독립적으로
// 고치는 입력란은 없다(#q 가 곧 종목 선택이다, applyMode 의 buy 모드와
// 같은 설계). 반환값이 null 이면 검증 실패로 이미 alert 를 띄운 뒤다.
function buildAmendPatch() {
  const target = amendTarget;
  const text = document.getElementById("q").value;
  const code = resolveCode(text);
  if (!code) {
    alert(masterLoadFailed
      ? "종목 목록을 불러오지 못해 코드를 확인할 수 없습니다. 새로고침 후 다시 시도해주세요."
      : "종목을 목록에서 골라주세요.");
    return null;
  }
  const price = parsePrice(document.getElementById("price").value);
  const date = document.getElementById("date").value;
  if (!(price > 0)) { alert("매입가를 확인해주세요."); return null; }
  if (!date) { alert("매입일을 골라주세요."); return null; }

  const patch = { op: "amend", id: target.id };

  if (code !== target.code) {
    patch.code = code;
    patch.name = NAMES.get(code) || code;   // code 없이 name 만, name 없이 code 만 보내지 않는다
  }

  const buyPatch = {};
  if (price !== target.buyPrice) buyPatch.price = price;
  if (date !== target.buyDate) buyPatch.date = date;
  if (Object.keys(buyPatch).length) patch.buy = buyPatch;

  if (target.exit) {
    const exitPrice_ = parsePrice(document.getElementById("exit-price").value);
    const exitDate = document.getElementById("exit-date").value;
    const exitReason = document.getElementById("exit-reason").value;
    if (!(exitPrice_ > 0)) { alert("매도가를 확인해주세요."); return null; }
    if (!exitDate) { alert("매도일을 골라주세요."); return null; }
    const exitPatch = {};
    if (exitPrice_ !== target.exit.price) exitPatch.price = exitPrice_;
    if (exitDate !== target.exit.date) exitPatch.date = exitDate;
    if (exitReason !== target.exit.reason) exitPatch.reason = exitReason;
    if (Object.keys(exitPatch).length) patch.exit = exitPatch;
  }

  const source = document.getElementById("source").value;
  if (source !== target.source) patch.source = source;
  const memo = document.getElementById("memo").value;
  if (memo !== target.memo) patch.memo = memo;
  const sigVal = document.getElementById("signal-date").value;      // "" 또는 YYYY-MM-DD
  const sigTarget = target.signalDate || "";
  if (sigVal !== sigTarget) patch.signal_date = sigVal;   // "" 는 서버에서 null 로 정규화된다(models.apply_amend)

  const changed = "code" in patch || "buy" in patch || "exit" in patch
    || "source" in patch || "memo" in patch || "signal_date" in patch;
  if (!changed) {
    alert("바뀐 내용이 없습니다.");
    return null;
  }
  return patch;
}

// amend 제출 — buy/sell(onSubmit)과 다른 경로다: 이슈 URL 을 만들기
// 직전에 positions.json 을 다시 받는다(구현계획.md "화면 - 지켜야 할
// 것" 1번, 이게 유일한 방어다). id 는 날짜+코드라서, 이 기록의 buy.date
// 를 amend 로 옮기면 옛 id 가 비고, 그 사이 같은 코드로 정말 새 매수가
// 그 자리를 다시 채우면 낡은 amend 이슈가 엉뚱한(새) 기록을 고칠 수
// 있다 — was 코드 하나로는 못 막는다(같은 코드니까). was/was_price 는
// 그래서 항상 이 재조회 결과에서 뽑는다 — buildAmendPatch 가 쓰는
// amendTarget(폼을 연 시점의 스냅샷)에서 뽑지 않는다. load() 의 기본값이
// 이미 cache:"no-store" + Date.now() 버스터라(app.js 파일 상단 load()
// 정의 참조) 별도 옵션을 얹지 않아도 강제 재조회가 된다.
async function onAmendSubmit(ev) {
  ev.preventDefault();
  const target = amendTarget;
  if (!target) return;   // 방어적 — submit 리스너가 amendTarget 있을 때만 이걸 부른다

  const patch = buildAmendPatch();
  if (!patch) return;   // 이미 alert 로 이유를 알렸다

  // 팝업 차단 대응 — onSubmit(매입/매도)은 "핸들러 안에서 await 없이
  // 동기 호출"로 사용자 제스처를 지켜 팝업 차단을 피한다. 여기서는 그
  // 트릭을 못 쓴다 — 아래 재조회(await load) 자체가 이 화면의 핵심
  // 방어라 없앨 수 없다(점 1). 대신 제스처가 아직 살아있는 지금 빈 탭을
  // 먼저 열어두고, writeRecord() 에 그대로 넘긴다 — Worker 로 끝나면
  // writeRecord 가 이 탭을 닫고, 깃허브 폴백이 필요하면 이 탭을 그
  // URL로 돌린다(그 탭을 새로 여는 대신). noopener 를 여기서 못 쓰는
  // 이유는 그대로다 — 쓰면 반환값이 null 이 되어 나중에 이 탭을 다시
  // 찾을 방법이 없다. 목적지가 사용자 입력이 아니라 이 코드가 고정한
  // github.com 이슈 생성 URL 이라 opener 노출 위험은 낮다고 본다.
  const pending = window.open("", "_blank");
  let handedOff = false;   // writeRecord() 에 pending 을 넘겼는지 — 넘겼으면 그 탭의 운명은 거기서 정해진다

  try {
    // allow404 를 안 쓴다(리뷰 I4) — main() 의 최초 로드와 달리 여기서는
    // 이 기록이 방금 전까지 있었다는 걸 이미 안다. allow404 를 쓰면
    // positions.json 자체가 404(브랜치·경로가 깨졌다 등)여도 fallback
    // 인 {positions:[]} 이 "정상 응답, 그냥 빈 목록"으로 둔갑해 아래
    // find 가 실패하고, 사용자는 "다른 곳에서 이미 고쳐졌거나 삭제된 것
    // 같습니다"라는 엉뚱한 안내를 받는다 — 실제로는 파일을 통째로
    // 못 받아온 것이다. allow404 없이 두면 404 는 load() 안에서 그냥
    // HTTP 오류로 처리되어 아래 !fresh.ok 분기(네트워크 문제 안내)로
    // 정확히 떨어진다.
    const fresh = await load("positions.json", { positions: [] });
    if (!fresh.ok) {
      alert("최신 기록을 다시 불러오지 못했습니다 — 네트워크를 확인하고 다시 시도해주세요.");
      return;
    }
    // 리뷰 I3 — positions 가 배열이 아닌 손상 파일({"positions":"..."}
    // 등)이면 아래 .find 가 TypeError 로 죽는다. amend 가 고치려는 바로
    // 그 손상 유형이므로 조용히 스크립트 오류로 남기지 않고 사람이 읽을
    // 메시지를 낸다 — 그리고 이 함수를 통째로 try 로 감싸서(아래) 여기서
    // 던지든 다른 데서 던지든 catch 가 pending 탭을 정리한다.
    const list = Array.isArray(fresh.data.positions) ? fresh.data.positions : null;
    if (!list) {
      alert("positions.json 형식이 예상과 다릅니다 — 자동으로 고칠 수 없습니다. "
        + "새로고침 후 다시 확인해주세요.");
      return;
    }
    const freshMatch = list.find(p => p.id === target.id);
    if (!freshMatch || !isReadablePosition(freshMatch)) {
      // 점 4 — 재조회한 파일에 더 이상 이 기록이 없다(다른 기기에서 이미
      // 고쳤거나, id 가 바뀌었거나). 낡은 was/was_price 로 이슈를 열면
      // 엉뚱한 기록을 겨눌 수 있으니 여기서 멈춘다 — 새로고침을 안내한다.
      alert("이 기록을 더 이상 찾을 수 없습니다 — 다른 곳에서 이미 고쳐졌거나 삭제된 것 같습니다. "
        + "새로고침 후 다시 확인해주세요.");
      return;
    }
    patch.was = freshMatch.code;
    patch.was_price = freshMatch.buys[0].price;

    const displayName = patch.name || freshMatch.name || freshMatch.code;
    const title = "AMEND " + displayName;

    // 여기부터는 pending 탭의 운명(닫힘/깃허브로 리다이렉트/그대로 둠)을
    // writeRecord() 가 정한다 — 아래 finally 는 더 이상 이 탭을 건드리지
    // 않는다(handedOff = true).
    handedOff = true;
    const result = await writeRecord(patch, title, displayName, pending);

    // 점 7 — Worker 로 성공했든 깃허브 폴백으로 넘어갔든, 사용자가 보는
    // 표는 둘 다 아직 이전 값이다(반영은 intake.yml 이 나중에 한다).
    // writeRecord() 가 이미 그 안내(#stale 배지 또는 #result 폴백 문구)를
    // 남겼으므로 여기서 다시 남기지 않는다.
    //
    // 리뷰 부가 개선 1 — 성공(또는 폴백으로라도 제출)했는데 amend 모드가
    // 그대로 남아 있으면, 폼도 그대로 남은 채 사용자가 실수로 다시
    // 제출을 누르면 똑같은 이슈가 한 번 더 열린다(apply_amend 가 두
    // 번째는 AlreadyApplied(rc=4)로 막긴 하지만, 열릴 필요 없는 이슈고
    // 안내 배지도 중복으로 쌓인다). result.ok(성공 또는 폴백 제출 완료)
    // 일 때만 나간다 — "blocked"(예: 패스프레이즈 불일치)면 사용자가
    // 아직 아무것도 못 냈으므로 폼을 그대로 둬 다시 시도하거나 #result
    // 의 수동 링크를 쓸 수 있게 한다.
    if (result.ok) exitAmendMode();
  } catch (e) {
    // 리뷰 I3 — 위 어디서 던지든(예상 못 한 형태의 JSON 등) 여기로 모여
    // pending 탭을 정리하고 사람이 읽을 오류를 알린다. reportFatal 은
    // 이미 있는 오류 경계(#stale 배지)를 그대로 재사용한다.
    reportFatal(e);
  } finally {
    if (pending && !handedOff) pending.close();
  }
}

function issueUrl(title, payload) {
  const body = "모의고사 입력\n\n```json\n" + JSON.stringify(payload) + "\n```";
  return REPO + "/issues/new?title=" + encodeURIComponent(title)
              + "&body=" + encodeURIComponent(body);
}

// ── Worker 쓰기 프록시 ───────────────────────────────────────────────────
//
// tryWorker() 는 절대 throw 하지 않는다 — 실패의 종류를 reason 문자열로
// 돌려주고, 그걸 어떻게 다룰지(자동 폴백 vs 막고 수동 탈출구만)는 호출자
// (writeRecord)가 결정한다. 종류를 구분하는 이유:
//
//   "not-configured"/"network" → **자동으로** 깃허브 폴백을 쓴다. Worker가
//     아직 배포 전이거나(자리표시자), 배포됐어도 지금 못 닿는(Cloudflare
//     장애, CSP 자리표시자 미교체, 오프라인 등) 상태는 "이 요청이 틀렸다"와
//     무관한 가용성 문제라, 예전(Task 13)처럼 그냥 깃허브로 진행해도 안전
//     하다 — 어차피 그 경로도 페이지 커튼을 통과했고 깃허브 로그인은
//     소유자만 되므로 인증이 약해지는 게 아니다.
//   "auth" → 패스프레이즈가 Worker 의 GATE_PASS 와 다르다. **자동으로
//     넘기지 않는다.** 이 페이지는 커튼을 통과한 그 문구를 그대로 보내므로,
//     여기서 틀렸다는 건 배포 설정(GATE_PASS 와 GATE_PBKDF2_HEX 가 서로
//     다른 문구에서 나왔음)이 어긋났다는 신호다 — 조용히 폴백으로
//     넘어가면 그 어긋남을 사용자가 영영 모르고 지나칠 수 있다. 막되,
//     수동으로 고를 수 있는 폴백 링크는 renderResult 가 보여준다(완전한
//     막다른 길은 아니다).
//   "http"/"bad-response" → Worker 는 응답했지만 뭔가 실패했다(깃허브 API
//     오류, 예상과 다른 응답 모양 등). 이것도 자동 폴백하지 않는다 — 예를
//     들어 깃허브 쪽 레이트리밋 같은 원인은 폴백(깃허브 이슈를 직접 여는
//     것)도 똑같이 막힐 수 있어, 사용자가 이유를 보고 판단하게 한다.
async function tryWorker(payload, display) {
  if (!isWorkerConfigured()) return { ok: false, reason: "not-configured" };
  const passphrase = getStoredPassphrase();
  if (!passphrase) return { ok: false, reason: "not-configured" };   // 커튼 이론상 항상 있어야 하지만 방어적으로

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);   // 무한 대기 방지 — 10초면 정상 응답엔 충분하고도 남는다
  let resp;
  try {
    resp = await fetch(WORKER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pass: passphrase, payload, display }),
      signal: controller.signal,
    });
  } catch (e) {
    // 2026-08-20 보안 리뷰 C1 — AbortError(타임아웃)를 "network"에 같이
    // 묶었던 게 원인이었다. "network"는 자동으로 깃허브 폴백을 쓰는데,
    // 타임아웃은 "요청이 안 갔다"가 아니라 **결과를 모른다**는 뜻이다 —
    // Worker 가 GitHub 이슈 생성까지 이미 마쳤는데 응답만 못 받았을 수
    // 있다. 이 상태에서 자동으로 깃허브 이슈를 또 열면 **같은 제출이
    // 두 번** 나갈 수 있다. sell 은 payload 에 대상 id 가 없어(onSubmit
    // 참조) apply_sell 이 매번 "이 코드의 open 중 가장 오래된 것"을 새로
    // 찾으므로, 보유가 2건 이상이면 두 번째 제출이 **거부되지 않고 다른
    // 보유를 조용히 닫는다**(tests/test_models.py
    // test_매도_요청이_중복되면_서로_다른_보유를_조용히_닫는다 로 고정 —
    // 원인은 여기, 고정은 거기). 그래서 타임아웃은 "network"와 분리해
    // 자동 폴백 목록에서 뺀다(writeRecord) — 모를 땐 자동으로 아무 것도
    // 더 하지 않는다.
    if (e && e.name === "AbortError") return { ok: false, reason: "timeout" };
    // 그 외 TypeError 는 DNS 실패·CORS 차단·CSP 차단(자리표시자 미교체
    // 포함)·오프라인처럼 요청이 애초에 나가지도 못한 경우다 — 이건 결과가
    // 모호하지 않다(안 갔다), 그래서 계속 "network"로 묶어 자동 폴백을
    // 쓴다.
    return { ok: false, reason: "network" };
  } finally {
    clearTimeout(timer);
  }

  if (resp.status === 401) return { ok: false, reason: "auth" };
  if (!resp.ok) {
    // 2026-08-20 보안 리뷰 I3 — Worker 가 사람이 읽을 진단(예: "Bad
    // credentials", "시크릿이 설정되지 않았습니다")을 이미 응답 본문에
    // 담아 보내는데, 그동안 상태코드만 보고 버렸다. PAT 만료처럼 사용자가
    // 결국 실제로 마주칠 실패에서 "HTTP 502" 한 줄만 보여주면 무엇을
    // 고쳐야 할지 알 길이 없다 — 본문을 최선껏 읽어 같이 넘긴다(못 읽어도
    // 상태코드 기반 메시지로는 그대로 대체된다).
    const data = await resp.json().catch(() => null);
    const detail = data && typeof data.error === "string" ? data.error : undefined;
    return { ok: false, reason: "http", status: resp.status, detail };
  }

  let data;
  try {
    data = await resp.json();
  } catch (e) {
    return { ok: false, reason: "bad-response" };
  }
  if (!data || typeof data.number !== "number" || typeof data.url !== "string") {
    return { ok: false, reason: "bad-response" };
  }
  return { ok: true, number: data.number, url: data.url };
}

// 2026-08-20 보안 리뷰 I5 — GATE_PBKDF2_HEX/GATE_PASS 어긋남을 실제 쓰기
// 전에 알아채기 위한 최선노력 진단. payload 없이 pass 만 보내면 Worker 는
// (worker.js) pass 부터 확인하므로: 맞으면 그 다음 검사(payload 모양)에서
// 걸려 400, 틀리면 401 — 이 둘의 차이만으로 인증 문제인지 아닌지 구분할
// 수 있다(둘 다 "실패"지만 이유가 다르다). Worker 코드 변경도 새 엔드포인트도
// 필요 없다.
//
// 실패해도(네트워크 등) 조용히 넘어간다 — 이건 실제 제출을 막는 검사가
// 아니라 조기 경보일 뿐이라, 여기서 뭐라 알리면 tryWorker() 가 실제 제출
// 시점에 내는 진단과 중복되거나 어긋난 타이밍에 두 번 놀라게 한다.
async function probeWorkerAuth() {
  if (!isWorkerConfigured()) return;
  const passphrase = getStoredPassphrase();
  if (!passphrase) return;
  try {
    const resp = await fetch(WORKER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pass: passphrase }),   // payload 를 일부러 안 보낸다 — 위 설명 참조
    });
    if (resp.status === 401) {
      addStaleMessage("Worker 인증 확인: 저장된 통과 문구가 Worker 의 GATE_PASS 설정과 다른 것 같습니다 — "
        + "실제로 저장을 시도하기 전에 worker/README.md 3단계를 다시 확인해주세요.");
    }
  } catch (e) {
    // 네트워크 실패·CSP 차단·미배포 등은 이 진단의 몫이 아니다 — 실제
    // 제출 시 tryWorker() 가 다시 다루므로 여기서는 조용히 넘어간다.
  }
}

// #result 를 채운다 — textContent 전용(성공 시 링크 <a> 하나만 createElement
// 로 별도 조립, href/textContent 둘 다 신뢰할 수 없는 문자열을 안전한
// 방식으로만 채운다). 매 호출마다 완전히 새로 그린다(renderTable 과 같은
// 패턴) — 이전 결과가 남아 있다가 새 제출 결과와 섞여 보이면 안 된다.
function renderResult(info) {
  const el = document.getElementById("result");
  el.textContent = "";
  el.className = "result " + info.kind;   // style.css: .result.success/.fallback/.blocked
  el.hidden = false;

  const REASON_MSG = {
    "not-configured": "Worker 가 아직 설정되지 않았습니다",
    network: "Worker 에 연결하지 못했습니다",
    // 타임아웃은 "실패"가 아니라 "모름"이다(tryWorker 옆 C1 주석 참조) —
    // 그래서 문구도 "실패했습니다"가 아니라 "이미 저장됐을 수 있다"는
    // 가능성을 먼저 알린다. 아래 blocked 분기의 공통 접미사("아직
    // 반영되지 않았습니다")를 이 reason 에는 안 붙인다(별도 처리, 아래).
    timeout: "응답이 늦습니다 — 이미 저장됐을 수 있습니다. 깃허브 이슈 목록을 먼저 확인해주세요",
    auth: "패스프레이즈가 Worker 설정과 일치하지 않습니다 — 배포 시 넣은 GATE_PASS 를 확인해주세요",
    http: "Worker 가 요청을 거부했습니다" + (info.status ? " (HTTP " + info.status + ")" : "")
      + (info.detail ? ": " + info.detail : ""),
    "bad-response": "Worker 응답을 이해할 수 없습니다",
  };

  if (info.kind === "success") {
    const p = document.createElement("p");
    p.textContent = "저장 요청을 보냈습니다 — 이슈 #" + info.number + ".";
    el.appendChild(p);
    const a = document.createElement("a");
    a.href = info.url;                  // Worker/깃허브 API 가 돌려준 값 — 사용자 입력이 아니다
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = "이슈 보기";
    el.appendChild(a);
  } else if (info.kind === "fallback") {
    const p = document.createElement("p");
    p.textContent = (REASON_MSG[info.reason] || "저장에 실패했습니다")
      + " — 대신 깃허브 이슈 화면을 새 탭으로 열었습니다. 그 탭에서 Submit 을 눌러야 반영됩니다.";
    el.appendChild(p);
  } else {   // "blocked" — 자동으로 넘기지 않고 수동 탈출구만 준다
    const p = document.createElement("p");
    // "아직 반영되지 않았습니다"는 auth/http/bad-response 에서는 사실이다
    // (Worker 가 응답할 때까지 아무 것도 안 만들어졌거나, 거부했다). 하지만
    // timeout 은 결과를 모르는 상태라 이 문구를 덧붙이면 방금 위에서 말한
    // "이미 저장됐을 수 있다"와 스스로 모순된다 — timeout 은 REASON_MSG
    // 자체가 이미 필요한 안내를 다 담고 있으므로 접미사를 안 붙인다.
    p.textContent = REASON_MSG[info.reason] || "저장에 실패했습니다";
    if (info.reason !== "timeout") p.textContent += " — 아직 반영되지 않았습니다.";
    el.appendChild(p);
    const a = document.createElement("a");
    a.href = issueUrl(info.title, info.payload);
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    // timeout 에서는 "그래도"라는 말이 안 맞는다(이미 성공했을 수도 있는
    // 상황에서 "그래도 열기"는 재촉하는 느낌을 준다) — 확인을 먼저
    // 권하는 문구로 바꾼다. 링크 자체는 그대로 둔다(정말 필요하면 여전히
    // 쓸 수 있어야 한다 — 예: 확인해보니 정말 안 갔을 때).
    a.textContent = info.reason === "timeout"
      ? "확인 후에도 안 갔다면 깃허브에서 직접 열기"
      : "그래도 깃허브에서 직접 열기";
    el.appendChild(a);
  }
}

// buy/sell(onSubmit)과 amend(onAmendSubmit) 제출 경로가 공유하는 마지막
// 단계 — Worker 를 먼저 시도하고, 그 결과에 따라 자동 폴백/수동 탈출구/
// 성공 표시 중 하나로 마무리한다.
//
// `pending` (선택) — amend 는 이 함수를 부르기 **전에** 이미 재조회
// (positions.json no-store)를 기다려야 해서, 그 재조회가 시작되기 전에
// 자신이 직접 빈 탭을 열어 사용자 제스처를 붙잡아 둔다(팝업 차단 대응,
// onAmendSubmit 옆 주석 참조) — 그 탭을 그대로 넘겨받아 재사용한다. buy/
// sell 은 이 함수를 제출 핸들러에서 await 없이 곧장 부르므로(핸들러 진입
// 시점에 아직 제스처가 살아있다) 이 함수 자신의 맨 앞(첫 await 이전)에서
// 새로 연다 — 여기서 여는 것도 fetch() 호출보다 먼저이기만 하면 같은
// 이유로 안전하다.
async function writeRecord(payload, title, display, pending) {
  if (pending === undefined) pending = window.open("", "_blank");
  let tabUsed = false;
  try {
    const outcome = await tryWorker(payload, display);
    if (outcome.ok) {
      if (pending) pending.close();
      renderResult({ kind: "success", number: outcome.number, url: outcome.url });
      addStaleMessage("방금 Worker로 저장을 요청했습니다(이슈 #" + outcome.number + ") — 워크플로가 "
        + "반영할 때까지 몇 분 걸릴 수 있습니다. 이 표는 아직 이전 값을 보여주고 있으니, 나중에 "
        + "새로고침해서 확인해주세요.");
      return { ok: true };
    }
    if (outcome.reason === "not-configured" || outcome.reason === "network") {
      const url = issueUrl(title, payload);
      if (pending) {
        pending.location.href = url;
        tabUsed = true;
      } else {
        const win = window.open(url, "_blank", "noopener");
        tabUsed = true;
        if (!win) location.href = url;
      }
      renderResult({ kind: "fallback", reason: outcome.reason });
      return { ok: true, fallback: true };
    }
    // "timeout"/"auth"/"http"/"bad-response" — 자동으로 넘기지 않는다
    // (tryWorker 옆 C1 주석 참조). pending 탭은 안 썼으니 finally 에서 닫는다.
    renderResult({
      kind: "blocked", reason: outcome.reason, status: outcome.status,
      detail: outcome.detail, title, payload,
    });
    return { ok: false };
  } finally {
    if (pending && !tabUsed) pending.close();
  }
}

// Worker 연동(이 작업) 전에는 이 함수가 완전히 동기였다 — issueUrl() 을
// 만들어 window.open() 한 줄로 끝났다. writeRecord() 가 await 하는
// tryWorker() 를 거치므로 이제 async 다. 그래도 팝업 차단 대응은 예전과
// 같은 요령을 그대로 쓴다 — 이 핸들러가 아직 동기로 실행되는 지금(제출
// 이벤트 직후, 첫 await 이전) writeRecord() 를 부르면, writeRecord() 내부의
// `window.open("", "_blank")` 도 같은 동기 구간 안에서 실행돼(async 함수는
// 첫 await 을 만나기 전까지 호출자와 같은 태스크에서 그대로 실행된다)
// 사용자 제스처가 아직 살아있다 — confirm() 이 끼어들어도 마찬가지다(같은
// 이유로 이전 코드가 이미 의존하던 성질).
async function onSubmit(ev) {
  ev.preventDefault();
  const text = document.getElementById("q").value;
  const code = resolveCode(text);
  if (!code) {
    return alert(masterLoadFailed
      ? "종목 목록을 불러오지 못해 코드를 확인할 수 없습니다. 새로고침 후 다시 시도해주세요."
      : "종목을 목록에서 골라주세요.");
  }
  const date = document.getElementById("date").value;
  if (!date) return alert("매입일을 골라주세요.");

  // Task 13(지정가 관찰) — 지금 렌더된 모드가 곧 폼의 진실이다(applyMode
  // 가 매번 #form.dataset.mode 를 같이 써 두므로, updateMode() 의 판정과
  // 어긋날 일이 없다). 관찰 모드에서는 #price 가 숨어 있어(값이 남아있을
  // 수도, 비어있을 수도 있다) 매입가 검증 대상이 아니다 — #watch-price 를
  // 대신 읽는다.
  const watching = document.getElementById("form").dataset.mode === "watch";
  const price = parsePrice(document.getElementById(watching ? "watch-price" : "price").value);
  if (!(price > 0)) return alert(watching ? "지정가를 확인해주세요." : "매입가를 확인해주세요.");

  // 오타 방지: 참고가(referencePrice — quotes 우선, 없으면 master.json
  // 현재가로 폴백, 항목 18) 대비 ±30% 를 벗어나면 되묻는다. 참고가가
  // 아예 없으면(null) 조용히 넘어간다 — referencePrice 옆 주석 참조.
  // 지정가 관찰도 결국 이 가격에 자동으로 1차 매수가 걸리므로, 매입가
  // 오타와 똑같은 무게로 다룬다 — 여기서만 봐주면 오타 하나가 그대로
  // 대기 주문에 실려 나중에(며칠 뒤일 수도 있다) 조용히 체결된다.
  const ref = referencePrice(code);
  if (ref !== null && Math.abs(pct(ref, price)) > 30) {
    if (!confirm("최근 종가 " + fmt(ref) + "원과 " + Math.round(Math.abs(pct(ref, price)))
                 + "% 차이입니다. 그대로 진행할까요?")) return;
  }

  const name = NAMES.get(code) || code;

  if (watching) {
    const payload = { op: "watch", code, name, price, date,
      source: document.getElementById("source").value,
      memo: document.getElementById("memo").value };
    await writeRecord(payload, "WATCH " + name, name);
    return;
  }

  const open = findOpenPosition(code);
  const payload = open
    ? { op: "sell", code, price, date, reason: document.getElementById("memo").value }
    : { op: "buy", code, name, price, date,
        source: document.getElementById("source").value,
        memo: document.getElementById("memo").value };
  const title = (open ? "SELL " : "BUY ") + name;

  await writeRecord(payload, title, name);
}

document.getElementById("q").addEventListener("input", e => {
  fillCandidates(e.target.value);
  // amend 모드 중에는 #q 를 바꿔도 매입/매도 자동판정으로 돌아가지 않는다
  // (Task 15 — amend 는 버튼으로만 들어오고 #cancel-btn 으로만 나간다).
  if (!amendTarget) updateMode();
});
// Task 13(지정가 관찰) — #q 입력 리스너와 같은 가드를 쓴다. amend 도중에
// 이 셀렉트를 만지는 경우는 흔치 않지만, 만약 만지더라도 amend 화면이
// 매입/관찰 모드로 갑자기 바뀌면 안 된다(같은 이유, 위 리뷰 C2).
document.getElementById("entry-mode").addEventListener("change", () => {
  if (!amendTarget) updateMode();
});
document.getElementById("form").addEventListener("submit", ev => {
  if (amendTarget) { onAmendSubmit(ev); return; }
  onSubmit(ev);
});
document.getElementById("cancel-btn").addEventListener("click", exitAmendMode);
document.getElementById("open").addEventListener("click", onAmendButtonClick);
document.getElementById("closed").addEventListener("click", onAmendButtonClick);
// 자동/수동 토글 버튼은 #open(보유 중 — open/pending 이 여기 그려진다)에만
// 나온다(nameCell 이 r.closed 인 행에는 아예 안 그린다) — 그래도 #closed
// 에 걸어도 해가 되진 않지만, 실제로 쓰이지 않을 리스너를 다는 대신
// 렌더가 실제로 그 버튼을 두는 표 하나에만 건다.
document.getElementById("open").addEventListener("click", onAutoToggleButtonClick);

// main() 은 더 이상 이 자리에서 즉시 실행되지 않는다 — 통과 커튼(맨 아래
// 절)이 통과된 뒤에만(이미 통과해 있었으면 로드 즉시, 아니면 #gate-form
// 제출 성공 시) 호출한다. positions.json/quotes.json/master.json 요청이
// 전부 이 함수 안에서만 일어나므로, 이렇게 미루는 것 자체가 "커튼을
// 통과하기 전엔 데이터를 받지 않는다"는 요구를 만족시키는 전부다 — 커튼이
// 뭔가를 막아서가 아니라(URL 은 여전히 공개다), 통과 전에 데이터를 받는
// 게 애초에 이 화면에서 할 일이 없어서다.
async function main() {
  // KST 기준 "오늘" 문자열 — master.json 캐시버스터(하루 한 번만 바뀌면
  // 됨)와 매입일 기본값(아래) 둘 다에 쓴다. 기기 로캘에 기대지 않고
  // UTC+9 를 명시적으로 더한다 — 파이썬 쪽 KST = timezone(timedelta(hours=9))
  // 와 같은 근거. Date.now()+9시간은 항상 파싱 가능한 10자리 문자열을
  // 내므로 이 값 자체가 비어있을 일은 없다. (Task 15: exitAmendMode() 도
  // 같은 계산을 써야 해서 kstTodayStr() 로 뽑아냈다 — 아래는 그 호출.)
  const kstToday = kstTodayStr();

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
  NAMES = new Map(MASTER);                  // [code,name,price] 라도 앞 2개만 쓴다(Map 생성자 규칙)
  // 코드 → 가격. 항목이 예전 [code,name] 2요소짜리로 캐시돼 있어도(배포
  // 직후 브라우저 HTTP 캐시가 어제 날짜 버스터로 아직 옛 파일을 들고
  // 있는 과도기) t[2] 가 undefined 라 null 로 정규화한다 — 가드가
  // "가격을 모른다"로 안전하게 해석하게(항목 18).
  MASTER_PRICES = new Map(MASTER.map(t => [t[0], t[2] === undefined ? null : t[2]]));
  masterLoadFailed = !msRes.ok;
  if (masterLoadFailed) {
    // 실패해도 화면 어디에도 안 보이던 유일한 실패 지점이었다 — 표는
    // 그려지고 배지도 안 뜨고 자동완성은 그냥 조용히 빈 채로 남아,
    // 사용자가 폼을 다 채우고 제출을 눌러야 비로소(alert 로) 알게 됐다.
    addStaleMessage("종목 목록(master.json)을 불러오지 못했습니다 — 자동완성·매도 "
      + "판정·신규 매수 오타 확인이 동작하지 않습니다. 새로고침해주세요.");
  }
  // 표가 그려지는 동안 사용자가 이미 입력을 시작했을 수 있으니, 마스터가
  // 늦게 도착하면 지금 값 기준으로 자동완성·모드를 한 번 더 채운다.
  //
  // 리뷰 C2 — 이 await(master.json, 207KB) 동안 표는 이미 그려져 있고
  // "고치기" 버튼도 눌릴 수 있다. 여기서 amendTarget 가드 없이
  // updateMode() 를 부르면, 마침 amend 중인 기록이 "보유 중" 종목이라서
  // (amend 로 여는 기록은 정의상 그럴 때가 흔하다) findOpenPosition 이
  // 걸려 매도 모드로 화면이 덮어써진다 — amendTarget 은 그대로라 실제
  // 제출은 여전히 amend patch 로 나가는데, 화면은 "매도가" 라벨을
  // 보여줘서 사용자가 매도가로 입력한 값이 매입가로 들어간다(실측). 이제
  // updateMode() 자신도 이 가드를 갖고 있지만(벨트+서스펜더), 호출부에도
  // 남겨 이 조건이 한눈에 보이게 한다.
  fillCandidates(document.getElementById("q").value);
  if (!amendTarget) updateMode();
}

// ══════════════════════════════════════════════════════════════════════
// 통과 커튼 (passphrase curtain) — 이건 잠금이 아니다, 그리고 이제 겸직이다
// ══════════════════════════════════════════════════════════════════════
//
// positions.json 은 인증 없이 누구나 받을 수 있다(실측 2026-08-20):
//   https://raw.githubusercontent.com/AMID815/mouigosa/data/positions.json
//   → HTTP 200, 인증 없음, 381바이트, 삼성전자/2026-08-19/247,500원/... 그대로.
// GitHub Pages 를 진짜 비공개로 만들려면 Enterprise Cloud + 조직 계정이
// 필요한데 여기엔 없다(설계 §9 와 같은 종류의 제약). 그래서 이 아래 코드가
// 막는 건 "URL 을 아는 사람"이 아니라 "지나가다 이 페이지를 그냥 열어본
// 사람" 뿐이다 — 사용자가 그 구분을 알고 이 형태를 골랐다
// ("지나가는 사람만 막으면 될것같아"). 이 사실을 화면 문구에는 안 낸다
// (내면 커튼의 대상에게 우회로를 알려주는 꼴이다) — 여기, 코드 주석에는
// 낸다. 이 파일을 읽는 미래의 누군가(자신 포함)가 이걸 진짜 접근 통제로
// 착각해 그 위에 뭔가를 쌓으면 안 되기 때문이다.
//
// **Worker 연동(이 작업) 전에는** 여기 거는 것도 "토큰"이 아니라 "통과
// 했다는 사실 하나"(불리언)뿐이었다. 이제는 다르다 — 같은 문구가 Worker
// 쓰기 요청의 인증에도 쓰이므로, 평문 문구 자체를 들고 있어야 한다(아래
// getStoredPassphrase 옆 주석). 이 절 전체가 그 변화를 어떻게 감당했는지
// 설명한다.
//
// ── 왜 SHA-256 한 번이 아니라 PBKDF2인가 ─────────────────────────────
// GATE_PBKDF2_HEX 는 페이지 소스에 그대로 공개된다(누구나 뷰소스로 본다).
// 이 값이 "통과 여부만 가르는 커튼용 해시"였을 때는 오프라인 대입 공격의
// 결과물이 기껏해야 "커튼을 넘길 수 있다"였다 — 그런데 §9 가 브라우저에
// 토큰을 안 두는 이유와 정확히 같은 논리로, 이제 이 문구는 **쓰기 자격
// 증명**이기도 하다. 바른 SHA-256 은 범용 GPU 로 초당 수십억 회를 돌릴 수
// 있어(해시 하나 계산이 마이크로초 단위), 평범한 길이의 문구는 오프라인
// 사전 대입에 사실상 무방비다. PBKDF2-HMAC-SHA256 을 반복 600,000 회로
// 걸면 계산 하나에 들이는 비용이 SHA-256 한 번의 60만 배가 되어, 같은
// 사전 대입에 필요한 총 시간이 그만큼 늘어난다 — 페이지 소스가 통째로
// 공개인 이상 "못 뚫는다"가 아니라 "뚫는 데 훨씬 오래 걸린다"는 뜻이다
// (OWASP 2023 PBKDF2-HMAC-SHA256 권장 반복수와 같은 자리 — 서버 인증
// 시스템 기준이지만 여기서도 같은 하한을 그대로 따른다). 소금(salt,
// 아래 GATE_PBKDF2_SALT)은 여기서 비밀이 아니다 — 이것도 페이지 소스에
// 있다. 소금의 역할은 "이 사이트 전용으로 미리 계산해둔 표(레인보우
// 테이블)를 못 재사용하게" 하는 것뿐, 이 페이지를 노리고 새로 도는
// 공격의 반복당 비용은 못 낮춘다 — 진짜 방어선은 반복수와 사용자가 고른
// 문구의 길이/무작위성이다.
//
// 반복수 600,000 을 고른 근거(실측, 이 저장소 개발 PC, 데스크톱급
// WebCrypto): 100,000회 25.5ms, 300,000회 75.5ms, 600,000회 159.9ms,
// 1,000,000회 267.3ms — 반복수에 선형으로 비례한다. WebCrypto의 PBKDF2
// 는 브라우저 네이티브 구현이라(JS 루프가 아니다) 휴대폰에서도 자릿수가
// 크게 달라지진 않는다고 보고, 저사양 휴대폰이 데스크톱보다 5~10배
// 느리다고 넉넉히 잡아도 600,000회는 1~1.5초 안팎으로 예상한다 — 매일
// 여는 화면에서 한 번(로그인 유지되는 한 다시 안 묻는다, 아래
// getStoredPassphrase) 감수할 수 있는 지연이라고 판단했다. 실제 휴대폰
// 실측치는 아니다 — 배포 후 너무 느리면 이 상수 하나만 낮추면 된다(다만
// 낮추면 위 대입 공격 여유 시간이 그만큼 줄어든다는 트레이드오프가
// 그대로 따라온다).
//
// ── 유출 시 무슨 일이 생기나 (localStorage 겸용 저장의 트레이드오프) ──
// §9 가 브라우저에 깃허브 토큰을 두지 않는 이유 — localStorage 는 경로가
// 아니라 오리진 단위라 amid815.github.io 아래 mouigosa·황룡·눌림베팅·
// 종가베팅·테마탐색구조대·오디세이가 같은 버킷을 쓴다 — 가 여기도 똑같이
// 적용된다. 다른 점은 유출됐을 때의 결과다:
//   - §9 가 막은 것(Contents:write 토큰)이 새면: main 브랜치의 app.js 를
//     통째로 갈아치울 수 있다 → Pages 재배포 → 그 오리진 전체(다른 네
//     대시보드 포함)에 임의 스크립트를 심을 수 있다. 토큰을 지워도
//     이미 커밋된 코드는 계속 서빙된다 — 사실상 영구적이고 전면적인
//     피해다.
//   - 이 값(패스프레이즈 평문)이 새면: 할 수 있는 일은 Worker 에 POST
//     해서 **이슈를 여는 것뿐**이다(GH_TOKEN 은 Worker 안에만 있고
//     Issues 권한만 있다, worker/worker.js 상단 주석). 이슈가 반영되면
//     positions.json 에 가짜 매수/매도/고치기 기록이 하나 늘거나
//     바뀐다 — 성가시지만 "고치기"(amend)로 되돌릴 수 있고, 최악의
//     경우도 이슈 이력과 git 커밋 이력(§4 "이슈가 남기는 것" — 처리된
//     이슈는 닫히되 지우지 않는다)에 그대로 남아 무엇이 언제 바뀌었는지
//     추적할 수 있다. 코드를 한 글자도 못 건드리고, 다른 대시보드에는
//     전혀 닿지 않는다.
// 이 비대칭(코드 장악 대 기록 오염, 후자는 감사로그가 있어 복구 가능)이
// "여기 평문을 저장해도 되는가"에 대한 답이다 — 안전해서가 아니라,
// §9 가 절대 안 된다고 한 피해와 종류가 다르고 훨씬 작기 때문이다.
//
// ── 어디에 저장하나 ──────────────────────────────────────────────────
// localStorage 를 골랐다(sessionStorage 나 메모리 변수가 아니라). 이
// 페이지는 "매일 휴대폰에서 열어보는" 것이 전제(요구사항, 기존 커튼
// 설계도 같은 이유로 불리언을 영구 저장했다) — sessionStorage 는 탭을
// 닫으면(모바일에서는 앱을 완전히 종료하면) 사라져 사실상 방문마다 다시
// 문구를 치게 되고, 그건 이 화면을 안 쓰게 만드는 마찰이다(위 §7 요구와
// 정면으로 부딪힌다). 메모리 변수는 새로고침마다 사라져 더 나쁘다.
// localStorage 의 대가는 위에서 이미 재본 유출 위험뿐이고, 그 위험은
// 감수할 만하다고 판단했다.

// 사용자가 고른 문구를 여기서 직접 볼 일이 없다 — PBKDF2 파생값(해시)만
// 붙여넣는다. 아래는 자리표시자다. 실제 값은 아래 명령으로 로컬에서
// 계산해 붙여넣을 것(이 작업의 보고서에도 같은 명령을 남겼다):
//
//   python -c "import hashlib, unicodedata, getpass; \
//   p = unicodedata.normalize('NFC', getpass.getpass('passphrase: ').strip()); \
//   salt = b'mouigosa-gate-salt-v1'; \
//   dk = hashlib.pbkdf2_hmac('sha256', p.encode('utf-8'), salt, 600000, dklen=32); \
//   print(dk.hex())"
//
// trim → NFC 정규화 → UTF-8 인코딩 → PBKDF2-HMAC-SHA256(salt, 600000회,
// 32바이트) 순서가 아래 pbkdf2Hex()/normalizePassphrase() 와 정확히
// 같아야 한다 — 한글은 입력 경로(IME·붙여넣기 소스)에 따라 NFC/NFD 로
// 다르게 들어올 수 있어(자모 결합 여부), 정규화를 양쪽에서 맞추지 않으면
// 눈에는 같은 문구인데 해시가 달라진다. (실제로 Python hashlib.pbkdf2_hmac
// 과 WebCrypto SubtleCrypto.deriveBits({name:"PBKDF2",...}) 가 같은 값을
// 내는지 이 작업에서 교차 검증했다 — 같은 문구·소금·반복수로 두 쪽
// 모두 27c44761...449635 로 일치했다.)
const GATE_PBKDF2_HEX = "1ecc80828ee19c54a6cd9bb512ccf5cd64a2878ed3e7c9c5cd1b05518bf198af";

// 공개 상수 — 비밀이 아니다(위 "왜 PBKDF2인가" 참조). 문구를 바꾸지 않는
// 한 이 소금과 반복수는 그대로 둔다 — 바꾸면 같은 문구도 다른 해시가
// 나와 GATE_PBKDF2_HEX 를 다시 계산해야 한다.
const GATE_PBKDF2_SALT = new TextEncoder().encode("mouigosa-gate-salt-v1");
const GATE_PBKDF2_ITERATIONS = 600000;

// 오리진 공유 버킷에서 다른 대시보드 키와 안 겹치게 접두어를 둔다(위
// 설명 참조). "_v2" — 이 저장소는 아직 push 되지 않은 로컬 커밋
// (d2bc65d)에서 "_v1"로 불리언("1")만 저장했었다. 이 작업이 그 커밋을
// 아직 아무도 안 받은 상태에서 고쳐 저장 형태를 불리언에서 평문
// 패스프레이즈로 바꾸므로, 실사용 기기가 옛 "_v1" 형태를 들고 있을 일이
// 없다(배포된 적이 없다) — 그래도 의미 자체가 달라졌으니(불리언 →
// 자격증명) 버전을 올려 혹시 모를 혼선을 원천 차단한다.
const GATE_STORAGE_KEY = "mouigosa_gate_pass_v2";

function normalizePassphrase(raw) {
  // trim 먼저, NFC 정규화 나중 — 위 python 명령과 순서를 맞춘다(순서
  // 자체가 결과를 바꾸는 입력은 실무에서 없다고 보지만, 두 코드가 서로
  // 다른 순서를 따를 이유가 없다). Worker 로 보낼 때도 이 정규화를 거친
  // 값을 보낸다 — worker.js 도 같은 순서(trim→NFC)로 한 번 더 정규화해
  // 비교하므로 어느 한쪽만 정규화를 빼먹어도 안전하지만, 두 코드가 다른
  // 규칙을 따를 이유가 없다는 원칙은 여기도 같다.
  return raw.trim().normalize("NFC");
}

async function pbkdf2Hex(passphrase) {
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey(
    "raw", enc.encode(passphrase), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: GATE_PBKDF2_SALT, iterations: GATE_PBKDF2_ITERATIONS, hash: "SHA-256" },
    keyMaterial, 256);
  return Array.from(new Uint8Array(bits)).map(b => b.toString(16).padStart(2, "0")).join("");
}

// 저장된 패스프레이즈(평문) — 있으면 이 기기가 이미 커튼을 통과했다는
// 뜻이자, Worker POST 에 실어 보낼 값이다(writeRecord → tryWorker). 예전
// (Worker 연동 전) isGateOpen() 은 "1"이라는 불리언만 봤지만, 이제는
// "통과했는가"와 "쓰기 요청에 실을 값이 있는가"가 같은 질문이 됐다 —
// 그래서 반환값 자체를 재사용한다(따로 boolean getter 를 안 둔다 — 두
// 갈래로 나누면 언젠가 어긋난다: 예를 들어 플래그는 있는데 값이 지워진
// 상태가 생기면 커튼은 열려 있는데 Worker 요청마다 인증이 조용히
// 실패하는, 원인 찾기 어려운 상태가 된다).
function getStoredPassphrase() {
  try {
    return localStorage.getItem(GATE_STORAGE_KEY) || "";
  } catch (e) {
    // localStorage 자체가 막힌 드문 환경(일부 사생활 보호 모드, 저장소
    // 정책 등) — 매번 다시 묻는 정도로 낮춰 대응한다. 페이지가 아예 못
    // 뜨는 것보다 낫다.
    return "";
  }
}

function isGateOpen() {
  return getStoredPassphrase() !== "";
}

function setStoredPassphrase(passphrase) {
  try {
    localStorage.setItem(GATE_STORAGE_KEY, passphrase);
  } catch (e) {
    // 저장 실패(용량 초과 등)해도 이번 세션은 이미 통과했으니 계속
    // 진행한다 — 다음 방문에 다시 물어볼 뿐, 이번 방문이 막히면 안 된다.
    // (이번 세션 안에서는 handleGateSubmit 의 지역변수 passphrase 가
    // 아니라 이 함수를 다시 거쳐야만 Worker 요청이 인증되므로, 저장이
    // 실패한 세션에서 Worker 쓰기를 시도하면 매번 401 로 막힌다 — 그래도
    // "페이지가 아예 안 뜨는 것"보다는 낫다는 판단은 예전 코드와 같다.)
  }
}

// #content 를 열면서 #q/#price/#date 의 required 도 같이 켠다(index.html
// 위쪽 통과 커튼 주석 참조) — 정적으로 걸어두면 #content 가 숨어 있는
// 동안 tests/test_index_html.py 의 "숨겨진 required" 가드에 걸린다.
function revealContent() {
  document.getElementById("content").hidden = false;
  document.getElementById("q").required = true;
  document.getElementById("price").required = true;
  document.getElementById("date").required = true;
}

function unlockAndStart() {
  document.getElementById("gate").hidden = true;
  // 2026-08-20 보안 리뷰 minor — #gate 를 숨겨도 #gate-pass 의 required 는
  // 그대로 켜져 있었다(index.html 정적 마크업). 이 입력란 자체는 숨은 뒤
  // 프로그램적으로 다시 submit 되지 않으니 당장 아무 것도 막지는 않지만
  // (별도 폼, dispatchEvent 로 우회하는 코드도 없다), tests/test_index_html.py
  // 가 정적으로 막는 바로 그 모양(hidden 조상 아래 살아있는 required)을
  // 런타임에 만들어낸다 — 정적 가드가 못 보는 자리에서. 커튼을 나가는
  // 김에 같이 끈다.
  document.getElementById("gate-pass").required = false;
  revealContent();
  // main() 이 여기서만 불린다 — positions.json/quotes.json/master.json
  // 요청은 전부 main() 안에 있으므로, 커튼을 통과한 뒤에만 이 줄에
  // 닿는다는 사실 자체가 "통과 전엔 안 받는다"는 요구를 만족시킨다.
  main().catch(reportFatal);   // 항목 13, F1 과 같은 오류 경계
  // 2026-08-20 보안 리뷰 I5 — GATE_PBKDF2_HEX(페이지)와 GATE_PASS(Worker)는
  // 같은 문구에서 나와야 하지만 서로 다른 도구(커밋 vs wrangler secret)로
  // 따로 설정된다 — 둘이 어긋나도 이 시점엔 아무 신호가 없고, 사용자는
  // 첫 실제 쓰기 시도에서야(#result 의 "blocked"/auth) 알게 된다. main()
  // 을 막지 않는 최선노력 진단으로 그 지연을 줄인다 — await 하지 않는다.
  probeWorkerAuth();
}

let gateBusy = false;   // 해시 계산(await) 도중 중복 제출 방지

async function handleGateSubmit(ev) {
  ev.preventDefault();
  if (gateBusy) return;

  const input = document.getElementById("gate-pass");
  const errorEl = document.getElementById("gate-error");
  const submitBtn = document.getElementById("gate-submit");
  errorEl.hidden = true;
  errorEl.textContent = "";

  // 이 페이지는 항상 HTTPS(또는 로컬 미리보기 — localhost 는 브라우저가
  // secure context 로 취급한다)로 서빙되므로 crypto.subtle 은 정상적으로
  // 있어야 한다. 그래도 없는 극단적 환경(구형 인앱 브라우저 등)에서
  // 조용히 아무 반응이 없는 것보다는, 이유를 알리고 통과시키지 않는
  // 편이 낫다 — 이 화면이 열리지 않아도 데이터 자체는 raw.githubusercontent.com
  // 에 그대로 있다(위 설명과 같은 사실 — 다만 여기 문구에는 안 낸다).
  if (typeof crypto === "undefined" || !crypto.subtle) {
    errorEl.textContent = "이 브라우저에서는 확인 기능을 사용할 수 없습니다. 다른 브라우저로 시도해주세요.";
    errorEl.hidden = false;
    return;
  }

  const passphrase = normalizePassphrase(input.value);
  if (!passphrase) return;   // #gate-pass 의 required 가 이미 막지만 방어적으로 한 번 더

  gateBusy = true;
  submitBtn.disabled = true;
  try {
    const hex = await pbkdf2Hex(passphrase);   // 600,000회 반복 — 위 절 설명 참조, 이 한 번만 비용을 낸다
    if (hex === GATE_PBKDF2_HEX) {
      // 평문을 저장한다(불리언이 아니다) — Worker 쓰기 요청에 이 값을
      // 그대로 실어 보내야 해서다(getStoredPassphrase/writeRecord 참조).
      setStoredPassphrase(passphrase);
      unlockAndStart();
    } else {
      errorEl.textContent = "코드가 일치하지 않습니다.";
      errorEl.hidden = false;
      input.value = "";
      input.focus();
    }
  } catch (e) {
    reportFatal(e);
    errorEl.textContent = "확인 중 오류가 발생했습니다. 다시 시도해주세요.";
    errorEl.hidden = false;
  } finally {
    gateBusy = false;
    submitBtn.disabled = false;
  }
}

document.getElementById("gate-form").addEventListener("submit", handleGateSubmit);

// 이 기기에서 이미 통과했으면 다시 묻지 않는다 — 매일 휴대폰에서 열어보는
// 화면에 매번 커튼을 치면 그 자체로 못 쓰게 된다(요구사항).
//
// 되돌아오는 길: 문구를 잊어도 페이지 조회 자체는 잃는 게 없다 — 데이터는
// 여전히 raw.githubusercontent.com 에 그대로 있다(위 설명). 페이지 자체에
// 다시 들어가고 싶으면 저장소 소유자가 새 문구를 고르고 그 PBKDF2 값으로
// GATE_PBKDF2_HEX 를 바꿔 커밋하면 된다(이때 Worker 의 GATE_PASS 시크릿도
// 같은 새 문구로 같이 바꿔야 한다 — worker/README.md 3단계 — 안 그러면
// 새 문구로 커튼은 통과되는데 Worker 쓰기는 401 로 막히는 어긋난 상태가
// 된다). 단, isGateOpen() 은 GATE_PBKDF2_HEX 가 아니라 GATE_STORAGE_KEY 에
// 저장된 값이 있는지만 본다 — 이미 통과해 둔 기기는 해시가 바뀐 뒤에도
// 계속 안 물어본다(그 기기는 이미 들어와 있으니 문제가 아니다. 다만 그
// 기기가 들고 있는 옛 평문으로 Worker 에 쓰려 하면, GATE_PASS 도 같이
// 바뀌었을 경우 401 로 거부된다 — #result 가 그 상태를 그대로 보여준다).
// "이번엔 모든 기기가 다시 확인하게 하고 싶다"처럼 그 반대가 필요해지면
// GATE_STORAGE_KEY 의 "_v2"를 "_v3"으로 올린다 — 옛 기기가 들고 있는
// 키와 안 겹치는 새 키가 되어 전부 다시 묻는다.
if (isGateOpen()) {
  unlockAndStart();
}
