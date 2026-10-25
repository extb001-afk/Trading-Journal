# tj-bot 보안

← [README.md](../README.md)

## 보안 · 데이터

- **조회만 합니다.** 개인 키·시드 문구를 요구하지 않고, 거래소·증권사 키로는 잔고·내역 조회 API 만 부릅니다(주문·출금 코드 없음).
- **웹은 127.0.0.1 바인딩이 기본**이고 비밀번호 로그인(기본 켜짐 — PBKDF2-SHA256 해시, HttpOnly·SameSite=Strict 세션 쿠키, 시도 제한)으로
  잠겨 있습니다. 모든 응답에 프레임 차단·nosniff 헤더가 붙고, 서버 오류 화면에 내부 경로·값을 싣지 않습니다. 모든 쓰기 요청(POST)은 같은 출처(Origin) + CSRF 토큰을 확인하고,
  키 입력 API 는 로컬/테일넷 접속(또는 로그인된 리버스 프록시 경유)만 받습니다. 모든 요청의 Host 를 검사합니다(DNS 리바인딩 방지).
  로그인이 꺼져 있으면 리버스 프록시·터널 헤더가 붙은 요청을 전부 거부합니다.
  **사설 IP(RFC 1918 · 10.x·172.16~31.x 등 공유기 내부 주소)·테일넷 바인딩 = 로그인 필수 + HTTPS 프록시 권장** — 로그인이 꺼져 있으면 tj-web 이 시작을 거부합니다(같은 네트워크 누구나 자산 전부를 보게 되므로 ·
  정말 원하면 `web.login.allow_lan_without_password: true` 를 명시해야만 열림 · 권장 안 함). 사설 IP 는 HTTP 라 비밀번호·쿠키가 암호화 없이 오가니 HTTPS 리버스 프록시를 쓰세요 —
  `web.behind_proxy: true` 면 로그인 쿠키에 늘 `Secure` 가 붙습니다(`web.login.secure_cookie: false` 명시만 예외 · 기동 로그 오류).
- 비밀값(탐색기·거래소·텔레그램 키)은 `.env`(600)에 저장되고 화면에는 •••• 로만 보입니다(거래소 공개 API 키만 끝 4자리).
  예외: 증권사 연결(미검증 · 기본 꺼짐)의 `app_secret`·`secret_key`·`client_secret`·`refresh_token` 등은 `config.json` 의 `brokers` 칸에 들어갑니다 —
  그래서 `config.json` 도 본인만 읽게(600) 둡니다: `tools/setup.sh` 가 만들 때·다시 실행할 때 600 으로 맞추고, tj-web 도 켜질 때 600 보다 넓으면 좁힙니다(내 파일일 때만).
  파일을 직접 복사해 넣었다면 `chmod 600 config.json .env` 를 한 번 해 두세요. `.env`·`config.json`·`state/` 는 `.gitignore` 에 들어 있습니다 — 절대 커밋하지 마세요.
- 밖으로 나가는 요청은 조회뿐입니다: 블록 탐색기·RPC(내 주소), 거래소 API, 가격(GeckoTerminal·DexScreener·거래소 공개 시세·주식/금 공개 시세),
  스캠 판정(GoPlus — 후보 토큰 주소만), 지갑 포트폴리오 보강(Rabby 공개 API — **기본 꺼짐** · `rabby.enabled: true` 로 켜면 평가액 $1,000 이상인 내 EVM 지갑 주소가 외부(DeBank 데이터)로 나감, 기준 `rabby.min_wallet_usd`),
  브릿지 탐색기(도착 확인), 환율, 텔레그램 발송, NFT 바닥가(코인게코·매직에덴·오픈시 — 컬렉션 주소만), Hyperliquid 공개 조회(내 주소),
  내 공인 IP 확인(api.ipify.org — 설정 화면에서 거래소 IP 허용 목록 안내 버튼을 누를 때만).
  원장 내용 자체는 보내지 않습니다. 예외: 서버 밖 백업(`backup.offsite` — 기본 꺼짐)을 켜면 압축한 원장 사본을 **내가 지정한 컴퓨터**로 ssh 로 보냅니다.
  예외: AI 기능(기본 꺼짐)을 켜면 그날 요약·영수증 요약을 내 컴퓨터의 `claude` CLI 로 보냅니다.
- **브라우저(화면)가 직접 부르는 외부 주소** — 위는 서버가 부르는 곳이고, 화면을 연 브라우저도 다음 곳에 직접 요청합니다(그 서비스는 접속 IP 를 볼 수 있어요):
  - **글꼴**(IBM Plex Sans KR·IBM Plex Mono) — 이제 저장소에서 제공(외부 요청 없음): `web/v2/fonts/` 의 글자 조각(woff2)을 tj-web 이 직접 내고,
    브라우저는 화면에 나온 글자의 조각만 받아요. 라이선스 = SIL Open Font License 1.1(`web/v2/fonts/OFL.txt`).
  - **코인 로고** — 받지 않아요(글자 아이콘만 · 외부 요청 0). 예전 판은 켜면 jsDelivr(`cdn.jsdelivr.net`)로 로고 요청이 나가 로고 주소의 **체인·컨트랙트 주소·심볼**로
    그 서비스가 내가 가진 토큰 목록을 짐작할 수 있었어요 — 로고 받기 자체를 뺐어요(`web.token_logos`·기기 설정 값은 남아 있어도 효과 없음).
  - **Cloudflare 같은 프록시·터널을 앞에 두면** 그쪽 설정에 따라 **Web Analytics** 스크립트(`static.cloudflareinsights.com`)가 페이지에 끼워 넣어질 수 있어요 —
    tj-bot 이 넣는 것이 아니라 프록시가 넣는 것이니, 원치 않으면 Cloudflare 대시보드에서 그 사이트의 Web Analytics(자동 삽입)를 끄세요.
- AI 리뷰·평가는 내 컴퓨터의 `claude` CLI 를 쓰며, 넘기는 환경변수는 허용 목록뿐입니다(PATH·HOME·로케일, 프록시 `HTTP(S)_PROXY`·`NO_PROXY`·`ALL_PROXY`,
  사내 인증서 `NODE_EXTRA_CA_CERTS`·`SSL_CERT_FILE`·`SSL_CERT_DIR`, Claude 로그인·게이트웨이·Bedrock·Vertex 변수). 거래소 키와 `.env` 값은 넘기지 않습니다.
  AI 매도·매수 평가는 기본 꺼짐 — `config.json` 의 `review.sell_eval_daily_max`·`review.buy_eval_daily_max` 를 1 이상(하루 최대 호출 수)으로 켭니다.
- 로그인 화면이 뜨면(로그아웃·만료·다른 기기에서 모두 로그아웃) 그 브라우저에 남은 화면 저장본(IndexedDB·버전 키)을 지웁니다.
- **원장 사본이 `state/` 밖에 생기는 때** — 자동 재구축(확장 백필 뒤 등) 동안 **홈 폴더**에 원장 약 3배 + 2GB 의 임시 사본(`~/tj_shadow_extrebuild_<시각>/`, 권한 700)과
  진단 보고서(`~/tj_shadow_extrebuild_<시각>.report.json`, 최근 3개)가 생겼다가 사본은 끝나면 지워집니다. 다른 사용자와 같이 쓰는 컴퓨터이거나 홈 폴더가 작으면
  `config.json` 의 `"backfill": {"rebuild_dir": "/내/디스크/경로"}` 로 옮기세요([백필 · 재구축](OPERATIONS.md#백필--재구축--재백필)).
- **보안 문제를 찾았다면** 공개 이슈 대신 저장소의 **Security › Report a vulnerability**(비공개 보고)로 알려 주세요. 재현 방법만 적고 실제 키·주소·잔고는 넣지 마세요.
