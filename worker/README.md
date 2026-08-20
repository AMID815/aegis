# 모의고사 쓰기 프록시 — 배포 가이드

이 폴더의 `worker.js` 는 [Cloudflare Workers](https://workers.cloudflare.com/) 위에서
돈다. 하는 일은 딱 하나 — 페이지가 보낸 패스프레이즈를 확인하고, 맞으면 `mouigosa`
저장소에 깃허브 이슈를 하나 여는 것뿐이다. 그 다음(이슈 → `positions.json` 반영)은
기존 `intake.yml`/`scripts/intake.py` 가 전혀 안 바뀐 채로 그대로 처리한다.

Cloudflare 를 한 번도 안 써봤다는 전제로 처음부터 적는다. 순서대로 하면 된다.

**정리 — 소스에 직접 고쳐 넣어야 하는 자리표시자는 모두 3곳이다** (아래
1~4단계가 그 순서대로 데려간다. 이 셋을 전부 안 고치면 페이지가 열리지
않거나(커튼이 영원히 안 열림), 열려도 저장이 항상 깃허브 폴백으로만 간다):

1. `app.js` 의 `GATE_PBKDF2_HEX` — 2단계
2. `app.js` 의 `WORKER_URL` — 4단계
3. `index.html` 의 CSP `connect-src` 안 같은 Worker 주소 — 4단계

---

## 0. 필요한 것

- [Node.js](https://nodejs.org/) (LTS 버전이면 충분 — `npx` 명령이 필요하다)
- 무료 Cloudflare 계정 — <https://dash.cloudflare.com/sign-up> 에서 이메일로 가입.
  신용카드 필요 없음, Workers 무료 플랜으로 충분하다(하루 요청 수 한도가 이 앱의
  실제 사용량보다 훨씬 크다).
- 이 저장소(`mouigosa`)에 대한 fine-grained PAT (아래 1단계에서 직접 만든다)

---

## 1. GitHub PAT 만들기 — **Issues 권한만** 준다

이게 이 설계에서 가장 중요한 단계다. 잘못 만들면(예: Contents 권한을 같이 주면)
`amid815.github.io` 오리진 전체(모의고사와 같은 오리진을 쓰는 다른 대시보드
포함)가 위험해진다.

1. 브라우저로 다음 주소를 연다(로그인된 계정이 `AMID815` 여야 한다):
   <https://github.com/settings/personal-access-tokens/new>
2. 아래대로 채운다:
   - **Token name**: `mouigosa-intake-worker` (아무 이름이나 되지만 나중에 알아보기
     쉽게)
   - **Expiration**: 원하는 기간(예: 1년). 만료되면 다시 만들어서
     `wrangler secret put GH_TOKEN` 을 다시 돌리면 된다.
   - **Resource owner**: `AMID815`
   - **Repository access**: **Only select repositories** → `mouigosa` 하나만 선택
   - **Permissions → Repository permissions → Issues**: **Read and write** 로 바꾼다.
     **그 외 모든 권한은 전부 "No access" 로 남겨둔다** — 특히 **Contents 는
     반드시 No access** 여야 한다.
3. **Generate token** → 화면에 뜬 토큰 문자열(`github_pat_...`)을 그 자리에서
   복사해둔다(다시 못 본다). 아직 어디에도 붙여넣지 않는다 — 3단계에서
   `wrangler secret put` 으로 Cloudflare 안에만 넣는다.

**확인**: 토큰을 만든 뒤 Settings → Developer settings → Personal access tokens →
Fine-grained tokens 목록에서 `mouigosa-intake-worker` 를 클릭해 Permissions 가
`Issues: Read and write` 하나뿐이고 `Contents` 가 없는지 다시 한번 본다.

---

## 2. 통과 문구(패스프레이즈) 검증값 계산하기

**이 문구는 Claude 에게 절대 말하지 않는다** — 아래 명령을 여러분 컴퓨터에서
직접 실행하면 터미널이 입력을 안 보여주며 물어보고(getpass), 그 결과 해시 값만
화면에 남는다. Claude 는 이 문구도, 이 명령의 실행 결과도 보지 못한다.

```
python -c "import hashlib, unicodedata, getpass; \
p = unicodedata.normalize('NFC', getpass.getpass('passphrase: ').strip()); \
salt = b'mouigosa-gate-salt-v1'; \
dk = hashlib.pbkdf2_hmac('sha256', p.encode('utf-8'), salt, 600000, dklen=32); \
print(dk.hex())"
```

나온 64자 16진수 문자열을 `app.js` 의 `GATE_PBKDF2_HEX` 상수에 붙여넣는다(app.js
안의 정확한 위치는 그 상수 옆 주석에 있다).

이 값은 페이지가 **커튼을 열지 말지**(누가 이 화면을 볼 수 있는지)만 판단하는 데
쓴다 — 소금(salt)·반복횟수(600,000)가 페이지 소스에 그대로 공개돼 있어서, 이
해시 하나만으로 실제 문구를 완전히 막을 수는 없다(오프라인 대입 공격의 시간당
비용을 올릴 뿐이다) — 왜 이 정도로 충분하다고 판단했는지는 이 작업의 보고서와
`app.js` 의 통과 커튼 절 주석에 있다.

**Worker 쪽 시크릿(`GATE_PASS`, 3단계)에는 해시가 아니라 이 문구 자체(평문)를
넣는다** — 헷갈리지 말 것. 위에서 계산한 해시는 페이지 소스용, 아래 3단계에서
넣는 값은 Worker 시크릿용이고 서로 다른 형태(하나는 해시, 하나는 평문)다.

**문구 선택 — 무작위 4단어 이상을 쓸 것.** 이 해시(`GATE_PBKDF2_HEX`)는 공개
저장소에 **영구히** 남는다 — 지워도 git 이력에 남고, 커밋을 되돌려도 GitHub 은
과거 커밋을 계속 서빙한다. 반복횟수(600,000회)는 오프라인 대입 공격의 비용을
SHA-256 한 번보다 약 60만 배 올리지만, 그래도 GPU 한 대가 초당 10억 회 안팎을
시도한다고 보면 `mouigosa2026!` 류의 흔한 패턴은 몇 시간, 소문자+숫자 6자는
GPU-일 단위로 뚫린다. 무작위로 고른 영어 단어 4개 이상(예: 사전에 없는 조합,
`correct horse battery staple` 류)이면 이 비용이 GPU-년 단위 이상으로 뛴다 —
반복횟수를 더 올리는 것보다 이쪽이 훨씬 효과가 크다.

---

## 3. Worker 배포하고 시크릿 넣기

이 폴더(`worker/`)에서 실행한다.

```
cd worker
npx wrangler login
```

브라우저가 열리며 Cloudflare 계정 로그인 및 권한 승인을 요청한다. 승인하면
터미널로 돌아와 다음을 계속한다.

```
npx wrangler deploy
```

성공하면 마지막 줄에 배포된 주소가 나온다. 예:

```
Published mouigosa-intake (x.xx sec)
  https://mouigosa-intake.<계정서브도메인>.workers.dev
```

**이 URL을 기록해둔다** — 4단계에서 페이지 쪽에 붙여넣는다.

이제 시크릿 두 개를 넣는다(값 입력 시 터미널에 그대로 표시되지 않는 대화형
프롬프트가 뜬다):

```
npx wrangler secret put GH_TOKEN
```
→ 1단계에서 복사해둔 `github_pat_...` 값을 붙여넣고 Enter.

```
npx wrangler secret put GATE_PASS
```
→ 2단계에서 쓴 것과 **똑같은 통과 문구(평문, 해시 아님)**를 붙여넣고 Enter.
앞뒤 공백이 섞이지 않게 주의한다 — Worker 가 trim 은 해주지만, 중간에 다른
문자가 섞이면 트림으로 못 고친다.

시크릿을 바꾸고 싶으면 같은 명령을 다시 실행하면 덮어써진다. 확인:

```
npx wrangler secret list
```
→ `GH_TOKEN`, `GATE_PASS` 이름만 보이고(값은 절대 안 보여준다) 둘 다 있는지 확인.

---

## 4. 페이지 쪽에 Worker 주소 연결하기

위 "정리"의 3곳 중 나머지 둘이다 — 첫 번째(`GATE_PBKDF2_HEX`)는 이미 2단계에서
끝났어야 한다, 잊었다면 지금 돌아가서 먼저 채운다.

두 파일에 있는 자리표시자 `REPLACE_WITH_YOUR_WORKER_URL` 을 3단계에서 받은 실제
주소로 **정확히** 바꾼다(호스트만, 끝에 슬래시 없이):

- `app.js` 의 `WORKER_URL` 상수
- `index.html` 의 CSP `connect-src` 안 같은 문자열

두 곳 다 안 바꾸면 페이지는 계속 "미설정"으로 보고 깃허브 폴백만 쓴다(고장은
아니다 — 그냥 Worker 경로를 안 쓸 뿐이다). 한쪽만 바꾸면 CSP 가 요청을
막아버려서 매번 폴백으로 떨어진다(이것도 조용히 실패하지 않고 그냥 폴백으로
동작한다 — 다만 의도한 대로 Worker 를 안 쓰고 있다는 뜻이므로 두 곳 다 바꿨는지
다시 확인할 것).

바꾼 뒤 평소처럼 커밋 + push 한다(이 저장소는 공개이니 Worker 주소 자체가
공개되는 건 문제 없다 — 패스프레이즈 없이는 아무것도 못 한다).

---

## 5. 확인

1. 페이지를 새로고침하고 통과 문구를 입력해 커튼을 연다.
2. 매수 하나를 테스트로 넣어본다(정말 넣기 싫으면 값을 넣었다가 제출 직전에
   취소해도 된다 — 어차피 다음 단계에서 실수해도 `intake.py` 가 사람이 읽을
   진단과 함께 거부하거나, 최악의 경우도 이슈 하나가 남는 것뿐이다. 잘못
   들어갔으면 "고치기"로 고치거나 이슈/커밋 이력에서 되돌리면 된다).
3. 제출 후 화면에 "이슈 #N 이 생성되었습니다" 같은 초록색 메시지와 링크가
   보이면 성공이다. 링크를 눌러 실제 깃허브 이슈가 열렸는지, 몇 분 뒤
   자동으로 닫히며 "반영했습니다" 코멘트가 달리는지 확인한다.
4. 안 되면(빨간/회색 메시지) 화면 문구를 그대로 읽는다 — "인증 실패"면 2/3단계의
   문구가 서로 다른 것, "연결하지 못했습니다"면 4단계를 다시 확인, 그 외는
   `npx wrangler tail` (배포한 폴더에서 실행하면 실시간 로그가 뜬다)로 Worker
   로그를 본다.

---

## 6. 통과 문구를 나중에 바꾸고 싶다면 — 세 단계, 순서대로

문구 하나가 커튼(페이지)과 Worker 인증 둘 다에 쓰이므로(app.js 통과 커튼 절
주석 참조), 셋 다 해야 어긋나지 않는다. 하나만 하면 "커튼은 새 문구로 열리는데
저장은 401로 막힘"(또는 그 반대) 상태가 된다.

1. **새 검증값 계산** — 2단계의 python 명령을 새 문구로 다시 돌려 나온 해시를
   `app.js` 의 `GATE_PBKDF2_HEX` 에 덮어쓰고 커밋한다.
2. **Worker 시크릿 갱신** — `cd worker && npx wrangler secret put GATE_PASS` 로
   같은 새 문구(평문)를 다시 넣는다. 이 명령은 있으면 덮어쓴다 — 기존 값을
   먼저 지울 필요 없다.
3. **(선택) 이미 통과해 둔 기기를 전부 다시 물어보게 하고 싶다면** — `app.js`
   의 `GATE_STORAGE_KEY` 값 끝의 버전 번호를 올린다(`_v2` → `_v3` 등, 그 옆
   주석에 이유가 있다). 안 올리면 이미 커튼을 통과해 둔 기기는 계속 안
   물어본다 — 그 기기가 들고 있던 옛 문구로 Worker 에 쓰려 하면 2번에서
   바꾼 새 `GATE_PASS` 와 어긋나 401 로 막히므로, 그 기기도 결국은 다시
   로그인하게 된다(그냥 언제 물어볼지의 차이다).

---

## 참고 — `devstub.py` 는 배포용이 아니다

같은 폴더의 `devstub.py` 는 이 Worker 를 배포하지 않고도 페이지 동작을 로컬에서
확인하기 위한 개발 도구다. 진짜 깃허브 이슈를 만들지 않고 그런 척만 한다.
**실제 배포에는 전혀 쓰이지 않는다** — 위 1~4단계만으로 배포가 끝난다.
