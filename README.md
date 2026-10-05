# tj-bot · 온체인 매매일지

내 지갑 주소와 거래소 **조회 전용** API 키만으로 코인 매매일지를 자동으로 만드는 셀프 호스팅 봇입니다.
온체인 스왑·전송·LP 와 거래소 입출금·체결을 하나의 원장(SQLite)으로 이어 붙여
**원가·실현/미실현 손익·일별 기록·신고용 명세**를 보여 줍니다.
모든 데이터는 내 컴퓨터(`state/`)에만 저장되고, 화면은 기본적으로 이 컴퓨터(127.0.0.1)에서만 열립니다.

*English summary is at the bottom — [English](#english).*

![대시보드 — 총자산·전일 대비 분해·총자산 곡선 (금액 랜덤값 모드)](docs/screenshots/01_dashboard_top.png)

---

## 처음 시작하면 이것부터

| 순서 | 할 일 | 명령·위치 |
|---|---|---|
| 1 | **Python 3.9+** 가 있는 macOS/Linux 준비 (pm2 는 선택) | `python3 --version` |
| 2 | 받고 설치 점검 — 아무것도 설치하지 않습니다 | `git clone <이 저장소 주소> tj-bot` → `cd tj-bot` → `bash tools/setup.sh` |
| 3 | 키 준비 — Solana 지갑이 있으면 Helius 무료 키만 필수, 나머지는 선택 | [키 표](#3-키-준비--env-와-configjson) · 거래소 키는 **조회 권한만** |
| 4 | 실행 | `pm2 start ecosystem.config.js` (pm2 없이: [아래](#4-실행--설정-마법사)) |
| 5 | 화면 열기 → 설정 마법사에서 지갑·키·거래소·텔레그램 | **http://127.0.0.1:8023/** |
| 6 | 첫 백필 기다리기 — 보통 수십 분, 많으면 몇 시간 | 화면 위 **상태 패널** |
| 7 | 남은 '원가 미확인'만 정리 | **미매칭** 탭 |

먼저 구경만 하려면 `bash tools/setup.sh --demo` — 합성 데이터로 화면만 띄우고 아무것도 저장하지 않습니다.

> **업데이트 안내 — 이미 쓰던 설치라면:** 이번 판부터 `config.json` 에 `web.login` 이 **없어도 로그인이 켜집니다.**
> 업데이트 뒤 `pm2 restart tj-web` 하고 **이 컴퓨터에서** http://127.0.0.1:8023/ 을 열어 비밀번호부터 만드세요
> (그 전까지 다른 기기·프록시에서는 401 — 첫 비밀번호는 이 컴퓨터에서만 만들 수 있습니다). 같은 컴퓨터의 tj-review 는 내부 토큰으로 그대로 동작합니다.
> 계속 끄려면 `"web": {"login": {"enabled": false}}` 를 적고 재시작하세요(끄면 리버스 프록시·터널로 온 요청은 전부 거부됩니다).

---

## 화면 미리보기

> 모든 금액은 금액 랜덤값 모드(실제와 다른 배수)로 찍었고, 주소·별칭·포지션 번호는 가짜로 바꿨어요.

### 새로 생긴 것 — 내 매매를 다르게 보는 화면

| | |
|---|---|
| ![타임머신 — 곡선을 끌면 그날의 내 지갑(코인·보관처별 비중)과 '지금 그대로였다면'](docs/screenshots/30_wow_timemachine.png) | ![자금 흐름 지도 — 넣은 돈 → 거래소 → 지갑 → 지금 있는 곳(띠를 누르면 그 길로 간 전송 목록)](docs/screenshots/31_wow_flows.png) |
| ![팔기 전 미리보기 — 팔 양을 움직이면 예상 실현손익·올해 누적 양도차익(주문은 넣지 않아요)](docs/screenshots/34_wow_sell_preview.png) | ![올해 결산 카드 — 실현·가장 많이 거래한 코인·오래 버틴 코인·수익 난 날, 비율만 보기·이미지 저장](docs/screenshots/32_wow_yearend.png) |
| ![계획 지키기 점수 — 목표가·손절선(없으면 기본 규칙) 대비 판 매도를 판정, 월별 준수율](docs/screenshots/33_wow_planscore.png) | ![매매 습관 — 요일×시간대별 이익 난 매도 비율·보유 기간별 수익률·판 다음 날 더 오른 비율](docs/screenshots/37_journal_habits.png) |
| ![지난 1년 하루 실현손익 잔디 — 가장 길게 이긴 흐름·조심할 요일](docs/screenshots/36_daily_heatmap.png) | ![전체 검색(⌘K · /) — 코인·주소·해시·날짜·금액, 필터 문법, '9월에 Base 에서 손해 본 거래' 같은 문장도](docs/screenshots/35_search_palette.png) |

- 대시보드 총자산 곡선에 **'BTC 만 들고 있었다면' · '안 팔았다면'** 비교선을 겹쳐 볼 수 있어요(입출금은 빼고 같은 날 같은 돈으로 계산).
- 문장 검색은 기본으로 **규칙 변환만** 씁니다(외부 호출 없음). `config.json` 의 `"wow": {"ask_llm": true}` 를 켜면 내 컴퓨터의 `claude` CLI 로도 바꿔 봅니다.
- 가리기·랜덤값 모드에서는 이 화면들도 금액을 가리고, 검색어 속 금액은 서버로 보내지 않아요.

### 대시보드

![대시보드 아래쪽 — 보유 코인 표(오늘 변동·7일 추이)](docs/screenshots/02_dashboard_below.png)

![보유 코인 한 줄 펼침 — 보관 위치별 수량·원가](docs/screenshots/03_holding_row_expanded.png)

| 총자산 곡선 1년 | 총자산 곡선 전체 |
|---|---|
| ![총자산 곡선 — 1년](docs/screenshots/15_long_curve_1y.png) | ![총자산 곡선 — 전체 기간](docs/screenshots/15_long_curve_all.png) |

### 매매일지 · 차익 영수증

![매매일지 — 코인별 사이클(투입 → 매도)](docs/screenshots/04_journal_cycles.png)

![차익 영수증 — 매수·매도 한 차트, 코드 점수, AI 평가 상자](docs/screenshots/05_receipt_drawer.png)

![선물 상세 — 포지션·펀딩·수수료](docs/screenshots/16_futures_drawer.png)

### 일별 기록 · 명세

![일별 기록 — 달력과 그날 카드(무엇이 움직였나·시세 코인별 분해·30분 체결 막대·매매 근거 메모)](docs/screenshots/06_daily_day_card.png)

![일별 기록 — 달력 아래 'M월 한눈에'(한 달 자산 변동 분해·실현 상위/하위 5)](docs/screenshots/06b_daily_month_glance.png)

![일별 기록 — 그날의 기록 표](docs/screenshots/07_daily_records_table.png)

![최근 30일 마감 — 날마다 실현·USDT 종가·김프·총자산·AI 리뷰 표시](docs/screenshots/07b_daily_recent_30d.png)

| 양도차익 명세 | 가스·수수료 |
|---|---|
| ![양도차익 명세(신고용 계산 보조)](docs/screenshots/08_tax_statement.png) | ![가스·수수료](docs/screenshots/09_gas_fees.png) |

### 보낸 내역 · 미매칭 · 기타 자산

![보낸 내역 — 전송 중·브릿지 매칭·외부 전송 추적](docs/screenshots/10_outflows.png)

![미매칭 — 원가 미확인 유입·스팸 의심](docs/screenshots/11_unmatched.png)

![기타 자산 — 부동산·주식·금·현금·부채(증권사 연결은 미검증 · 이 캡처는 자산 이름을 '종류 A' 로 바꿈)](docs/screenshots/12_other_assets.png)

![기타 자산 › NFT — 추적 중·후보·스팸 접힘 (이 캡처는 컬렉션 이름·바닥가도 가림)](docs/screenshots/12b_other_assets_nft.png)

### 설정

![설정 — 상태 패널·수집 한계·표시](docs/screenshots/13_settings_top.png)

![상태 패널 — 수집기·외부 API·잔고 대사·백업 상태](docs/screenshots/18_status_panel.png)

| 연결·키 — 지갑 | 연결·키 — 탐색기 키 | 연결·키 — 텔레그램 |
|---|---|---|
| ![지갑 — 주소 여러 개 한 번에 추가](docs/screenshots/14_settings_keys_wallets.png) | ![탐색기 키 — Helius·Etherscan·코인게코 데모·오픈시(값은 가림)](docs/screenshots/14_settings_keys_explorers.png) | ![텔레그램 연결](docs/screenshots/14_settings_keys_telegram.png) |

![텔레그램 알림 — 즉시 · 하루 요약 · 시스템 3단, 추천값, 조용한 시간](docs/screenshots/17_settings_alerts.png)

### 모바일

| 대시보드 | 보유 코인 | 일별 기록 |
|---|---|---|
| ![모바일 대시보드](docs/screenshots/21_mobile_dashboard.png) | ![모바일 보유 코인](docs/screenshots/22_mobile_holdings.png) | ![모바일 일별 기록](docs/screenshots/23_mobile_daily.png) |

| 기타 자산 | 매매일지(아래 탭 막대) | 알림 설정 |
|---|---|---|
| ![모바일 기타 자산](docs/screenshots/24_mobile_other_assets.png) | ![모바일 매매일지와 아래 탭 막대](docs/screenshots/25_mobile_tabbar_journal.png) | ![모바일 알림 설정](docs/screenshots/26_mobile_settings_alerts.png) |

| 일별 — M월 한눈에 | 기타 자산 › NFT |
|---|---|
| ![모바일 'M월 한눈에'](docs/screenshots/27_mobile_month_glance.png) | ![모바일 NFT(컬렉션 이름·바닥가 가림)](docs/screenshots/28_mobile_nft.png) |

---

## 설치 자세히

### 1) 준비물

| 항목 | 필수? | 설명 |
|---|---|---|
| macOS 또는 Linux | 필수 | Windows 는 시험하지 않았습니다(쓰려면 WSL2 의 리눅스에서). 24시간 켜 둘 수 있는 컴퓨터·서버가 좋습니다 |
| **Python 3.9 이상** | 필수 | **표준 라이브러리만** 씁니다 — `pip install` 할 것이 없습니다. sqlite3 3.24+·ssl 모듈 포함 파이썬(맥 기본 `python3`·우분투 22.04+ 기본이면 됨) |
| Node.js + pm2 | 선택(권장) | 재부팅·오류 때 자동으로 다시 켜 줍니다. `npm install -g pm2`. Node 는 pm2 를 쓸 때만 필요합니다 |
| `claude` CLI | 선택 | AI 리뷰·AI 매수/매도 평가를 켤 때만(기본 꺼짐). 내 컴퓨터에 로그인된 Claude Code CLI 를 그대로 씁니다 |
| 고정 IP | 거래소 연결 때 권장 | 거래소 키에 IP 화이트리스트를 걸기 때문에, IP 가 자주 바뀌는 노트북은 밖에서 거래소 동기화가 거부될 수 있습니다 |

### 2) 받기 + 설치 점검

```bash
git clone <이 저장소 주소> tj-bot
cd tj-bot
bash tools/setup.sh
```

`tools/setup.sh` 는 **아무것도 설치하지 않습니다.** 파이썬 버전·sqlite3·ssl 을 점검하고,
`config.example.json` → `config.json`, `.env.example` → `.env`(권한 600)를 복사하고(이미 있으면 그대로 둠),
`state/`(권한 700)를 만든 뒤 다음에 칠 명령을 알려 줍니다. 여러 번 실행해도 안전합니다.

### 3) 키 준비 — `.env` 와 `config.json`

**보통은 파일을 직접 고칠 필요가 없습니다.** 웹 설정 마법사가 `.env`·`config.json` 을 대신 써 줍니다. 미리 키만 준비해 두세요.

| 키(`.env` 이름) | 필수? | 어디서 받나 | 언제 필요한가 |
|---|---|---|---|
| `TJ_HELIUS_KEY` | Solana 지갑이 있으면 **필수** | https://dashboard.helius.dev (무료) | Solana 지갑 수집 |
| `TJ_ETHERSCAN_KEY` | 선택 | https://etherscan.io/myapikey (무료) | Ethereum·Arbitrum·Polygon 과거 거래 백필이 수십 배 빨라짐. 없어도 동작 |
| `TJ_COINGECKO_KEY` | 선택 | https://www.coingecko.com/en/developers/dashboard → **Demo** 키(무료) 또는 유료 **Pro** 키 — 자동 판별 | 키 하나를 코인게코 시세(거래소 값이 없는 코인)·DEX 토큰 시세·원가·차트·NFT 바닥가가 같이 써서 빨라짐. 몫이 모자라거나 실패하면 그 콜만 무키로. 없으면 전부 무키 공용 한도라 느리고 NFT 바닥가는 처음 몇 시간 걸릴 수 있음. 프로 키는 플랜 한도의 10%(기본 · 25·50·80% 선택)만 씀 |
| `TJ_OPENSEA_KEY` | 선택 | https://docs.opensea.io/reference/api-keys (무료 신청) | 넣으면 EVM NFT 바닥가를 **오픈시에서 먼저** 받아 작은 컬렉션까지 원활하게 추적(없거나 실패하면 코인게코) |
| `UPBIT_ACCESS` · `UPBIT_SECRET` | 선택 | 업비트 › 마이페이지 › Open API 관리 | 업비트 입출금·체결·잔고 |
| `TJ_BITHUMB_KEY` · `TJ_BITHUMB_SECRET` | 선택 | 빗썸 › 마이페이지 › API 관리 | 빗썸 |
| `TJ_BINANCE_KEY` · `TJ_BINANCE_SECRET` | 선택 | 바이낸스 › API Management | 바이낸스 |
| `TJ_BYBIT_KEY` · `TJ_BYBIT_SECRET` | 선택 | 바이빗 › API | 바이빗 |
| `TJ_OKX_KEY` · `TJ_OKX_SECRET` · `TJ_OKX_PASSPHRASE` | 선택 | OKX › API keys | OKX |
| `TJ_KUCOIN_KEY` · `TJ_KUCOIN_SECRET` · `TJ_KUCOIN_PASSPHRASE` | 선택 | 쿠코인 › API Management | 쿠코인 |
| `TJ_GATE_KEY` · `TJ_GATE_SECRET` | 선택 | 게이트 › API Keys | 게이트 |
| `TJ_TG_TOKEN` · `TJ_TG_CHAT` | 선택 | 텔레그램 @BotFather 로 봇 만들기(마법사가 채팅 ID 를 자동으로 채움) | 텔레그램 알림 |

키마다 받는 법·어디에 쓰는지·없으면 어떻게 되는지는 [docs/API_KEYS.md](docs/API_KEYS.md) 에 정리돼 있습니다.

> **거래소 키는 반드시 '조회(읽기)' 권한만 켜고, IP 화이트리스트를 거세요.**
> 거래·출금·이체 권한은 절대 켜지 마세요. 바이낸스·바이빗·OKX 는 저장할 때 권한을 확인해 거래·출금·이체가 켜진 키를 거부하고,
> 권한을 API 로 확인할 수 없는 업비트·빗썸·쿠코인·게이트는 '조회 권한만 켰음' 확인을 눌러야 저장됩니다.
> 개인 키·시드 문구는 어디에도 필요 없습니다 — 이 봇은 조회만 합니다.

RPC 키는 필요 없습니다. `config.example.json` 은 공개 RPC·무료 탐색기만 씁니다(무료 한도를 지키도록 천천히 받습니다).
더 빠른 유료 RPC 가 있으면 `config.json` 의 `chains.<체인>`·`bsc`·`sol` RPC 목록에 넣을 수 있습니다(키 박힌 URL 은 남에게 보여 주지 마세요).

`config.json` 에서 알아 두면 좋은 키:

| 키 | 기본 | 설명 |
|---|---|---|
| `wallets` | 비어 있음 | 추적할 지갑 — 비워 두고 웹 화면에서 추가하면 됩니다 |
| `backfill_months` / `backfill_since` | 5개월 / 없음 | 처음 불러올 과거 기간 / 시작일(YYYY-MM-DD)로 앞당기기 |
| `web.port` · `web.bind` | 8023 · `loopback` | 화면 포트 / `loopback`(이 컴퓨터만, 권장) 또는 `tailscale`(테일넷 IP 추가) |
| `web.login.enabled` · `session_days` · `idle_days` | 켜짐 · 30 · 7 | 웹 비밀번호 로그인. **키가 없어도 켜짐** — 끄기는 `false` 를 적을 때만. 바꾸면 `pm2 restart tj-web` |
| `web.login.secure_cookie` | false | true 면 로그인 쿠키에 항상 `Secure`(HTTPS 로만 열 때). HTTPS 리버스 프록시가 `X-Forwarded-Proto: https` 를 붙이면 꺼 둬도 자동으로 붙음 |
| `web.allowed_hosts` · `web.public_url` | 비어 있음 | 리버스 프록시·터널 도메인(Host 허용) / 텔레그램 알림 '보기' 링크 주소(`https://도메인`만, 비우면 링크 없음) — [아래](#6-화면-열기--다른-기기에서-보기) |
| `web.behind_proxy` | 없음(false) | true 면 모든 요청을 리버스 프록시 경유로 취급(헤더를 안 붙이는 프록시 뒤 · 첫 비밀번호는 `tools/reset_password.py`) |
| `web.setup_allow_lan` | 없음(false) | true 면 일반 사설망(192.168.x 등)에서도 설정 API 허용 — 기본은 루프백·테일넷만 |
| `review.sell_eval_daily_max` · `buy_eval_daily_max` | 0(끔) | AI 매도·매수 평가 하루 상한. 켜려면 예: 20 (`claude` CLI 필요) |
| `review.coach_role` · `review.known_patterns` | 없음 | AI 일간·주간 리뷰 맞춤 — 첫 줄 트레이더 설명(예: "단타 위주 트레이더") / 지적하지 않을 내 운용 패턴 문장 목록(10개·각 200자) |
| `recon_tokens` | 없음 | 잔고 대사에 늘 넣을 토큰 `{"체인": {"0x토큰 CA": ["심볼", 소수 자리]}}` — 자동으로 켜진 추가 체인에 합쳐짐 |
| `health.tunnel` | 없음(꺼짐) | 터널 유닛 감시 `{"unit": "pm2 이름", "ready_url": "http://127.0.0.1:<메트릭 포트>/ready"}` — 터널 연결 0 이 5분 이어지면 알림(클라우드플레어 터널 메트릭의 `/ready` 등) |
| `other_assets` · `brokers` | 증권사 전부 꺼짐 | 기타 자산 탭의 공개 시세 갱신 주기 / 증권사 보유 동기화(**미검증**, 아래 '기타 자산' 참고) |
| `chains.<체인>.enabled` | 체인마다 | 쓰지 않는 체인을 통째로 끄기 |
| `price_overrides` | 없음 | 비상용 수동 가격 고정 |

텔레그램 알림 종류·조용한 시간은 `config.json` 이 아니라 화면 **설정 › 알림 (텔레그램)** 에서 정합니다(`state/ui_prefs.json` 에 저장).

### 4) 실행 · 설정 마법사

```bash
pm2 start ecosystem.config.js     # 전체 시작 — 지갑·키가 없으면 해당 유닛은 조용히 기다립니다
pm2 save                          # (선택) 재부팅 후 자동 시작: 'pm2 startup' 이 알려 주는 명령도 실행
```

브라우저에서 **http://127.0.0.1:8023/** 을 열면 설정 마법사가 **지갑 → 탐색기 키 → 거래소 → 텔레그램 → 표시** 순서로 안내합니다.
지갑은 [여러 개를 한 번에](#지갑-주소-여러-개-한-번에) 넣을 수 있고, EVM 주소는 추적할 체인을 골라(칩) 등록합니다. 거래소 키는 저장 즉시 연결을 시험합니다.
나중에 바꿀 때는 화면의 **설정** 탭에서 같은 단계를 다시 열 수 있습니다(바꾸면 해당 유닛만 30초 안에 스스로 다시 켜짐).

pm2 없이 쓰려면 터미널 여러 개에서 각각 켜 두세요:

```bash
python3 src/unit_runner.py web     # 화면 (필수)
python3 src/unit_runner.py core    # 원장 쓰기 (필수)
python3 src/unit_runner.py evm     # EVM 지갑 · sol · bsc 도 같은 식
python3 src/upbit_link.py          # (선택) 업비트 · src/ex_foreign.py = 해외 거래소 · src/alert_bot.py = 텔레그램
```

### 5) 첫 실행 — 얼마나 걸리고 어디서 보나

- 처음엔 지갑마다 **최근 5개월**을 거슬러 받습니다(백필). 그동안 화면 숫자는 계속 바뀝니다.
- 걸리는 시간(이 저장소의 실측 모델 `seed/coverage/speed_model.json` 기준, 무료 한도):
  - 이더스캔 계열 체인: 지갑당 수 초~수십 초 · Base·Optimism 등 블록스카웃 계열: 지갑당 수십 초~4분
  - BNB Chain: 지갑 수와 무관하게 5개월 ≈ 20~25분 · Solana: 거래 1건 ≈ 0.4초(1,000건 ≈ 7분)
  - 거래소: 업비트 과거 체결은 1분에 7일 창씩 이어 받아 몇 달이면 수십 분 — 해외 거래소도 비슷
  - 지갑·거래가 많으면 **몇 시간** 걸릴 수 있습니다. 그 뒤로는 증분만 받아 1~몇 분 안에 따라갑니다.
- 어디서 보나:
  - 화면 위의 **상태 표시줄 → 상태 패널 열기** — 수집기별 '과거 기록 수집 중'·지연·오류
  - **설정 › 수집 한계** — 거래소·체인별로 어디까지 받았고 무엇을 못 받는지([docs/COLLECTION_LIMITS.md](docs/COLLECTION_LIMITS.md) 와 같은 내용)
  - 로그: `pm2 logs tj-core` · `pm2 logs tj-evm` 등
- 백필이 끝나기 전에는 '원가 미확인'·잔고 차이가 많이 보이는 게 정상입니다. 끝난 뒤에도 남는 것만 **미매칭** 탭에서 처리하세요.
- 텔레그램을 연결했다면 처음 7일은 동기화·대사·백필 알림이 많이 옵니다(추천값 기준 — 7일 뒤 자동으로 줄어듦).

### 6) 화면 열기 · 다른 기기에서 보기

- 이 컴퓨터에서: **http://127.0.0.1:8023/** (포트는 `config.json` 의 `web.port`)
- **로그인(기본 켜짐)** — 처음 한 번 **이 컴퓨터에서** http://127.0.0.1:8023/ 을 열면 **비밀번호 만들기**(10자 이상)부터 나옵니다.
  그 뒤로는 어느 기기에서 열든 비밀번호를 묻습니다. 한 번 로그인하면 그 기기에서 30일 유지되고, 7일 동안 안 쓰면 다시 묻습니다
  (`web.login.session_days` · `idle_days`).
  - 비밀번호 바꾸기 · 모든 기기에서 로그아웃 · 로그아웃 = 화면 **설정 › 로그인**. 10분에 5번 틀리면 15분 잠깁니다(반복되면 두 배, 최대 24시간).
  - 비밀번호를 잊었으면 이 컴퓨터에서 `python3 tools/reset_password.py`(지운 뒤 /login 에서 새로 만들기) 또는
    `python3 tools/reset_password.py --set`(터미널에서 바로 입력). 실행 중인 tj-web 이 바로 알아챕니다.
  - 끄기 = `config.json` 의 `"web": {"login": {"enabled": false}}` → `pm2 restart tj-web`(켜기·끄기·기간 변경은 재시작 때 반영).
    끄면 이 주소에 닿는 누구나 화면을 볼 수 있습니다.
  - 같은 컴퓨터의 유닛(tj-review)은 내부 토큰(`state/auth_internal_token`, tj-web 이 켜질 때마다 새로 만듦)으로 자동 통과합니다.
    직접 조회할 땐 토큰이 명령줄(프로세스 목록)에 남지 않게 헤더를 파일 꼴로 넘기세요:
    `curl -H @<(printf 'X-TJ-Internal: %s\n' "$(cat state/auth_internal_token)") http://127.0.0.1:8023/api/state`
    (루프백 직접 GET 에서만 통하고, 프록시 헤더가 붙으면 거부됩니다).
- **HTTPS 리버스 프록시·터널(예: 클라우드플레어 터널)로 밖에서 열 때** — 로그인이 켜져 있어야 합니다(꺼져 있으면 프록시 헤더가 붙은 요청은 전부 403).
  - 프록시는 `http://127.0.0.1:8023` 으로 보내고 `Host` 를 그대로 넘기며 `X-Forwarded-For`(실제 접속 IP를 끝에)·`X-Forwarded-Proto: https` 를 붙여야 합니다
    (클라우드플레어 터널은 기본으로 그렇게 합니다). 그 도메인을 `web.allowed_hosts` 에, 알림 링크를 원하면 `"public_url": "https://도메인"` 을 넣으세요.
  - 프록시를 거친 요청은: 로그인 필수 · 첫 비밀번호 만들기 불가 · 내부 토큰 불가 · 전체 로그인 시도 상한 적용 · 쿠키 `Secure` · HSTS ·
    캐시 금지(`Cache-Control: private, no-store` · `Cloudflare-CDN-Cache-Control: no-store`). 로그인 시도 제한은 `X-Forwarded-For` 마지막 값(실제 접속 IP) 기준입니다.
  - **nginx 예시**(기본 `proxy_pass` 만으로는 헤더가 안 붙습니다 — 아래 네 줄을 꼭 넣으세요):
    ```nginx
    location / {
      proxy_pass http://127.0.0.1:8023;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
    }
    ```
    헤더를 붙일 수 없는 프록시를 쓰거나 확실히 하고 싶으면 `config.json` 에 `"web": {"behind_proxy": true}` — 모든 요청을 프록시 경유로 봅니다
    (그때 첫 비밀번호는 이 컴퓨터에서 `python3 tools/reset_password.py` 로 만듭니다 · 내부 토큰 조회는 안 됩니다).
  - **`ssh -R`·`socat`·`tailscale serve --tcp`·`ngrok tcp` 같은 순수 TCP 중계로 열지 마세요.** 헤더를 붙이지 않아 이 컴퓨터에서 직접 연 것처럼
    보입니다(첫 비밀번호 만들기·내부 토큰·시도 상한 예외가 밖에 열림). HTTP 를 이해하는 프록시(헤더를 붙이는 것)만 쓰세요.
  - 로그인 화면은 `http://` 로 열렸는데 이 컴퓨터·테일넷 주소가 아니면 '암호화되지 않은 주소' 경고를 띄웁니다(비밀번호·쿠키가 그대로 오감).
- 휴대폰 등 내 다른 기기에서 보려면 [Tailscale](https://tailscale.com) 을 켜고 `config.json` 에 `"web": {"bind": "tailscale"}` →
  `pm2 restart tj-web`. 테일넷 안의 내 기기에서만 열립니다(테일스케일이 암호화). 공인 IP·0.0.0.0 바인딩은 코드에서 거부합니다.
  사설 IP(192.168.x 등)를 직접 적으면 같은 와이파이에서 HTTP(암호화 없음)로 비밀번호·쿠키가 오가니 권하지 않습니다(tj-web 이 시작할 때 경고).
- 키 입력·지갑·텔레그램 같은 **설정 API(설정 › 연결·키)는 이 컴퓨터(루프백)와 테일넷에서만** 열립니다(같은 컴퓨터의 리버스 프록시·터널을 거친 요청은
  로그인한 뒤에만 여기 닿으므로 설정도 열립니다). 사설 IP 로 바인딩해도
  같은 와이파이의 다른 기기는 설정을 바꿀 수 없습니다. 꼭 필요할 때만 `config.json` 의 `"web": {"setup_allow_lan": true}` 로 풀 수 있습니다(권장하지 않음).

### 7) 문제 해결 — 자주 묻는 5가지

1. **화면이 안 열려요** — `pm2 ls` 로 `tj-web` 이 online 인지, `pm2 logs tj-web --lines 50` 에 오류가 있는지 보세요.
   8023 포트를 다른 프로그램이 쓰고 있으면 `config.json` 의 `web.port` 를 바꾸고 `pm2 restart tj-web`.
2. **거래소 키 저장이 거부돼요 / 동기화가 멈췄어요** — 키에 거래·출금·이체 권한이 켜져 있으면 저장을 거부합니다(조회만 켜서 새로 발급).
   IP 화이트리스트에 지금 컴퓨터의 공인 IP 가 들어 있는지 확인하세요(노트북을 들고 나가면 IP 가 바뀌어 거부됩니다).
3. **Solana 지갑이 안 잡혀요** — `TJ_HELIUS_KEY` 가 비어 있으면 Solana 수집기는 기다리기만 합니다. 설정 › 연결·키에서 넣으세요.
4. **원가 미확인·잔고 차이가 많아요** — 백필 중이면 정상입니다. 끝난 뒤 남은 것은 **미매칭** 탭에서 '원가 적용'·'당시 시세로 추정'·'손익 0 처리'를 쓰세요.
   거래소 API 가 옛 기록을 주지 않는 경우(예: OKX 체결 약 4개월, 바이빗 2년)는 [docs/COLLECTION_LIMITS.md](docs/COLLECTION_LIMITS.md) 에 정리돼 있습니다.
5. **'출처(Origin) 확인 실패'·'CSRF 토큰 불일치'(403)** — 쓰기 요청은 같은 화면에서만 받습니다. 페이지를 새로고침하세요.
   `curl` 같은 외부 도구로 설정을 바꾸는 것은 의도적으로 막혀 있습니다.

---

## 지갑 주소 여러 개 한 번에

- 설정 마법사의 지갑 단계(또는 **설정 › 연결·키 › 지갑**)의 주소 칸에 **쉼표·줄바꿈(Enter)·공백·세미콜론**으로 나눠 여러 주소를 붙여 넣으면 한 번에 추가됩니다.
- EVM(0x…, EVM·BSC 공용)과 Solana 주소를 섞어도 됩니다. 붙여 넣으면 저장 전에 주소마다 형식 확인(EVM 체크섬 포함)·중복을 보여 줍니다.
- 한 번에 최대 50개. 더 많으면 나눠서 넣으세요.
- 이름(별칭)·메모는 추가한 뒤 지갑 목록에서 하나씩 붙입니다.
- **개인 키·시드 문구는 절대 넣지 마세요** — 주소만 필요합니다. 줄로 나뉜 키 조각처럼 보이는 입력은 주소로 저장하지 않습니다.

## 텔레그램 알림 설정

텔레그램을 연결하면(설정 마법사 › 텔레그램) **설정 › 알림** 에서 알림을 **세 등급**으로 나눠 받습니다. 꼭 필요한 것만 소리가 나요.

| 등급 | 어떻게 오나 | 종류 |
|---|---|---|
| 🔴 **즉시** | 지금 폰을 보고 해야 할 일 · 소리 · 조용한 시간에도 바로 | 봇이 멈춤(몇 분 이상 · 끌 수 없음) · 목표가·손절 도달 · 내가 안 한 큰 출금 · 스테이블 가격 이탈 · 선물 청산가 근접 · 보유 코인 급등락(켜도 밤엔 모았다가) |
| 📋 **하루 요약** | 정한 시각(추천 09:00)에 소리 없이 한 통 · 작은 차트 | 오늘 손익 · 잔고 맞추기 결과 · 처음 보는 토큰 · LP 범위 이탈 · AI 복기 도착 · 기타 자산·증권사 · 안 풀린 봇 문제 · 그 밖의 소식 |
| **시스템** | 텔레그램으로 보내지 않음(상태 패널·설정의 '지난 7일'에만) | 거래 분류·동기화 · 과거 기록 가져오기·다시 계산 |

- **추천값 3종** — 버튼 하나로 채웁니다. 손으로 바꾸면 '직접 설정'으로 표시됩니다.
  - **추천**(새 설치 기본): 즉시 5가지(급등락 제외) + 하루 요약 한 통, 밤 1시~8시는 모아서
  - **최소**: 즉시 5가지만(요약 없음)
  - **전부**: 급등락까지 모두
- 같은 문제는 **두 번만** 알립니다 — 생겼을 때와 풀렸을 때(심해지면 한 번 더). 풀림은 ✅ 로 시작하고 소리가 나지 않아요.
- **조용한 시간** — 정한 시간 동안 온 알림은 모았다가 끝날 때 한 통으로 보냅니다(즉시 등급은 그대로).
- 급등락·큰 출금·디페그·청산 근접·손익 기준 시각·요약 시각은 기준값을 바꿀 수 있어요. **테스트** 버튼으로 그 종류의 예시를 받아 볼 수 있습니다(예시 값은 가짜).
- 가짜 전송·주소 오염 같은 확실한 스캠은 설정과 상관없이 항상 걸러 냅니다. 끈 동안 생긴 알림은 보내지 않을 뿐 기록은 남습니다.

## 금액 랜덤값 모드

화면을 남에게 보여 주거나 캡처할 때 실제 금액 대신 그럴듯한 가짜 숫자를 보여 주는 모드입니다(위 스크린샷이 전부 이 모드).

- 켜기: 화면 위 **주사위 버튼** 또는 **설정 › 표시 › 금액 랜덤값**.
- 금액·수량에 **페이지를 열 때마다 새로 정해지는 같은 배수**를 곱해 보여 줍니다. 합계·차트 모양은 서로 맞고, 퍼센트·단가·날짜·건수는 그대로라 예시 화면처럼 자연스럽습니다.
- 화면 전체에 **'랜덤값' 워터마크**가 깔려 실제 숫자로 오해할 일이 없습니다. CSV 도 같은 배수로 나갑니다.
- **실제 금액은 저장소에 닿지 않습니다.** 배수는 어디에도 저장하지 않고(새로고침하면 바뀜), 원장·설정은 그대로이며,
  켜 있는 동안 금액·메모 입력 칸은 비우고 잠가 랜덤 숫자가 저장될 일이 없습니다. 이 기기의 브라우저 저장본도 쓰지 않습니다.
  AI 설명 글처럼 배수를 맞출 수 없는 글은 통째로 가립니다.
- 금액 가리기와 둘 중 하나만 켜집니다.

## 금액 가리기(숨김 모드)

- 화면 위 **눈 버튼** 또는 **Shift+H**(설정 › 표시에서도). 금액·수량·단가를 흐린 가짜 글자로 바꿉니다.
- 퍼센트·건수·날짜는 그대로 보이고, AI 설명 글은 숫자가 섞여 있어 통째로 가립니다.
- 숨김 중 CSV 를 내려받으면 '실제 금액이 그대로 담긴다'고 한 번 더 묻습니다.

## 기타 자산 — 증권사 연결은 미검증

코인 밖 자산(부동산·주식·금·자동차·현금·기타·부채)을 직접 적어 두면 대시보드 '전체 순자산'에 더해집니다. 주식·금은 공개 시세(약 15분 지연)로 평가합니다.

> **증권사 연결은 미검증입니다 — 공개 문서만 보고 작성했고, 실제 계정으로 시험하지 않았습니다.**
> 한국투자·키움·LS·DB·토스·Alpaca·IBKR·Schwab 어댑터가 있지만 모두 기본 꺼짐(`config.json` 의 `brokers.*.enabled: false`)입니다.
> 읽기 전용(보유·예수금 조회만, 주문 코드 없음)이며, 실제로 켜면 필드 이름·연속 조회·오류 코드가 문서와 달라 실패할 수 있습니다.
> 증권사별 필드·주의점은 [src/brokers/README.md](src/brokers/README.md) 에 있습니다.

## NFT 보유 · 바닥가

**기타 자산 › NFT** 에서 지갑의 NFT 와 컬렉션 바닥가를 봅니다. **표시 전용**이라 원장·손익·AI 리뷰에는 들어가지 않습니다.

- **자동 발견(하루 1회)** — EVM 은 블록스카웃(없으면 이더스캔 키), Solana 는 Helius. 등록한 지갑 + 활동이 확인된 체인만 봅니다.
  표준(ERC-721) 이전 NFT(**크립토펑크·원조 문캣**)도 자동으로 잡습니다. LP 포지션 NFT 는 LP 화면이 따로 추적하므로 개수만 보여 줍니다.
- **분류**
  - **추적 중(자동 포함)** — 바닥가와 최근 거래량이 확인된 컬렉션. 바닥가 × 개수로 평가하고 오늘 변동·7일 추이를 보여 줍니다(추적 대상은 1시간마다 갱신).
  - **후보** — 바닥가는 있는데 거래량이 없거나, 시세는 없지만 내가 사거나 민트한 것 등. 고르면 **추적**, 아니면 **숨김**.
  - **스팸 접힘** — 링크·보상 유도 이름, 유니코드 속임 글자, 대량 에어드랍, 남이 공짜로 보낸 시세 없는 NFT 등. 사유 칩이 붙고, 잘못 걸렸으면 펼쳐서 **'정상으로'**.
  - **지켜보기** — 갖고 있지 않아도 컬렉션 주소나 매직에덴·오픈시 링크를 넣어 바닥가만 지켜봅니다.
- **총자산에 포함** 스위치(기본 꺼짐) — 켜면 대시보드·기타 자산의 '전체 순자산'에 NFT 줄이 더해집니다(코인 총자산 숫자는 그대로).
- **바닥가 출처** — Solana = 매직에덴(1시간마다). EVM = `TJ_OPENSEA_KEY` 가 있으면 **오픈시 최우선**(작은 컬렉션까지), 없거나 실패하면 코인게코 NFT.
  코인게코는 키 없이도 되지만 공용 무료 한도라 처음엔 몇 시간 걸릴 수 있어요 — 그동안 화면 위 안내(하루 1회 텔레그램 안내 포함)가 뜨고,
  무료 **Demo 키**(`TJ_COINGECKO_KEY`)를 **설정 › 연결·키 › 탐색기 키** 에 넣으면 금방 채워집니다. 유료 **Pro 키**도 같은 칸에 넣으면 됩니다 —
  저장·연결 테스트 때 데모/프로를 자동으로 판별하고(프로는 주소가 `pro-api.coingecko.com` 으로 다름), 프로 키는 보통 다른 곳에서도 쓰는 키라
  코인게코가 알려 주는 플랜 한도(분당·월)의 **10%** 만 씁니다(같은 화면의 **사용 비율** 버튼으로 25·50·80% 까지 — 80% 가 상한). 한 달 몫은 남은 날에
  고르게 나누고, 같은 키를 쓰는 다른 곳의 이번 달 사용량이 많으면 그만큼 더 줄여 계정 전체가 80% 를 넘지 않게 합니다.
  등급·비율·지금 쓰는 몫은 같은 화면에 표시됩니다(키 값은 표시하지 않음).
  이 키는 NFT 만이 아니라 코인게코 시세·DEX 토큰 시세·원가·차트도 같이 씁니다(하루 몫을 기능별로 나눔 — [docs/API_KEYS.md](docs/API_KEYS.md)).
  오픈시 연결은 공개 문서 기준(키 없이 실호출 시험은 못 함).
- 무료 탐색기 API 가 NFT 목록을 주지 않는 체인은 제외되고, NFT 이미지는 외부 주소라 불러오지 않습니다(머리글자 표시). 호출은 무료 한도의 절반 이하로 천천히 합니다.

## Hyperliquid — 현물 · 무기한 · 스테이킹

- **설정 › 연결·키 › 퍼프 덱스** 에서 Hyperliquid 를 고르고 주소만 넣으면(키 없음 — 공개 조회 API) 무기한 포지션·실현 손익이 선물 화면에 나옵니다.
- `config.json` 에 `"hyperliquid": {"spot": true}` 를 넣고 `tj-exf`·`tj-web` 을 재시작하면 같은 주소의 **HyperCore 현물 체결·입출금**과
  **현물 + 무기한 현금 + 스테이킹 HYPE 잔고**를 거래소 'hyperliquid' 처럼 원장에 넣고 잔고 대사까지 합니다(빼고 싶은 주소는 `"spot_exclude": ["0x…"]`).

![연결·키 › 퍼프 덱스 — Hyperliquid 주소(주소는 가짜로 바꿈)](docs/screenshots/14_settings_keys_perp.png)

- 아비트럼 브릿지로 보낸 USDC 입금은 보낸 내역에서 Hyperliquid 입금과 자동으로 이어집니다. 시세는 같은 코인이 확인된 토큰만 아래 순서(바이낸스 → 바이빗 → 코인게코)를 쓰고,
  Hyperliquid 고유 토큰은 Hyperliquid 현물 중간가를 씁니다. 조회는 공개 한도의 3분의 1 이하로 천천히 합니다.

## 시세 출처 · 동명 코인 거르기

- **달러 시세 순서 = 바이낸스 → 바이빗 → 코인게코.** 원화 마켓이 없는 업비트·빗썸 보유 코인, 원가(매수 시점 1분봉), 장기 곡선·그날 마감가가 이 순서를 씁니다.
- **업비트·빗썸의 USDT·BTC 마켓 시세는 쓰지 않습니다**(거래가 얇아 튀는 일이 잦음). 원화 마켓 시세와 원화 환산용 업비트 KRW-USDT 는 그대로 씁니다.
- **동명 코인 거르기** — 같은 티커라도 다른 코인일 수 있어, 코인게코 매핑이 다른 코인이라고 하거나 기준가와 0.5~2배 넘게 어긋나면 그 거래소 시세를 버리고 사유를 남깁니다.
- 온체인 토큰은 그 체인의 DEX 실가(얇은 풀의 비정상 가격은 평가 제외)로 평가하고, 원가가 필요한데 거래소 1분봉이 같은 코인으로 확인되지 않으면 코인게코(컨트랙트 주소)를 씁니다.
- **코인게코 키**(`TJ_COINGECKO_KEY`, 선택)가 있으면 코인게코·GeckoTerminal 조회를 키로 먼저 부르고, 키 몫이 모자라거나 실패하면 그 콜만 예전처럼 무키로 부릅니다.
  순서는 그대로 — 거래소 값이 있는 코인은 코인게코를 부르지 않고, 그 코인의 확인용 조회(동명 거르기 기준가)는 키 몫을 아끼려고 무키로 둡니다.

## 일별 기록 — 그날 카드 · 'M월 한눈에'

- **그날 카드** — 그날 총자산 변동을 시세·실현·입출금·환율로 나누고, **시세(평가) 몫은 코인별 표**(전일 수량 × 가격 변화 — 전일 마감가 → 그날 마감가(오늘은 지금 시세) · 변동률 · 기여 금액)로 펼쳐 보여 줍니다.
  30분 체결 막대, 그날 실현 기여, 매매 근거 메모(코인별 한 줄)도 같은 카드에 있습니다.
- **'M월 한눈에'** — 달력 아래에 그 달 자산 변동 분해(시세·실현·LP 수수료·입출금·환율·나머지)와 실현 상위·하위 5를 한 장으로 보여 줍니다.

## 백필 · 재구축 · 재백필

- **백필**: 지갑을 추가하면 그 지갑의 과거(기본 5개월)를 자동으로 받습니다. 더 옛날이 필요하면 `config.json` 의 `backfill_since` 를 앞당기세요.
- **재구축(자동)**: 수집 시작일을 앞당긴 확장 백필이 끝나거나 수집 기간 밖의 옛 기록이 원장에 들어오면, `tj-core` 가 **별도 사본에서**
  분류·원가·손익을 다시 계산하고 검증을 통과한 경우에만 원장을 바꾼 뒤 스스로 다시 켭니다. 손으로 유닛을 멈출 일이 없습니다.
  실패하면 원장은 그대로 두고 6시간 → 12시간 → 24시간 뒤 다시 시도합니다. 진행은 **상태 패널**과 `pm2 logs tj-core` 에서 봅니다
  (끄려면 `config.json` 의 `"backfill": {"auto_rebuild": false}`).
- **재구축 점검(읽기만)**: `python3 tools/rebuild2.py --dry-run` 은 아무것도 쓰지 않고 원본 건수만 보여 줍니다.
  `python3 tools/rebuild2.py --shadow-dir /tmp/tj_shadow` 는 원장을 복사본에서 다시 계산해 지금 원장과 비교만 합니다(교체하지 않음 · 유닛을 멈출 필요 없음).
- `tools/rebuild.py` 는 옛 원장 형식용이라 지금 원장에서는 **실행을 거부합니다** — 쓰지 마세요.
- 설정 마법사가 '과거 보유분 재구축 필요'라고 표시한 지갑(기초 잔고 대조가 끝난 뒤 추가한 체인)을 확실히 맞추려면 아래 재백필을 하세요.
- 어떤 작업이든 유닛을 직접 멈췄다가 중간에 실패했다면 `pm2 start ecosystem.config.js` 로 다시 켜세요(멈춘 유닛이 모두 올라옵니다). `pm2 ls` 로 전부 online 인지 확인하세요.
- **재백필**(처음부터 다시): 지갑을 빼도 이미 기록된 거래는 원장에 남습니다. 깨끗이 다시 시작하려면
  `pm2 stop all` → `state/` 폴더 이름을 바꿔 보관(예: `state.old`) → `bash tools/setup.sh` → `pm2 start ecosystem.config.js`.

---

## 기능 요약

- **지갑 수집** — EVM(Ethereum·Base·Arbitrum·Optimism·Polygon·Scroll·zkSync·Gnosis) + BNB Chain + Solana.
  추가 EVM 체인(Monad·MegaETH·Plasma·X Layer·Kaia·Fraxtal·BOB·Story·Somnia·Avalanche·Stable·Abstract·Arc·Robinhood 등)은
  등록 주소에 활동이 확인되면 켤 수 있습니다(`chain_sweep` — 기본은 알림만, `auto_enable` 로 자동 추적).
- **거래소 연결(선택)** — 업비트·빗썸·바이낸스·바이빗·OKX·쿠코인·게이트. 입금·출금·체결·잔고(마진·Earn·선물 손익 포함)를 읽어
  "지갑 → 거래소 입금 → 매도" 흐름을 한 사이클로 묶고 원가를 이어 줍니다. 원화 입출금도 따로 보여 줍니다.
- **퍼프 덱스(선택)** — 주소만으로 공개 조회되는 곳(Hyperliquid·GMX 등)의 포지션·정산. **Hyperliquid** 는 현물·무기한 현금·스테이킹까지 원장·대사(선택).
- **NFT(표시 전용)** — 보유 자동 발견(크립토펑크 등 표준 이전 NFT 포함), 바닥가·거래량 확인된 컬렉션 자동 추적, 후보·스팸 거르기·지켜보기, 총자산 포함 스위치.
- **LP** — Uniswap v3/v4·PancakeSwap·SushiSwap·Aerodrome/Velodrome Slipstream·Meteora DLMM 등 포지션 원금·수수료 평가.
- **손익** — 사이클별 투입·실현·미실현, 차익 영수증(매수·매도 한 차트·점수), 월/일 실현손익 달력과 매매 근거 메모,
  전일 대비 분해(시세 몫은 코인별 표), 'M월 한눈에', 장기 총자산 곡선(1년·전체), 가스·수수료, 신고용 양도차익 명세(CSV).
- **내 매매 돌아보기** — 타임머신 · 자금 흐름 지도 · 팔기 전 미리보기 · 올해 결산 · 계획 지키기 점수 · 매매 습관 · 하루 실현 잔디 · BTC 비교선.
- **전체 검색** — ⌘K(또는 /)로 코인·주소·해시·날짜·금액·메모·리뷰를 한 번에(필터 문법 `coin:` `chain:` `type:` `after:` `pnl:` `amt:` …, 문장 검색).
- **상태 패널·알림** — 수집기·외부 API 지연, 온체인 잔고 상시 대조(불일치 알림), 원장 정기 백업 상태, 텔레그램 알림 3등급(즉시 · 하루 요약 · 시스템).
- **가격** — 토큰은 그 체인의 DEX 실가(얇은 풀의 비정상 가격은 평가 제외), 거래소 보유분은 그 거래소 원화 시세, 달러 시세는 바이낸스 → 바이빗 → 코인게코
  (업비트·빗썸 USDT·BTC 마켓은 쓰지 않음 · 동명 코인 거르기), 원화 환산은 업비트 KRW-USDT. 금액 랜덤값·가리기 모드로 화면 공유도 안전하게.
- **AI(선택, 기본 꺼짐)** — 일간·주간 리뷰(`TJ_ENABLE_REVIEW=1 pm2 start ecosystem.config.js` 로 `tj-review` 유닛 추가)와
  영수증 AI 매수·매도 평가(`config.json` 의 `review.*_eval_daily_max` 를 0 보다 크게). 둘 다 내 컴퓨터의 `claude` CLI 로 요약을 보냅니다.

## 구조

```
지갑 수집기(tj-evm·tj-sol·tj-bsc) ─┐
거래소 수집기(tj-ex·tj-exf) ───────┼─> state/inbox/ ─> tj-core ─> state/ledger.db (SQLite 원장)
                                   │                               │
텔레그램 알림(tj-alert) <────────── tj-web (화면·설정 API·가격·잔고 대조) <┘
```

| 유닛 | 하는 일 |
|---|---|
| `tj-evm` · `tj-sol` · `tj-bsc` | 지갑 수집기(EVM·Solana·BNB Chain) → `state/inbox/` |
| `tj-ex` · `tj-exf` | 업비트 / 해외 거래소(+퍼프 덱스) 수집 |
| `tj-core` | 원장 쓰기(유일한 쓰기 주체) — 분류·원가·손익 |
| `tj-web` | 화면·설정 API·가격·잔고 대조·기타 자산·알림 생산 (127.0.0.1:8023) |
| `tj-alert` | 텔레그램 발송 — 종류별 켜기·끄기·조용한 시간 적용 |
| `tj-review` | (선택) AI 일간·주간 리뷰 |

- 원본(raw) 기록은 보존되고, 분류·원가·손익은 원본에서 다시 계산할 수 있습니다(위 '재구축').
- 로그 자르기: `bash tools/rotate_logs.sh --dry-run` (크론 등록은 각자).
- 백업할 것: `state/`(특히 `state/ledger.db` — tj-core 가 정기 백업도 남김)·`.env`·`config.json`.

## 보안 · 데이터

- **조회만 합니다.** 개인 키·시드 문구를 요구하지 않고, 거래소·증권사 키로는 잔고·내역 조회 API 만 부릅니다(주문·출금 코드 없음).
- **웹은 127.0.0.1 바인딩이 기본**이고 비밀번호 로그인(기본 켜짐 — PBKDF2-SHA256 해시, HttpOnly·SameSite=Strict 세션 쿠키, 시도 제한)으로
  잠겨 있습니다. 모든 응답에 프레임 차단·nosniff 헤더가 붙고, 서버 오류 화면에 내부 경로·값을 싣지 않습니다. 모든 쓰기 요청(POST)은 같은 출처(Origin) + CSRF 토큰을 확인하고,
  키 입력 API 는 로컬/테일넷 접속(또는 로그인된 리버스 프록시 경유)만 받습니다. 모든 요청의 Host 를 검사합니다(DNS 리바인딩 방지).
  로그인이 꺼져 있으면 리버스 프록시·터널 헤더가 붙은 요청을 전부 거부합니다.
- 비밀값은 `.env`(600)에만 저장되고 화면에는 •••• 로만 보입니다(거래소 공개 API 키만 끝 4자리). `.env`·`config.json`·`state/` 는 `.gitignore` 에 들어 있습니다 — 절대 커밋하지 마세요.
- 밖으로 나가는 요청은 조회뿐입니다: 블록 탐색기·RPC(내 주소), 거래소 API, 가격(GeckoTerminal·DexScreener·거래소 공개 시세·주식/금 공개 시세),
  스캠 판정(GoPlus — 후보 토큰 주소만), 지갑 포트폴리오 보강(Rabby 공개 API — 내 EVM 주소, `rabby.enabled: false` 로 끔),
  브릿지 탐색기(도착 확인), 환율, 텔레그램 발송, NFT 바닥가(코인게코·매직에덴·오픈시 — 컬렉션 주소만), Hyperliquid 공개 조회(내 주소).
  원장 내용 자체는 보내지 않습니다.
  예외: AI 기능(기본 꺼짐)을 켜면 그날 요약·영수증 요약을 내 컴퓨터의 `claude` CLI 로 보냅니다.
- AI 리뷰·평가는 내 컴퓨터의 `claude` CLI 를 쓰며, 넘기는 환경변수는 허용 목록뿐입니다(PATH·HOME·로케일, 프록시 `HTTP(S)_PROXY`·`NO_PROXY`·`ALL_PROXY`,
  사내 인증서 `NODE_EXTRA_CA_CERTS`·`SSL_CERT_FILE`·`SSL_CERT_DIR`, Claude 로그인·게이트웨이·Bedrock·Vertex 변수). 거래소 키와 `.env` 값은 넘기지 않습니다.
  AI 매도·매수 평가는 기본 꺼짐 — `config.json` 의 `review.sell_eval_daily_max`·`review.buy_eval_daily_max` 를 1 이상(하루 최대 호출 수)으로 켭니다.
- 로그인 화면이 뜨면(로그아웃·만료·다른 기기에서 모두 로그아웃) 그 브라우저에 남은 화면 저장본(IndexedDB·버전 키)을 지웁니다.

## 알아 둘 것

- 시간대는 한국 시간(KST), 화면은 한국어입니다.
- 거래소·체인 API 가 주지 않는 옛 기록은 가져오지 않습니다 — [docs/COLLECTION_LIMITS.md](docs/COLLECTION_LIMITS.md)·화면 **설정 › 수집 한계**.
- 신고용 명세는 계산 보조 자료입니다. 세무 판단은 전문가와 확인하세요.

## 라이선스

라이선스 미정 — 정해지기 전까지는 저작권자 허락 없이 재배포·수정 배포를 할 수 없습니다.
이 소프트웨어는 있는 그대로 제공되며 손익·세금 계산의 정확성을 보증하지 않습니다.

---

## English

**tj-bot** is a self-hosted, **read-only** crypto trade journal. Give it wallet addresses (EVM chains, BNB Chain, Solana, plus
optional extra EVM chains) and, optionally, **read-only** API keys for Upbit, Bithumb, Binance, Bybit, OKX, KuCoin and Gate.
It merges on-chain swaps, transfers and LP positions with exchange deposits, withdrawals and fills into one local SQLite ledger and
shows cost basis, realized/unrealized PnL, a daily PnL calendar with per-day trade notes, trade "receipts" with buy/sell charts,
a long-range net-worth curve, an "other assets" tab (real estate, stocks, gold, cash, debt), a tax-report CSV, bridge/transfer
tracking and a review queue for unknown-cost inflows and spam tokens. The UI is Korean and times are KST.

- **Requirements:** macOS or Linux, Python 3.9+ (standard library only). Node.js + pm2 optional (recommended for auto-restart).
- **Start:** `bash tools/setup.sh` (creates `config.json`, `.env` (mode 600) and `state/`; installs nothing), then
  `pm2 start ecosystem.config.js` and open http://127.0.0.1:8023/ — a setup wizard handles wallets (paste many at once), keys and Telegram.
  `bash tools/setup.sh --demo` shows synthetic data without saving anything.
- **Keys:** a free Helius key is required only for Solana wallets; Etherscan, CoinGecko (demo or pro — detected automatically) and OpenSea keys are optional; exchange keys must be **read-only**
  with an IP whitelist (keys with trade/withdraw/transfer permissions are refused where the exchange lets us check).
- **First run:** the default backfill is the last 5 months; expect minutes to a few hours depending on wallets and trades.
  Progress is shown in the status panel and in Settings > collection limits.
- **New in this release:** Hyperliquid (HyperCore spot fills/transfers, perps cash and staked HYPE booked like an exchange and reconciled —
  opt in with `"hyperliquid": {"spot": true}`); NFT holdings with floor prices (auto-tracks collections with a floor and recent volume,
  candidate list, spam filtering with reasons, watch-only collections, an "include in total" switch that is off by default, CryptoPunks and
  other pre-ERC-721 NFTs detected automatically; display only, never in the ledger). EVM floors come from OpenSea first when the optional
  `TJ_OPENSEA_KEY` is set (covers smaller collections), otherwise CoinGecko; an optional CoinGecko key (`TJ_COINGECKO_KEY` — a free **demo**
  key or a paid **pro** key; the plan is detected automatically when you save or test it, pro keys use `pro-api.coingecko.com` and, since a pro
  key is usually shared with other tools, only 10% of the plan's per-minute and monthly limits by default — a "usage share" switch in the same
  row offers 10/25/50/80%, 80% being the hard cap; the monthly part is spread evenly over the rest of the month and shrinks further when other
  tools already used most of the month) fills floors much faster. The same key is also used for CoinGecko USD prices of coins no exchange
  priced, DEX token prices, historical prices for cost basis and charts, and DEX pool candles; when its share runs out or it fails, that call
  falls back to the old keyless request (see `docs/API_KEYS.md`). USD prices follow Binance → Bybit → CoinGecko, Upbit/Bithumb USDT and BTC markets are never used, and same-ticker
  different coins are filtered out. The daily card breaks the price move down per coin, and a "month at a glance" card sits under the calendar.
- **Telegram alerts:** three tiers — **now** (sound, even in quiet hours: bot stopped, target/stop hit, a large withdrawal you did not make,
  stablecoin depeg, near liquidation, optional big moves), a **daily digest** (one silent message at a set time) and **system** (never sent,
  status panel only). Presets (recommended/minimal/all), thresholds and quiet hours; the same problem is sent at most twice (raised and ✅ resolved).
- **Look back at your trading (new):** a time machine (drag the curve to see that day's holdings vs. "if you had held"), a money-flow map
  (deposits → exchanges → wallets → where it is now), a sell preview (expected realized PnL and this year's taxable gain), a year-end card set,
  a plan-keeping score, trading habits by weekday/hour and holding time, a one-year realized-PnL heatmap and BTC / "never sold" comparison lines.
- **Search (new):** ⌘K or / searches coins, addresses, tx hashes, dates, amounts, notes and reviews with a filter syntax
  (`coin:` `chain:` `type:` `after:` `before:` `pnl:` `amt:` …) and plain-sentence queries (rule-based by default; no external calls).
- **Broker adapters** in the other-assets tab are **UNVERIFIED** — written from public documentation only and never tested
  against a real account; all are disabled by default.
- **Privacy:** random-amount mode multiplies amounts by a per-page random factor (never stored) with a "랜덤값" (random) watermark;
  hide mode (Shift+H) blurs amounts. Both are display-only. All screenshots above were taken in random-amount mode with fake addresses
  and position numbers (NFT collection names and floors are also hidden in the NFT shots, and other-asset names are replaced with "<type> A").
- **Login (on by default):** on first run, open http://127.0.0.1:8023/ on the machine itself to create a password (10+ characters);
  every device then needs it. Sessions last 30 days (7 days idle). Passwords are stored as PBKDF2-SHA256 hashes; 5 wrong tries in
  10 minutes lock that IP for 15 minutes (doubling on repeat). Change it or log out everywhere in Settings › 로그인; forgot it →
  `python3 tools/reset_password.py` (or `--set`) on the machine. Disable only with `"web": {"login": {"enabled": false}}` + restart tj-web.
  **Upgrading:** login is now on even when `web.login` is missing from `config.json` — after updating, restart tj-web and create the
  password on the machine first (other devices get 401 until then).
- **Reverse proxy / tunnel:** put an HTTP-aware HTTPS proxy (e.g. a Cloudflare tunnel) in front of `http://127.0.0.1:8023`, keep the `Host`
  header, add `X-Forwarded-For` and `X-Forwarded-Proto: https`, and list the domain in `web.allowed_hosts` (`web.public_url` = optional
  `https://` link for Telegram alerts). nginx: `proxy_set_header Host $host; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;` — or set `"web": {"behind_proxy": true}` to treat every request as proxied (create the first
  password with `python3 tools/reset_password.py`). With login off, every request carrying proxy headers is refused (403). Proxied requests always need a
  session, can't create the first password or use the internal token, count toward the global login limit, and get `Secure` cookies, HSTS
  and `private, no-store` caching. Never use raw TCP forwarders (`ssh -R`, `socat`, `tailscale serve --tcp`, `ngrok tcp`) — they look like
  direct local access. `web.login.secure_cookie: true` forces the `Secure` flag; the login page warns on plain `http://` outside loopback/Tailscale.
  The internal token (`state/auth_internal_token`, regenerated on every tj-web start) is for same-machine units only — pass it as a header file,
  e.g. `curl -H @<(printf 'X-TJ-Internal: %s\n' "$(cat state/auth_internal_token)") http://127.0.0.1:8023/api/state`.
- **Security:** binds to 127.0.0.1 by default (optional Tailscale IP; public IPs and 0.0.0.0 are refused); password login is on
  by default, but still never expose the port directly to the internet; every POST needs a same-origin `Origin` header and a CSRF token; secrets stay in `.env`.
- **AI features** (daily/weekly review, receipt evaluation) are off by default and use your local `claude` CLI when enabled. Only an
  allow-list of environment variables is passed to it (PATH, HOME, locale, `HTTP(S)_PROXY`/`NO_PROXY`/`ALL_PROXY`, corporate CA variables
  `NODE_EXTRA_CA_CERTS`/`SSL_CERT_FILE`/`SSL_CERT_DIR`, and Claude login/gateway/Bedrock/Vertex variables) — never exchange keys or `.env` values.
  Receipt buy/sell evaluation is off by default; enable it by setting `review.sell_eval_daily_max` / `review.buy_eval_daily_max` to 1 or more
  (max calls per day). `review.coach_role` and `review.known_patterns` tailor the daily/weekly review to your style.
- **License:** not decided yet (all rights reserved until then). Provided as is; PnL and tax figures are an aid, not advice.
