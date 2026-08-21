// 모의고사 — 쓰기 프록시 (Cloudflare Worker)
//
// 이 Worker 는 데이터를 쓰지 않는다. 하는 일은 정확히 둘뿐이다:
//   1. 페이지가 보낸 패스프레이즈를 확인한다(GATE_PASS, 시크릿).
//   2. 확인되면 소유자(AMID815) 명의로 깃허브 이슈를 하나 연다(GH_TOKEN, 시크릿).
// 그 다음은 이 저장소의 intake.yml → scripts/intake.py → scripts/models.py 가
// 그대로 처리한다 — 이 파일이 바뀌어도 그 파이프라인은 전혀 안 바뀐다.
//
// 토큰 스코프가 이 설계의 핵심이다: GH_TOKEN 은 이 저장소(aegis)에
// "Issues: Read and write" 권한만 가진 fine-grained PAT여야 한다. **Contents
// 권한은 절대 주지 않는다** — Contents:write 토큰은 main 브랜치의 app.js 를
// 갈아치울 수 있고, 그러면 amid815.github.io 오리진 전체(모의고사와 같은
// 오리진을 쓰는 다른 네 개 대시보드 포함)에 스크립트를 심을 수 있게 된다.
// Issues 권한만 있는 토큰은 이슈를 열 수 있을 뿐 코드를 한 글자도 못 건드린다
// — 유출돼도 피해가 "이슈 스팸/기록 오염"으로 막힌다(게다가 intake.yml 의
// 작성자 검사 덕에 이슈 자체는 아무나 열어도 이 토큰 없이는 반영되지 않는다;
// 이 토큰이 새는 경우는 "반영까지 가능한" 이슈를 임의로 열 수 있게 된다는
// 뜻이다).
//
// 이슈로 생성된 요청이 실제로 워크플로를 트리거하려면 PAT 로 만들어야 한다
// (실측: GITHUB_TOKEN 으로 만든 이슈는 issues.opened 이벤트를 안 낸다 — 이게
// 바로 이 Worker 가 존재하는 이유다).

// ── 설정 ────────────────────────────────────────────────────────────────

const OWNER = "AMID815";
const REPO = "aegis";
const GITHUB_API = `https://api.github.com/repos/${OWNER}/${REPO}/issues`;

// 이 오리진에서 온 요청만 브라우저가 응답을 읽을 수 있게 한다(CORS). 이게
// 보안의 전부는 아니다 — 패스프레이즈 없이는 어차피 401 이라, 이건 어디까지나
// "브라우저를 거친 요청"에 대한 위생이지 이 엔드포인트 자체를 숨기지 않는다.
const ALLOWED_ORIGIN = "https://amid815.github.io";

// 페이로드 JSON 문자열 길이 상한. intake.py 의 MAX_BODY(8000자, 이슈 본문
// 전체 기준)보다 한참 여유 있게 훨씬 작게 잡는다 — 실제 페이로드는 최대
// 수백 바이트다(name 40자·source 20자·memo 200자, models._text 상한). 이 값은
// models.py 를 다시 구현하는 게 아니라 그냥 "터무니없이 큰 요청" 방지용
// 모양 점검이다 — 진짜 검증은 intake.py/models.py 가 한다.
const MAX_PAYLOAD_CHARS = 4000;

// intake.apply()(scripts/intake.py)가 라우팅하는 op 전체 목록과 정확히
// 같아야 한다 — 새 op 를 추가할 때마다 반드시 여기(와 OP_LABEL)도 같이
// 고친다. 이 목록이 왜 "models.py 를 다시 구현하지 않는다"는 원칙의
// 유일한 예외인지, 그리고 동기화가 깨져도 왜 거의 안 보이는지는 아래
// isPlausiblePayload() 위 설명 참조.
const KNOWN_OPS = new Set([
  "buy", "sell", "amend", "watch", "orders", "auto", "delete",
]);
const OP_LABEL = {
  buy: "BUY", sell: "SELL", amend: "AMEND",
  watch: "WATCH", orders: "ORDERS", auto: "AUTO", delete: "DELETE",
};

// ── CORS ────────────────────────────────────────────────────────────────

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    // 캐시가 이 응답을 다른 오리진에게 잘못 재사용하지 않게.
    Vary: "Origin",
  };
}

// 모든 응답이 반드시 이 함수를 거친다 — CORS 헤더가 성공 응답에만 붙고
// 오류 응답(401/400/500 등)에는 빠지면, 브라우저의 fetch() 는 그 오류
// 응답을 "읽을 수 없는 응답"이 아니라 아예 **네트워크 오류**로 본다(CORS
// 실패와 구분이 안 된다). 페이지는 "Worker 에 연결할 수 없음"(네트워크
// 오류)과 "Worker 가 거부함"(예: 401 틀린 패스프레이즈)을 다르게 안내해야
// 하므로, 오류 응답에도 CORS 헤더가 반드시 있어야 fetch() 가 상태코드를
// 읽을 수 있다.
function json(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders() },
  });
}

// ── 상수시간 비교 ───────────────────────────────────────────────────────
//
// 순수 `===` 문자열 비교는 두 가지를 새어나가게 한다: (1) 두 문자열 길이가
// 다르면 JS 엔진이 즉시 false 를 내므로 길이가 노출되고, (2) V8 의 문자열
// 비교는 앞에서부터 다르면 그 지점에서 끊기는 구현이 흔해 "몇 글자까지
// 맞았는지"가 응답 시간차로 새어나갈 수 있다(네트워크 지터에 묻히긴
// 하지만, 반복 요청으로 평균을 내면 이론적으로 복원 가능하다).
//
// 여기서는 두 문자열을 먼저 SHA-256 으로 고정 길이(32바이트)로 만든 뒤에
// 비교한다 — 그러면 애초에 "길이가 다르다"는 조기 탈출 자체가 없어지고,
// 다이제스트 비교는 XOR 누적으로 전 바이트를 항상 끝까지 읽어 어디서
// 갈렸는지가 시간차에 안 남는다. 원본 문자열 길이가 아무리 달라도 이
// 비교 자체의 소요 시간은 항상 같다.
async function timingSafeEqual(a, b) {
  const enc = new TextEncoder();
  const [da, db] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(a)),
    crypto.subtle.digest("SHA-256", enc.encode(b)),
  ]);
  const va = new Uint8Array(da);
  const vb = new Uint8Array(db);
  let diff = 0;
  for (let i = 0; i < va.length; i++) diff |= va[i] ^ vb[i];
  return diff === 0;
}

// 페이지(app.js: normalizePassphrase)와 같은 정규화 — trim → NFC. 사용자가
// `wrangler secret put GATE_PASS` 에 붙여넣을 때 끝에 개행이나 공백이
// 섞이는 흔한 실수, 그리고 한글 자모가 IME 에 따라 NFC/NFD 로 다르게
// 들어오는 경우를 여기서도 흡수한다 — 안 그러면 페이지 쪽 문구와 눈으로는
// 같은데 바이트가 달라 401 이 나는, 원인 찾기 아주 어려운 버그가 된다.
function normalizePassphrase(raw) {
  return typeof raw === "string" ? raw.trim().normalize("NFC") : "";
}

// ── 페이로드 모양 점검(shape sanity) ───────────────────────────────────
//
// models.py 를 다시 구현하지 않는다 — intake.py 가 그 권위다. 여기서 보는
// 건 "이게 요청 흉내라도 내고 있는가"(object 인가, op 를 아는가) 뿐이다.
// 필드 값 하나하나(가격이 숫자인지, 날짜가 유효한지 등)는 전혀 보지
// 않는다 — 그건 intake.py 가 사람이 읽을 수 있는 종료코드(2/3/4)로 이미
// 잘 처리한다. 여기서 더 엄격하게 굴면 두 곳의 규칙이 갈라져(예: Worker는
// 통과시켰는데 intake 는 거부, 혹은 그 반대) 사용자가 "Worker 는 됐다는데
// 왜 이슈엔 거부 코멘트가 달리지" 하는 혼란만 는다.
//
// 이 원칙에 예외가 딱 하나 있다: KNOWN_OPS(위)는 필드 값 검증이 아니라
// "op 라는 이름 자체를 아는가"라서 위 비-중복 논리가 안 통한다 —
// intake.apply() 가 아는 op 목록이 바로 여기 있고, 다른 데서 다시
// 베낄 수도 없다. 그런데 이 목록이 낡아도(intake.apply() 는 새 op 를
// 아는데 여기는 모르는 상태) 거의 안 보인다는 게 함정이다: 패스프레이즈
// 검사가 이 검사보다 먼저 실행되므로(아래 fetch 핸들러), 패스프레이즈가
// 틀린 프로브는 op 값과 무관하게 항상 401 로 막혀 이 400 이 절대
// 드러나지 않는다. 정상 패스프레이즈를 가진 **진짜 사용자**가 새 op 를
// 실제로 써야만 드러나므로, 흔한 배포 후 스모크 테스트("틀린
// 패스프레이즈로 401 이 오나"만 확인)로는 절대 못 잡는다 — 실측:
// watch/orders/auto/delete 가 models.py·intake.py 에는 이미 구현돼
// 있는데 KNOWN_OPS 는 buy/sell/amend 셋뿐이던 채로 배포돼 있었다
// (2026-08-21 발견, 실제 사용자 요청에서만 드러남). models.py 에 op 를
// 하나 추가하고 intake.apply() 에 라우팅을 연결할 때마다, KNOWN_OPS(와
// OP_LABEL)도 반드시 같이 고친다.
function isPlausiblePayload(payload) {
  return (
    payload !== null &&
    typeof payload === "object" &&
    !Array.isArray(payload) &&
    typeof payload.op === "string" &&
    KNOWN_OPS.has(payload.op)
  );
}

// ── 이슈 제목/본문 조립 ─────────────────────────────────────────────────
//
// 본문은 intake.extract() 가 요구하는 형식과 **정확히** 같아야 한다
// (scripts/intake.py FENCE = ```` ```json\s*(.+?)\s*``` ````, 정확히 하나).
// 페이지의 issueUrl() 이 만드는 문자열과 글자 하나까지 같게 맞춘다 —
// Worker 를 거치든 깃허브 폴백을 거치든 intake 입장에서 똑같은 모양이어야
// 한다.
function buildBody(payload) {
  return "모의고사 입력\n\n```json\n" + JSON.stringify(payload) + "\n```";
}

// 제목은 intake.extract() 가 전혀 읽지 않는다(본문의 fenced json 블록만
// 본다) — 그러니 순수하게 사람이 이슈 목록에서 알아보기 위한 장식이다.
// `display` 는 페이지가 보내는 선택 힌트(종목명) — 매도/일부 amend 는
// payload 안에 이름이 없어서(§ 클라이언트가 NAMES/master.json 조회로만
// 아는 값이라 Worker 는 원래 모른다) 페이지가 알려주지 않으면 코드로
// 대체한다. 검증된 필드가 아니므로 개행 제거·길이 제한만 하고 그 이상
// 신뢰하지 않는다.
function buildTitle(payload, display) {
  const label = OP_LABEL[payload.op] || "WRITE";
  let name = typeof display === "string" ? display : "";
  name = name.replace(/[\r\n]+/g, " ").trim().slice(0, 60);
  if (!name) {
    name =
      (typeof payload.name === "string" && payload.name) ||
      (typeof payload.code === "string" && payload.code) ||
      "?";
  }
  return `${label} ${name}`.slice(0, 200); // 깃허브 실제 상한(수백자)보다 넉넉히 여유
}

// ── 본체 ────────────────────────────────────────────────────────────────

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }
    if (request.method !== "POST") {
      return json(405, { ok: false, error: "POST만 허용합니다." });
    }

    if (!env.GATE_PASS || !env.GH_TOKEN) {
      // 배포는 됐는데 시크릿을 아직 안 넣은 상태 — 클라이언트 잘못이
      // 아니므로 401(인증 실패)이 아니라 500(서버 설정 문제)으로 구분한다.
      return json(500, { ok: false, error: "Worker 시크릿이 설정되지 않았습니다." });
    }

    // 2026-08-20 보안 리뷰 minor — Content-Length 를 먼저 본다. request.text()
    // 로 본문 전체를 다 받은 뒤에야 길이를 재면, 무료 플랜의 요청당 CPU
    // 예산(10ms) 안에서 수 MB 짜리 본문을 디코딩하다가 이 검사에 닿기도
    // 전에 CPU 리미터가 먼저 끊어버릴 수 있다 — 그러면 런타임이 CORS
    // 헤더 없는 자체 오류를 내고, 브라우저는 이걸 "network"로 오판해
    // (tryWorker) 조용히 깃허브 폴백으로 넘어간다. 헤더 단계에서 먼저
    // 걸러내면 본문을 아예 안 읽으므로 이 경로 자체가 생기지 않는다.
    // (Content-Length 를 안 보내는 요청도 있을 수 있어 — 아래 raw.length
    // 검사는 그 경우를 위한 방어로 그대로 남긴다.)
    const declaredLength = Number(request.headers.get("content-length") || 0);
    if (declaredLength > MAX_PAYLOAD_CHARS + 200) {
      return json(400, { ok: false, error: "요청이 너무 큽니다." });
    }

    let body;
    try {
      const raw = await request.text();
      if (raw.length > MAX_PAYLOAD_CHARS + 200) {
        // +200 은 {pass, payload, display} 감싸는 JSON 오버헤드용 여유.
        // Content-Length 헤더가 없거나 거짓이었던 경우의 2차 방어.
        return json(400, { ok: false, error: "요청이 너무 큽니다." });
      }
      body = JSON.parse(raw);
    } catch (e) {
      return json(400, { ok: false, error: "JSON 파싱 실패." });
    }

    if (!body || typeof body !== "object") {
      return json(400, { ok: false, error: "요청 형식이 올바르지 않습니다." });
    }

    const pass = typeof body.pass === "string" ? body.pass : "";
    const payload = body.payload;

    // 페이지도 같은 정규화를 거친 뒤 저장한 값을 보낸다(app.js
    // normalizePassphrase) — 여기서도 같은 정규화를 한 번 더 거는 이유는
    // env.GATE_PASS 를 `wrangler secret put` 으로 넣을 때 섞일 수 있는
    // trailing whitespace/개행, 그리고 한글 정규화 형태(NFC/NFD) 차이를
    // 흡수하기 위해서다 — 흡수하지 않으면 눈에는 같은 문구인데 401 이
    // 나는, 사용자가 원인을 알 길이 없는 버그가 된다.
    const ok = await timingSafeEqual(
      normalizePassphrase(pass),
      normalizePassphrase(env.GATE_PASS)
    );
    if (!ok) {
      // 어느 쪽이 틀렸는지(길이/내용) 절대 말하지 않는다 — 그 자체가
      // 공격자에게 신호가 된다.
      return json(401, { ok: false, error: "인증 실패." });
    }

    if (!isPlausiblePayload(payload)) {
      // 허용 op 를 여기 다시 하드코딩하지 않는다 — 문자열 그대로 베껴
      // 놓으면 이 메시지 자체가 KNOWN_OPS 와 또 따로 낡을 수 있다(바로
      // 위 KNOWN_OPS 가 겪은 함정과 같은 모양). KNOWN_OPS 에서 그때그때
      // 뽑아 쓴다.
      return json(400, {
        ok: false,
        error: `payload 형식이 올바르지 않습니다(op: ${[...KNOWN_OPS].join("/")} 필요).`,
      });
    }

    const title = buildTitle(payload, body.display);
    const issueBody = buildBody(payload);

    let ghResp;
    try {
      ghResp = await fetch(GITHUB_API, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_TOKEN}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
          "X-GitHub-Api-Version": "2022-11-28",
          // 깃허브는 User-Agent 없는 요청을 거부한다.
          "User-Agent": "aegis-intake-worker",
        },
        body: JSON.stringify({ title, body: issueBody }),
      });
    } catch (e) {
      // 깃허브 API 자체에 못 닿음(네트워크) — 클라이언트 잘못이 아니다.
      return json(502, { ok: false, error: "깃허브에 연결하지 못했습니다." });
    }

    if (!ghResp.ok) {
      // 깃허브가 돌려준 진단 메시지는 그대로 보여줘도 안전하다(토큰을
      // 절대 되풀이하지 않는다 — GitHub API 는 애초에 응답에 요청 헤더를
      // 반영하지 않는다). 상태코드는 그대로 실어 페이지가 "Worker가
      // 거부"(4xx, 폴백 없이 안내만)와 "업스트림 실패"(5xx 포함, 여기선
      // 뭉뚱그려 502)를 구분하지 않게 한다 — 어느 쪽이든 사용자가 할 수
      // 있는 일은 같다(깃허브 폴백으로 직접 열기).
      let detail = "";
      try {
        const errJson = await ghResp.json();
        if (errJson && typeof errJson.message === "string") detail = errJson.message;
      } catch (e) {
        // 진단 실패해도 아래 기본 메시지로 계속 진행 — 무시.
      }
      console.error("GitHub issue 생성 실패:", ghResp.status, detail);
      return json(502, {
        ok: false,
        error: "깃허브 이슈 생성에 실패했습니다" + (detail ? `: ${detail}` : "."),
      });
    }

    // 2026-08-20 보안 리뷰 I2 — 여기서 그냥 await 하다 파싱이 던지면(깃허브가
    // 201 인데 본문이 JSON 이 아닌 드문 경우) 이 fetch 핸들러 자체가 예외로
    // 끝나 런타임이 자체 오류 페이지를 낸다 — 그 페이지엔 CORS 헤더가 없어
    // 브라우저가 응답을 아예 못 읽고, 페이지(app.js)는 이걸 "network"로
    // 오판해 **이미 만들어진 이슈에 대해** 깃허브 폴백으로 또 하나를 연다
    // (중복 생성). 이슈는 이미 성공적으로 만들어졌으므로(ghResp.ok 를
    // 통과했다) 실패로 되돌리지 않는다 — number/url 을 못 읽었을 뿐이라고
    // 정직하게 반영한다. 클라이언트의 bad-response 분기가 이미 이 모양
    // (number 가 숫자가 아님)을 "blocked, 자동 폴백 없음"으로 처리한다.
    let created = {};
    try {
      created = await ghResp.json();
    } catch (e) {
      console.error("이슈는 생성됐으나 응답 파싱 실패:", e);
    }
    return json(201, {
      ok: true,
      number: created.number,
      url: created.html_url,
    });
  },
};
