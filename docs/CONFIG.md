# tj-bot 설정

← [README.md](../README.md)

## 알아 두면 좋은 키

`config.json` 에서 알아 두면 좋은 키:

| 키 | 기본 | 설명 |
|---|---|---|
| `wallets` | 비어 있음 | 추적할 지갑 — 비워 두고 웹 화면에서 추가하면 됩니다 |
| `backfill_months` / `backfill_since` | 5개월 / 없음 | 처음 불러올 과거 기간 / 시작일(YYYY-MM-DD)로 앞당기기 |
| `web.port` · `web.bind` | 8023 · `loopback` | 화면 포트 / `loopback`(이 컴퓨터만, 권장) 또는 `tailscale`(테일넷 IP 추가) |
| `web.login.enabled` · `session_days` · `idle_days` | 켜짐 · 30 · 7 | 웹 비밀번호 로그인. **키가 없어도 켜짐** — 끄기는 `false` 를 적을 때만. 바꾸면 `pm2 restart tj-web` |
| `web.login.secure_cookie` | false(`behind_proxy: true` 면 true) | true 면 로그인 쿠키에 항상 `Secure`(HTTPS 로만 열 때). HTTPS 리버스 프록시가 `X-Forwarded-Proto: https` 를 붙이면 꺼 둬도 자동으로 붙음. `web.behind_proxy: true` 면 적지 않아도 켜짐 — `false` 를 명시할 때만 꺼짐(기동 로그 ERROR · HTTP 프록시 뒤에서만) |
| `web.allowed_hosts` · `web.public_url` | 비어 있음 | 리버스 프록시·터널 도메인(Host 허용) / 텔레그램 알림 '보기' 링크 주소(`https://도메인`만, 비우면 링크 없음) — [아래](INSTALL.md#6-화면-열기--다른-기기에서-보기) |
| `web.login.allow_lan_without_password` | 없음(false) | 로그인 꺼짐(`enabled: false`) + `bind` 가 사설 IP·`tailscale` 이면 tj-web 이 **시작을 거부**해요(같은 네트워크 누구나 자산 전부를 봄). 그래도 비밀번호 없이 열려면 `true` 를 적어야만 통과(기동 로그 ERROR 는 남음 · 권장 안 함) |
| `web.behind_proxy` | 없음(false) | true 면 모든 요청을 리버스 프록시 경유로 취급(헤더를 안 붙이는 프록시 뒤 · 첫 비밀번호는 `tools/reset_password.py`) · 로그인 쿠키 `Secure`(이름 `__Host-tj_session`) 기본 — 켜거나 끄는 판에선 기존 로그인이 한 번 풀림 |
| `web.setup_allow_lan` · `setup_allow_proxy` | 없음(false) | true 면 설정 바꾸기를 사설망(192.168.x 등) / 프록시·터널에서도 허용 — 기본은 루프백·테일넷만 |
| `web.token_logos` | 없음(false) | (호환으로 남은 키 — **효과 없음**) 화면이 토큰 로고를 받지 않아요(글자 아이콘만 · 외부 요청 0) · 예전 판의 '기본 꺼짐' 로고 스위치는 없어졌어요 |
| `review.sell_eval_daily_max` · `buy_eval_daily_max` | 0(끔) | AI 매도·매수 평가 하루 상한. 켜려면 예: 20 (`claude` CLI 필요) |
| `review.chart_prewarm_per_day` | 0(끔) | 영수증 차트 봉 미리 받기 하루 상한(영수증 한쪽 = 1 · 최대 300 · 모델 호출 없음 · `tj-review` 가 돌 때만). 보존 기한이 짧은 DEX 봉(GeckoTerminal 180일)부터 받아 영구 저장 · 화면이 차트를 받는 중이면 양보 · 무키 GeckoTerminal·코인게코는 분당 1회·429 면 그날 멈춤 · 코인게코 키는 프로의 남는 몫만. 예: 150. 바꾸면 `pm2 restart tj-review` |
| `review.coach_role` · `review.known_patterns` | 없음 | AI 일간·주간 리뷰 맞춤 — 첫 줄 트레이더 설명(예: "단타 위주 트레이더") / 지적하지 않을 내 운용 패턴 문장 목록(10개·각 200자) |
| `recon_tokens` | 없음 | 잔고 대사에 늘 넣을 토큰 `{"체인": {"0x토큰 CA": ["심볼", 소수 자리]}}` — 자동으로 켜진 추가 체인에 합쳐짐 |
| `health.heartbeat_url` · `heartbeat_sec` | 없음(꺼짐) · 300 | 감시기(tj-alert)를 밖에서 감시 — healthchecks.io 같은 서비스의 핑 주소를 넣으면 상태 점검이 한 바퀴 돌 때마다(최소 60초 간격) GET 한 번. tj-alert 가 죽거나 멈추면 핑이 끊겨 그 서비스가 알려 줍니다(실패는 조용히 다음 주기에) |
| `health.tunnel` | 없음(꺼짐) | 터널 유닛 감시 `{"unit": "pm2 이름", "ready_url": "http://127.0.0.1:<메트릭 포트>/ready"}` — 터널 연결 0 이 5분 이어지면 알림(클라우드플레어 터널 메트릭의 `/ready` 등) |
| `other_assets` · `brokers` | 증권사 전부 꺼짐 | 기타 자산 탭의 공개 시세 갱신 주기 / 증권사 보유 동기화(**실험(미검증)** — 켜려면 `other_assets.brokers.experimental_ack: true` 도 필요 · 필드 = src/brokers/README.md) |
| `chains.<체인>.enabled` | 체인마다 | 쓰지 않는 체인을 통째로 끄기 — 화면 **설정 › 지갑 · 주소 › 체인별 조회** 스위치가 이 값을 바꿔요 |
| (화면) 추천 체인 자동으로 끄기 | 켜짐 | 자동 끄기가 싫으면 **설정 › 지갑 · 주소 › 체인별 조회** 의 '추천 체인 자동으로 끄기' 스위치를 끄세요. 끄면 '끄는 걸 추천해요' 표시만 남고 자동으로 끄지 않아요. 이미 자동으로 꺼 둔 체인은 그대로라 다시 켜려면 그 체인 스위치를 직접 켜야 해요(재시작 필요 없음 · 값은 `state/ui_prefs.json`). 자동으로 켠 체인은 켠 뒤 30일 동안 끄기 추천·자동 끄기에서 빠져요 |
| `rpc_fallback` · `chains.<체인>.rpc_fallback` | 켜짐 | 이더스캔·블록스카웃이 막히면 그 체인을 공개 RPC 로 대체 — `false` 면 끔(전체 / 그 체인만) |
| `chains.base.discovery` | `rpc` | Base 수집 방식 — 공개 RPC 로 직접. `"explorer"` 면 블록스카웃(되돌리기) |
| `sol.helius_monthly_credits` | 없음(100만) | 헬리우스 월 크레딧(무료 플랜 100만). 유료 플랜이면 그 값을 적으세요 — 하루 몫 = 이 값의 80% ÷ 30 |
| `sol.helius_head_min_pct` | 10 | 옛 기록을 채우는 동안 새 거래 확인에 떼어 두는 헬리우스 하루 몫(%)의 상한 · 1~70 — 공개 노드가 새 거래 확인을 맡아 건강하면 실제 사용량 × 1.25 까지 줄여요(바닥 3%) |
| `sol.head_rpc` · `sol.archive_rpc` | publicnode · Solana 공식 공개 노드 | Solana 새 거래 확인용 / 헬리우스 몫이 없을 때 옛 기록용 공개 노드. `""` 면 끔(헬리우스만) |
| `price_overrides` | 없음 | 비상용 수동 가격 고정 |
| `loan_short` | 없음(꺼짐) | 거래소 대출로 빌려 출금했던 기간 — 예(합성): `[{"exchange": "okx", "asset": "ETH", "from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}]`(asset `"*"` = 그 거래소 전부 · 날짜 = UTC 그날 처음~끝). 그 기간에 거래소 보유가 출금으로 0 밑으로 내려갔다가 나중에 같은 거래소 입금·매수로 채워진 몫만 '빌린 코인'으로 계산(원가 = 빌린 시각 시가 · 갚을 때 되산 원가와의 차 = 실현 · 명세 '대출 상환' 행 · 화면 계산만 — 원장 무변). **대출 기록으로 확인된 기간만** 넣으세요 — 모양만으로는 정하지 않아요(6시간 안에 채워진 몫·업비트·빗썸·Hyperliquid·스테이블 제외 · 시세가 없으면 종전처럼 원가 미확인). 최초 인식 시가가 켜져 있을 때만(기본 켬) · 바꾸면 `pm2 restart tj-web` |

## 고급 설정

보통은 건드릴 일이 없는 값들이에요. 위 [키 준비](INSTALL.md#3-키-준비--env-와-configjson)의 `config.json` 표에 없는 것만 모았습니다.

**환경변수** (pm2 로 띄웠다면 `… pm2 restart ecosystem.config.js --update-env` 로 반영)

| 이름 | 기본 | 설명 |
|---|---|---|
| `TJ_BASE` | 저장소 폴더 | 설치 폴더(그 아래 `state/`·`config.json`·`.env`)를 다른 곳으로 |
| `TJ_CONFIG` | `<TJ_BASE>/config.json` | 설정 파일 경로만 따로 |
| `TJ_PYTHON` | `python3` | `ecosystem.config.js`·`tools/setup.sh` 가 쓸 파이썬 |
| `TJ_ENABLE_REVIEW` | 없음 | `1` 이면 `pm2 start ecosystem.config.js` 가 AI 리뷰 유닛 `tj-review` 도 띄움 |
| `TJ_BUILD_PROC` | `auto` | `auto` = 리눅스·코어 2개 이상이면 화면 계산을 tj-web 자식 프로세스에서(4개 이상이면 전용 코어 1개) · `off` = 끔(웹 안에서 계산 · 코어 배분 없음) · `fork` = 시험용 강제(맥은 권하지 않음). 환경변수 → `.env` → `config.json` 의 `build_proc` 순서로 읽고, 모든 유닛을 다시 켜야 반영 |
| `TJ_ASK_MODEL` | 리뷰와 같은 모델 | 문장 검색을 `claude` CLI 로 바꿀 때(`wow.ask_llm: true`) 쓸 모델 이름 |
| `TJ_EXT_REBUILD` | 켜짐 | `0` 이면 자동 재구축 끔(`backfill.auto_rebuild: false` 와 같음) |
| `TJ_HEALTH` | 켜짐 | `0` 이면 상태 점검(텔레그램 '봇이 멈춤' 등) 끔 |
| `TJ_DAYCLOSE` | 켜짐 | `0` 이면 30일 곡선의 그날 마감가 받기를 끄고 종전 방식으로(비상 스위치) |
| `TJ_NEGABS` | 켜짐 | `0` 이면 발견 시점 기초 잔고 끔(`negabs_enabled: false` 와 같음 · 요청·후보는 남고 처리만 쉼) |
| `TJ_TG_API` | 텔레그램 공식 주소 | 시험용 — `http://127.0.0.1:<포트>` 만 받음(그 밖의 주소는 무시) |
| `TJ_CONFIG_FAIL_WAIT` | 45 | `config.json` 이 깨졌을 때 pm2 아래에서 다시 켜지기 전 기다리는 초(최대 600) |
| `TJ_RUNNER_CHECK_SEC` · `TJ_RUNNER_SETTLE_SEC` | 15 · 10 | 유닛 러너가 설정 바뀜을 보는 간격 · 바뀐 뒤 기다렸다 다시 켜는 초 |
| `TJ_RUNNER_MAX_MB_<유닛>`(예: `TJ_RUNNER_MAX_MB_WEB`) | web 3072 · 그 밖 0(끔) | 유닛 러너가 띄운 프로세스의 메모리(RSS, MB) 상한 — 검사(15초) 2번 연속 넘으면 정상 종료 뒤 다시 켬(데이터 손실 없음 · 상태 패널에 '메모리 상한 넘어 다시 시작' 한 줄). `0` = 끔 · 256 미만은 256. 환경변수 → `.env` → `config.json` 의 `runner.max_mb.<유닛>` 순서로 읽고, 바꾸면 다음 검사부터(재시작 불필요). 화면 계산 자식·검색 프로세스는 합치지 않음. pm2 `max_memory_restart` 는 러너 유닛엔 효과가 없어요(러너 프로세스만 잼) |
| `TJ_DEPADDR_PACE` | 0.4 | 거래소 입금주소 자동 수집의 콜 간격(초) |
| `TJ_REBUILD_FX_CALLS` | 3000 | 재계산 도구(`tools/rebuild2.py`)가 과거 환율을 받는 호출 상한 |
| `TJ_TENSOR_KEY` | 없음 | 자리만 — Solana NFT 텐서(Tensor) 바닥가는 아직 구현 전이라 넣어도 쓰지 않아요(NFT 진단 응답에 '키 있음' 여부만 · Solana 바닥가는 매직에덴 공개 API) |
| `TJ_DEMO` · `TJ_DEMO_STATE` · `TJ_PORT` | 없음 | 데모 전용(`bash tools/setup.sh --demo` 가 씀) — 데모 임시 폴더 · 데모 포트 |
| `TJ_ALLOW_NEW_LEDGER` | (러너가 자동) | 원장 파일이 없을 때 새로 만들기 허락 — `src/core.py` 를 러너 없이 직접 띄울 때만 `1` |

시험·진단 전용(운영에선 설정하지 않음): `TJ_HEALTH_NO_NET` · `TJ_KEEP_DIAG` · `TJ_REPLAY_DEBUG` · `TJ_SEARCH_TICK` · `TJ_SEARCH_IDX_DELAY` · `TJ_INT_RESCAN_STABLE_SEC` · `TJ_TEST_*` ·
`TJ_CPU_PLAN`(코어 배분을 하위 프로세스에 물려주는 내부 값).

**`config.json` 키**

| 키 | 기본 | 설명 |
|---|---|---|
| `build_proc` | `auto` | 위 `TJ_BUILD_PROC` 와 같은 값(`auto`·`off`·`fork`) — 환경변수·`.env` 에 없을 때 |
| `backup.keep_db` | 3 | 원장 정기 백업(하루 1번, `state/backups/`) 보관 수(1~30) |
| `backup.offsite` | 꺼짐 | 서버 밖 둘째 백업 — 받을 곳·방식(`push`/`outbox`)·보관 수·속도 상한([백업 · 복구](OPERATIONS.md#백업--복구) · 키 전체 = `python3 tools/offsite_backup.py --help`) |
| `alerts.liq_repeat_min` | 60 | 청산 위험 구간에 머무는 동안 다시 알리는 간격(분 · `0` = 끔 · 5~1440) |
| `runner.max_mb.<유닛>` | web 3072 · 그 밖 0 | 위 `TJ_RUNNER_MAX_MB_<유닛>` 과 같은 값(환경변수·`.env` 에 없을 때) — 예: `"runner": {"max_mb": {"web": 2048}}` |
| `health.t.build_p95_warn_s` | 별도 프로세스 60 · 웹 안 10 | 상태 패널 '웹 빌드 느림' 문턱(최근 빌드 소요 p95, 초) — 값을 넣으면 빌드 방식과 상관없이 그 값 |
| `backfill.auto_rebuild` | 켜짐 | `false` 면 자동 재구축 끔([백필 · 재구축](OPERATIONS.md#백필--재구축--재백필)) |
| `backfill.rebuild_dir` | `~`(홈) | 자동 재구축 임시 사본 위치(원장 약 3배 + 2GB · `state/`·저장소 밖이어야 함) |
| `backup.keep_pre_rebuild` | 1 | 재계산 교체 전 원장 보존본 수(1~5 · 직전 원장 포함) — 옛 키 `backfill.rebuild_keep_recent`·`rebuild_keep_oldest` 를 직접 적어 두면 그대로 따름 |
| `rpc_day_pct` · `rpc_day_limits` | 80 · 기본 표 | 하루·월 한도가 있는 무료 노드를 공표 한도의 몇 % 까지 쓸지 · 노드별 한도 덮어쓰기(`{이름: {...}}` · `false` = 그 노드 장부 끔) |
| `xchain` | 켜짐 | 교차체인 브릿지 짝 맞추기·미등록 경유 지갑 원가 역추적 워커 — `{"trace": false}` 로 끔 · `budget`(후보당 호출, 300) · `per_cycle`(3) · `cycle_calls`(60) · `interval_sec`(60) |
| `flow_trace` | 켜짐 | 보낸 내역 '받은 곳 추적' 워커 — `{"trace": false}` 로 끔 · `cycle_calls`(40) · `interval_sec`(60) · `min_usd`(추적할 최소 금액) |
| `wow.ask_llm` · `wow.ask_llm_daily_max` | 꺼짐 · 40 | 문장 검색을 `claude` CLI 로도 바꿔 봄 · 하루 상한 |
| `rabby.enabled` · `rabby.min_wallet_usd` | 꺼짐 · 1000 | 지갑 포트폴리오 보강(Rabby 공개 API) · 대상 지갑 평가액 기준 — **기본 꺼짐**, 켜면 외부(DeBank 데이터)로 내 EVM 지갑 주소가 나감 |
| `token_discovery.enabled` | 켜짐 | `false` 면 지갑 등록 대사의 옛 보유 토큰 찾기를 끄고 종전 대사로([옛 보유 토큰 찾기](FEATURES.md#옛-보유-토큰-찾기--체인-표)) |
| `negabs_enabled` | 켜짐 | `false` 면 발견 시점 기초 잔고(놓친 옛 보유 토큰이 나가 생긴 원장 마이너스를 직전 블록 잔고로 바로잡기) 끔 |
| `rpc_first` · `chains.<체인>.rpc_first` | 켜짐 | 새로 받는 탐색기 체인(Ethereum·Arbitrum·Polygon 등)의 수집 순서 = 이더스캔(키 있고 그 체인 지원) → 공개 RPC → 블록스카웃은 최후. 체인별로 처음 정한 순서는 `state/evm_route.json` 에 고정(이미 탐색기로 받던 설치본 = 종전 순서) · `false` = 종전(이더스캔 → 블록스카웃 → RPC) |
| `chains.<체인>.rpc_lanes` · `chains.<체인>.rpc_lanes_recent_hours` | 켜짐 · 48 | RPC 로 받는 체인 = 최신 블록 먼저(라이브 차선) + 옛 구간은 뒤 차선 · 라이브 차선이 처음 맡는 최근 시간. `false` = 종전 단일 차선(창 시작부터 순서대로) |
| `chains.<체인>.reorg_check` · `chains.<체인>.reorg_ack` | 켜짐 · 없음 | RPC 로 받는 체인의 깊은 재편(확정 깊이 `conf_depth` 보다 깊은 리오그) 감지 — 사이클마다 블록 해시 2콜로 확인하고, 바뀌면 그 구간을 다시 훑고(새 갈래 거래 반영) 그 체인 잔고 대사를 보류(상태 패널 `evm:reorg:<체인>` 노랑 · 이미 기장한 옛 갈래 거래는 그대로). 확인 뒤 `reorg_ack: <상태 패널의 블록>` + tj-evm 재시작 = 보류 해제 · `reorg_check: false` = 감지 끔 |
| `addr_tier.inflow_sec` | 600 | 쉬는·빈 지갑에 들어온 토큰 확인 간격(초 · Ankr 키 → 공개 노드 getLogs · `0` = 끔 · tj-evm 재시작 때 반영) |
| `bsc.lanes` · `bsc.backfill_days` | 켜짐 · `backfill_months` × 30 | BNB Chain 최신 블록 먼저 + 옛 기록 옆 차선(`false` = 종전 한 차선) · BSC 수집 기간(일 — 따로 정할 때만) |
| `sol.live_first_hours` · `sol.live_first_n` · `sol.old_slice_sec` | 24 · 100 · 60 | Solana 첫 동기화 때 먼저 받는 최근 시간 · 주소당 건수 · 옛 구간을 사이클마다 끊어 받는 초(`live_first_hours`·`old_slice_sec` 가 `0` = 종전 순서) |
| `sol.helius_burst` | 켜짐 | 무료 헬리우스의 옛 기록 버스트(하루 몫의 최대 10배 · 최근 31일 합 80% 안) — `false` 면 끔 |

<!-- gen:cfg -->

**선언표 — `src/cfg_schema.py` 에서 자동 생성(`python3 -I tools/refactor/cfg_doc.py --write` · 이 블록은 손으로 고치지 않음)**

기동 때 한 번 선언과 대조해 다른 점을 로그 경고 한 줄로만 알려요(키 이름·이유만 · 값은 안 찍음). 모르는 키는 지우지 않고 그대로 두고, 형이 달라도 값은 종전처럼 씁니다. `_` 로 시작하거나 `_note` 로 끝나는 키는 메모로 보고 경고하지 않아요. `null` = 비움.

| 키 | 형 | 기본(문서) | 설명 |
|---|---|---|---|
| `addr_ai` | 객체 | 꺼짐 | 주소 AI 판정 워커 하루 상한·간격(enabled · daily_max 등) |
| `addr_tier` | 객체 | inflow_sec 600 · budget_pct 80 | 쉬는·빈 지갑 잔고·유입 확인 간격과 몫(inflow_sec · budget_pct 등) |
| `alerts` | 객체 | liq_repeat_min 60 | 알림 세부(liq_repeat_min · liq_fast 등) |
| `autofix` | 객체 | 꺼짐 | 거래소 칸 자동 처리(창 시작 음수 · 창 이전 행 되받기) — enabled = true 면 core 가 주기마다(1차 배포 = 꺼짐 · 1회 도구 tools/ledger_rowfix.py --kind autofix_ws) |
| `backfill` | 객체 | 없음(코드 기본값) | 과거 기록 채우기·자동 재구축 세부(닫힌 블록 — 아래 하위 키) |
| `backfill_covered_since` | 글자 · 숫자 | 없음 | 이미 채운 것으로 보는 시작일(YYYY-MM-DD 또는 epoch) |
| `backfill_full_history` | 참·거짓 | false | true 면 처음부터 전체 기록(backfill_months 무시 · 기초잔고 대사 꺼짐) |
| `backfill_months` | 숫자 | 모듈마다 다름: 수집기·core·대사 = 0(키 없으면 대사 꺼짐) · 화면·거래소·온보딩 = 5 · config.example = 5 | 처음 불러올 과거 개월 수 |
| `backfill_since` | 글자 · 숫자 | 없음 | 과거 기록 시작일(YYYY-MM-DD 또는 epoch) — backfill_months 보다 앞당길 때 |
| `backup` | 객체 | keep_db 3 | 원장 정기 백업(닫힌 블록 — keep_db · keep_pre_rebuild · offsite) |
| `balance_check` | 객체 | config.example 값 | 온체인 잔고 상시 대조(알림 전용 · 원장 무변) |
| `brokers` | 객체 | 전부 꺼짐 | 증권사 보유 동기화({키: {enabled …}} · 필드 = src/brokers/README.md) |
| `bsc` | 객체 | config.example 값 | BNB Chain 공개 RPC 수집기(logs_rpcs · getlogs_span · poll_sec 등) |
| `build_proc` | 글자 | auto | 화면 계산 프로세스 방식 auto · off · fork(환경변수·.env 에 없을 때) |
| `chain_sweep` | 객체 | config.example 값 | 등록 주소의 다른 체인 활동 훑기(enabled · auto_enable · ignore 등) |
| `chain_wallets` | 목록 | 없음 | 비EVM 체인 지갑 목록(체인 등록부 — 설정 화면이 씀) |
| `chains` | 객체 | config.example 값 | EVM 체인 블록 {체인: {rpcs · blockscout · enabled · discovery …}} — 필수 키 |
| `etherscan` | 객체 | 코드 기본값 | 이더스캔 하루 몫·속도(daily_budget · page_rows 등) |
| `evm_poll_sec` | 숫자 | 45 | EVM 체인 기본 수집 주기(초 · 체인 블록 poll_sec 이 우선) |
| `exchange_addresses` | 목록 | 비어 있음 | 거래소 입출금 주소 목록(이동 판정) |
| `exchanges` | 객체 | 없음 | 거래소별 과거 기록 시작일 {거래소: {backfill_since · covered_since}} |
| `exf` | 객체 | poll_sec 600 | 해외 거래소 수집(poll_sec 기본 600 · leverage · binance_dividends = false 면 바이낸스 배당·에어드랍 지급 내역 안 받음) |
| `first_seen_px` | 참·거짓 | true | 최초 인식 시가 스위치(화면 설정 ui_prefs 가 우선) |
| `flow_trace` | 객체 | 켜짐 | 보낸 내역 받은 곳 추적 워커(trace · cycle_calls · interval_sec · min_usd) |
| `gas_in_cost` | 참·거짓 | true | 가스비를 원가에 넣기 스위치(화면 설정 ui_prefs 가 우선) |
| `health` | 객체 | 켜짐 | 상태 점검(enabled · heartbeat_url · tunnel · t 문턱 등 — 열린 블록) |
| `hyperliquid` | 객체 | config.example 값 | Hyperliquid 현물 수집(spot · spot_exclude) |
| `loan_short` | 목록 | 없음(꺼짐) | 거래소 대출로 빌려 출금한 기간 목록 |
| `native_symbol` | 객체 | 체인 표 기본값 | 체인별 네이티브 심볼(없으면 체인 표 기본값을 채움) |
| `negabs_enabled` | 참·거짓 | true | 발견 시점 기초 잔고 바로잡기 |
| `net_pace` | 객체 | 코드 기본값 | 외부 요청 간격(cooldown_sec · explorer_sec · other_sec) |
| `nft` | 객체 | 켜짐 | NFT 추적(enabled false = 끔) |
| `nonevm` | 객체 | 없음 | 비EVM 체인별 선택 설정 {체인: {…}} — 수집기가 정의 |
| `okx_dex` | 객체 | krw_threshold 1000000 | OKX DEX 시세 기준(krw_threshold) |
| `other_assets` | 객체 | config.example 값 · 확인 없음 | 기타 자산 탭 공개 시세 갱신(quote_every_sec · broker_every_sec · quotes) · 증권사 실험 켜기 확인(brokers.experimental_ack = true 만) |
| `perp_wallets` | 목록 | 없음 | 무기한 선물 DEX 지갑 목록(설정 화면이 씀) |
| `price_guard` | 객체 | config.example 값 | DEX 시세 유동성 가드(min_reserve_usd · dex_max_age_sec) |
| `price_overrides` | 객체 | 없음 | 비상용 수동 가격 고정 |
| `rabby` | 객체 | 꺼짐 | 지갑 포트폴리오 보강(Rabby 공개 API · enabled · min_wallet_usd) |
| `recon_native_stall_hours` | 숫자 | 코드 기본값 | 네이티브 잔고 대사 멈춤 판정 시간 |
| `recon_tokens` | 객체 | 없음 | 잔고 대사에 늘 넣을 토큰 {체인: {CA: [심볼, 소수 자리]}} |
| `review` | 객체 | 평가 0(끔) | AI 리뷰·평가(닫힌 블록 — 아래 하위 키) |
| `rpc_day_limits` | 객체 | 기본 표 | 노드별 하루·월 한도 덮어쓰기({이름: {…}} · false = 그 노드 장부 끔) |
| `rpc_day_pct` | 숫자 | 80 | 무료 노드를 공표 한도의 몇 % 까지 쓸지 |
| `rpc_fallback` | 참·거짓 | true | 탐색기가 막히면 공개 RPC 로 대체(전체 스위치) |
| `rpc_first` | 참·거짓 | true | 새 탐색기 체인의 수집 순서 = RPC 우선(false = 종전 순서) |
| `runner` | 객체 | web 3072 · 그 밖 0 | 유닛 러너(max_mb.<유닛> 메모리 상한) |
| `sol` | 객체 | config.example 값 | Solana 수집(rpc · head_rpc · archive_rpc · helius_* · poll_sec 등) |
| `token_discovery` | 객체 | 켜짐 | 지갑 등록 대사의 옛 보유 토큰 찾기(enabled) |
| `transit` | 객체 | 코드 기본값 | 보낸 뒤 도착 전 '이동 중' 표시 시간(hours · default_hours · own_hours 등) |
| `upbit` | 객체 | poll_sec 60 | 업비트 수집(poll_sec) |
| `wallets` | 목록 | 비어 있음 | 추적할 지갑 목록 — 필수 키 |
| `web` | 객체 | port 8023 · bind loopback | 웹 화면(닫힌 블록 — 아래 하위 키) |
| `wow` | 객체 | ask_llm false · 하루 40 | 물어보는 검색(ask_llm · ask_llm_daily_max) |
| `wrapped_native` | 객체 | 체인 표 기본값 | 체인별 랩드 네이티브 토큰 CA(없으면 체인 표 기본값을 채움) |
| `xchain` | 객체 | 켜짐 | 교차체인 짝 맞추기·경유 지갑 역추적 워커(trace · budget · per_cycle · cycle_calls · interval_sec) |

닫힌 블록 — 아래에 없는 하위 키는 경고(그대로 둠). 다른 블록은 열린 블록이라 하위 키를 보지 않아요.

| 키 | 설명 |
|---|---|
| `backfill.auto_rebuild` | false = 자동 재구축 끔 |
| `backfill.bf_target_sec` | 노드 고르기 목표 시간 |
| `backfill.engine` | 과거 기록 엔진 선택 |
| `backfill.evm_cycle_budget_sec` | EVM 과거 기록 한 바퀴 시간 몫 |
| `backfill.hosts` | 노드 호스트 덮어쓰기 |
| `backfill.node_select` | false = 노드 고르기 끔(관측만) |
| `backfill.node_slo_sec` | 노드별 응답 목표 덮어쓰기 |
| `backfill.px_prefetch` | false = 과거 시세 미리 받기 끔 |
| `backfill.quota_open_sec` | 하루 몫 열림 대기 |
| `backfill.rebuild_allow_locked` | false = 잠긴 원장 재구축 허용 안 함 |
| `backfill.rebuild_check_sec` | 재구축 조건 확인 간격 |
| `backfill.rebuild_dir` | 재구축 임시 사본 위치(기본 홈) |
| `backfill.rebuild_keep_oldest` | 옛 키 — 재계산 전 원장 보존(가장 옛 것) |
| `backfill.rebuild_keep_recent` | 옛 키 — 재계산 전 원장 보존(최근 것) |
| `backfill.rebuild_min_gap_sec` | 재구축 최소 간격 |
| `backfill.rebuild_pnl_gate` | false = 재구축 손익 게이트 끔 |
| `backfill.rebuild_pnl_tol_pct` | 재구축 손익 허용 차(%) |
| `backfill.rebuild_pnl_tol_usd` | 재구축 손익 허용 차(USD) |
| `backfill.rebuild_retry_sec` | 재구축 실패 뒤 다시 시도 간격 |
| `backfill.rebuild_timeout_sec` | 재구축 시간 한도 |
| `backfill.stall_sec` | 과거 기록 멈춤 판정 |
| `backfill.verify_timeout_sec` | 재구축 검증 시간 한도 |
| `backup.keep_db` | 원장 정기 백업 보관 수(1~30) |
| `backup.keep_pre_rebuild` | 재계산 교체 전 원장 보존본 수(1~5) |
| `backup.offsite` | 서버 밖 둘째 백업(안쪽 칸은 tools/offsite_backup.py --help · 열린 칸) |
| `review.buy_eval_daily_max` | AI 매수 평가 하루 상한(0 = 끔) |
| `review.chart_prewarm_per_day` | 영수증 차트 봉 미리 받기 하루 상한(0 = 끔) |
| `review.coach_role` | AI 리뷰 첫 줄 트레이더 설명 |
| `review.known_patterns` | 지적하지 않을 내 운용 패턴 문장 목록 |
| `review.sell_eval_daily_max` | AI 매도 평가 하루 상한(0 = 끔) |
| `web.allowed_hosts` | 리버스 프록시·터널 도메인(Host 허용) |
| `web.behind_proxy` | true = 모든 요청을 프록시 경유로 취급(로그인 쿠키 Secure 기본) |
| `web.bind` | loopback(권장) · tailscale |
| `web.login` | 웹 로그인(enabled · session_days · idle_days · secure_cookie · allow_lan_without_password) |
| `web.max_conn` | 동시 연결 상한 |
| `web.max_conn_per_ip` | 주소 하나당 동시 연결 상한 |
| `web.port` | 화면 포트 |
| `web.public_url` | 알림 '보기' 링크 주소 |
| `web.setup_allow_lan` | true = 사설망에서도 설정 바꾸기 |
| `web.setup_allow_proxy` | true = 프록시·터널에서도 설정 바꾸기 |
| `web.token_logos` | 호환으로 남은 키(효과 없음) |

실행 중 붙는 키(설정에 쓰지 않음): `_auto_pairs` · `_disabled_chains` · `_disabled_wallets`

<!-- /gen:cfg -->
