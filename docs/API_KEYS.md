# API 키 받는 법

tj-bot 은 **무료 키와 공개 노드만으로** 돌아가게 짜여 있어요. 꼭 넣을 키는 둘 — Solana 지갑이 있으면 **Helius**, EVM 지갑이 있으면 **Etherscan**(둘 다 무료).
나머지 키는 더 빨리·더 넓게 받게 해 줄 뿐이고, 탐색기·시세 키는 공표 한도의 80% 를 기준으로 하루 몫을 정해 천천히 부릅니다.
키는 웹 **설정 › 연결·키** 에 붙여 넣으면 `.env`(권한 600)에 저장되고, 화면에는 •••• 로만 보입니다(거래소 공개 API 키만 끝 4자리).
키 값은 주소(URL)·로그·상태 파일·화면 응답 어디에도 남기지 않습니다 — 요청 헤더로만 보냅니다.
(노드 키만 예외 — NodeReal·Ankr·QuickNode 는 키가 노드 주소에 들어가는 방식이라 그 주소를 메모리에서만 만들어 부르고, `config.json`·상태 파일에는 쓰지 않습니다.)

| 키(`.env` 이름) | 꼭 필요? | 무료? | 어디에 쓰나 | 없으면 |
|---|---|---|---|---|
| `TJ_HELIUS_KEY` | Solana 지갑이 있으면 **필수** | 무료 플랜 | Solana 지갑 옛 기록·토큰·NFT 수집, 새 거래 확인의 백업 | Solana 지갑을 못 받아요 |
| `TJ_ETHERSCAN_KEY` | EVM 지갑이 있으면 **필수**(경고만 · 막지는 않음) | 무료 | Ethereum·Arbitrum·Polygon 거래를 빠르고 빠짐없이 · NFT 자동 발견(블록스카웃이 없는 체인) | 공개 탐색기·RPC 로 받아 느리거나 늦게 기록될 수 있어요 |
| `TJ_COINGECKO_KEY` | 선택 | Demo 무료 · Pro 유료 | 코인게코 시세 · DEX 토큰 시세 · 원가·차트 시세 · NFT 바닥가 | 전부 무키(공용 무료 한도)로 — 느리고 막히기 쉬워요 |
| `TJ_OPENSEA_KEY` | 선택 | 무료 신청 | EVM NFT 바닥가 최우선 출처 | 코인게코 NFT 로 |
| `TJ_NODEREAL_KEY` · `TJ_ANKR_KEY` · `TJ_QUICKNODE_BSC_KEY` · `TJ_QUICKNODE_BASE_KEY` | 선택 | NodeReal·Ankr 무료 키 · QuickNode 유료 | BNB Chain·Base 옛 기록(아카이브) 노드 — 무료 키는 월 한도의 80%, 유료는 사용 비율(기본 10%) 안에서만 | 공개 노드로 — BNB Chain 은 공개 노드 보관 기간까지만 |
| 거래소 키(업비트·빗썸·바이낸스·바이빗·OKX·쿠코인·게이트) | 선택 | 무료 | 그 거래소 잔고·체결·입출금 | 그 거래소는 안 받아요 |
| `TJ_TG_TOKEN` · `TJ_TG_CHAT` | 선택 | 무료 | 텔레그램 알림 | 알림 없이 화면만 |

---

## Helius — `TJ_HELIUS_KEY` (Solana)

1. https://dashboard.helius.dev 에 가입(무료 플랜).
2. **API Keys** 에서 키를 복사.
3. **설정 › 연결·키 › 탐색기 키 › Helius** 에 붙여 넣고 저장.

- 쓰는 곳: Solana 지갑의 거래·잔고·토큰, Solana NFT 자동 발견.
- **새 거래 확인은 무료 공개 노드(publicnode)가 먼저** 하고, 응답이 없거나 이상하면 같은 요청을 Helius 로 다시 보내요. 공개 노드는 최근 약 18시간만 보관해서,
  마지막 확인이 12시간보다 오래된 주소와 처음 넣은 지갑은 Helius 로 확인하고, Helius 가 주기적으로 공개 노드 결과를 대조합니다.
- **하루 몫** = 월 크레딧(무료 100만 · 유료면 `config.json` 의 `sol.helius_monthly_credits`)의 80% ÷ 30(무료 기준 약 2만 6천).
  새 거래 확인 몫을 먼저 떼어 두고(옛 기록을 채우는 동안은 하루 몫의 10% — `sol.helius_head_min_pct`) 나머지는 UTC 0시(한국 오전 9시)부터 옛 기록에 먼저 써요.
  그래서 처음 넣은 지갑은 첫날 새 거래 확인이 평소보다 늦을 수 있고, 오늘 옛 기록 몫을 다 쓴 뒤 넣은 지갑은 다음 오전 9시에 시작해요.
- 하루 몫을 다 쓰면 그날 끝까지 Helius 를 쉬고 공개 노드로 이어 받아요(옛 기록 = Solana 공식 공개 노드 · 공표 한도의 80% 안).
  공개 노드를 끄려면 `sol.head_rpc`·`sol.archive_rpc` 를 `""` 로(그러면 Helius 만 쓰고, 하루 몫이 다 차면 그날 끝까지 쉼).

## Etherscan — `TJ_ETHERSCAN_KEY` (EVM 지갑이 있으면 필수)

1. https://etherscan.io/myapikey 에 가입 → **Add** 로 키 만들기(무료).
2. **설정 › 연결·키 › 탐색기 키 › Etherscan** 에 저장.

- 쓰는 곳: Ethereum·Arbitrum·Polygon 거래를 빠르고 빠짐없이 받기(키 하나로 여러 체인), 블록스카웃이 없는 체인의 NFT 자동 발견. 무료 키는 Base 를 지원하지 않아요(Base 는 공개 RPC 로 받음).
- **필수지만 막지는 않아요** — EVM 지갑이 있는데 키가 없으면 설정 마법사·키 카드('EVM 필수')·상태 패널에 '이더스캔 키가 필요해요(무료)'가 떠요(텔레그램으로는 안 감).
  키가 없어도 공개 탐색기·RPC 로 계속 받지만 느리거나, 공개 탐색기가 막힌 체인(Arbitrum·Polygon 등)은 늦게 기록될 수 있어요(기록이 사라지지는 않아요).
- **하루 몫** = 공표 무료 한도(하루 10만 회)의 80%(8만 회) · 초당 요청은 공표 3회보다 낮은 2회. 새 거래 확인 몫(하루의 약 10~70% — 실제 사용량으로 정함)을
  먼저 떼어 두고, 나머지는 옛 기록 채우기가 UTC 0시(한국 오전 9시)부터 몰아서 써요 — 처음 넣은 지갑은 첫날 새 거래 확인이 늦을 수 있고,
  옛 기록이 다 채워지면 새 거래 확인이 하루 몫을 그대로 씁니다.
- 하루 몫을 다 쓰거나 키가 거부되면 그 체인은 블록스카웃(살아 있으면) 또는 공개 RPC 로 이어 받아요. 공개 RPC 로 갔다면 이더스캔이 살아날 때 알아서 돌아옵니다.

## CoinGecko — `TJ_COINGECKO_KEY` (데모 또는 프로 — 자동 판별)

**받는 법**

1. https://www.coingecko.com/en/developers/dashboard 에 가입.
2. 무료라면 **Demo** 키를 만들고(가입만 하면 됨), 유료 플랜이 있다면 그 **Pro** 키를 그대로 씁니다.
3. **설정 › 연결·키 › 탐색기 키 › CoinGecko** 에 저장 — 저장·연결 테스트 때 데모인지 프로인지 자동으로 알아냅니다
   (프로는 주소가 `pro-api.coingecko.com` 으로 달라요). 재시작은 필요 없어요.

**어디에 쓰나 — 키 하나를 아래 기능이 같이 씁니다**

| 기능 | 언제 코인게코를 부르나 |
|---|---|
| 지금 시세 | 거래소(바이낸스 → 바이빗)가 값을 못 준 코인만 — 예: 원화 마켓이 없는 업비트·빗썸 코인, Hyperliquid 코인 |
| DEX 토큰 시세 | 온체인 토큰의 DEX 실가(코인게코 온체인 = GeckoTerminal 데이터 · 풀 유동성을 같이 받아 얇은 풀의 튀는 값은 거름) |
| 지난 시세 | 원가(거래소 1분봉이 없는 토큰의 그때 시세), 차트·장기 곡선의 시세 점, DEX 풀 봉 |
| NFT 바닥가 | 오픈시 키가 없거나 실패한 EVM 컬렉션 |

- **시세 순서는 그대로 = 바이낸스 → 바이빗 → 코인게코.** 키를 넣어도 거래소 값이 있는 코인은 코인게코를 부르지 않아요.
- 거래소 값이 있는 코인의 **확인용 조회**(동명 코인 거르기 기준가 등)는 키 몫을 아끼려고 예전처럼 무키로 부릅니다.
- **부족하거나 실패하면 그 콜만 무키로** 다시 부릅니다(예전과 같은 공용 무료 한도). 키 쪽은 잠깐 쉽니다 —
  한도 초과(429)는 1분부터 두 배씩 최대 15분, 키 거절(401·403)은 6시간(설정에서 다시 저장·테스트하면 바로 풀림), 장애는 1분.
  키가 정답으로 '없음'(404)이라고 하면 무키로 다시 묻지 않아요.

**얼마나 쓰나**

- **데모(무료)**: 코인게코 공표 한도(분당 30회 · 월 1만 회)의 80% 아래 — 분당 24회 · 하루 260회.
- **프로(유료)**: 코인게코가 알려 주는 플랜 한도(분당·월)의 **10%** 만 씁니다(기본). 같은 화면의 **사용 비율** 버튼으로 25·50·80% 까지(80% 가 상한).
  한 달 몫은 남은 날에 고르게 나누고, 같은 키를 다른 곳에서도 많이 썼으면 그만큼 줄여 계정 전체가 80% 를 넘지 않게 합니다.
  플랜 한도는 6시간에 한 번 코인게코에 물어 갱신합니다(추적 NFT 가 없어도). 못 읽으면 데모 수준으로 아껴 씁니다.
- 하루 몫은 기능별로 나눕니다 — 지금 시세 50% · NFT 30% · 지난 시세 20% 는 그 기능 몫으로 남겨 두고, 쓰지 않는 기능 몫은 다른 기능이 빌려 씁니다.
  분당 몫의 1/4 은 지금 시세용으로 남기고, 지금 시세는 한 시간에 하루 몫의 1/24 까지만(하루 몫을 한꺼번에 쓰지 않게).
- 웹·수집기 등 여러 프로세스가 같은 예산 기록(`state/nft_budget.json`)을 함께 써서 합계가 한도를 넘지 않습니다.

**없으면**: 코인게코·GeckoTerminal 을 전부 무키(IP 공유 무료 한도)로 부릅니다. 돌아가긴 하지만 느리고, NFT 바닥가는 처음 몇 시간 걸릴 수 있어요.

## OpenSea — `TJ_OPENSEA_KEY` (NFT 바닥가)

1. https://docs.opensea.io/reference/api-keys 에서 무료로 신청.
2. **설정 › 연결·키 › 탐색기 키 › OpenSea** 에 저장.

- 쓰는 곳: EVM NFT 바닥가를 **오픈시에서 먼저** 받아 작은 컬렉션까지 추적합니다. 없거나 실패하면 코인게코 NFT.
- 오픈시 연결은 공개 문서 기준입니다(키 없이 실호출 시험은 못 함).

## 거래소 키

| 거래소 | `.env` 이름 | 어디서 받나 |
|---|---|---|
| 업비트 | `UPBIT_ACCESS` · `UPBIT_SECRET` | 업비트 › 마이페이지 › Open API 관리 |
| 빗썸 | `TJ_BITHUMB_KEY` · `TJ_BITHUMB_SECRET` | 빗썸 › 마이페이지 › API 관리 |
| 바이낸스 | `TJ_BINANCE_KEY` · `TJ_BINANCE_SECRET` | 바이낸스 › API Management |
| 바이빗 | `TJ_BYBIT_KEY` · `TJ_BYBIT_SECRET` | 바이빗 › API |
| OKX | `TJ_OKX_KEY` · `TJ_OKX_SECRET` · `TJ_OKX_PASSPHRASE` | OKX › API keys |
| 쿠코인 | `TJ_KUCOIN_KEY` · `TJ_KUCOIN_SECRET` · `TJ_KUCOIN_PASSPHRASE` | 쿠코인 › API Management |
| 게이트 | `TJ_GATE_KEY` · `TJ_GATE_SECRET` | 게이트 › API Keys |

> **반드시 '조회(읽기)' 권한만 켜고, IP 화이트리스트를 거세요.** 거래·출금·이체 권한은 절대 켜지 마세요.
> 바이낸스·바이빗·OKX 는 저장할 때 권한을 확인해 거래·출금·이체가 켜진 키를 거부하고,
> 권한을 API 로 확인할 수 없는 업비트·빗썸·쿠코인·게이트는 '조회 권한만 켰음' 확인을 눌러야 저장됩니다.

- 쓰는 곳: 그 거래소의 잔고·체결·입출금(무엇을 어디까지 받는지는 [COLLECTION_LIMITS.md](COLLECTION_LIMITS.md)).
- 바이낸스·바이빗·OKX 는 같은 조회 키로 선물 손익과 선물 영수증의 진입·청산 가격도 받습니다(추가 권한 필요 없음 · 바이낸스만 선물 체결 내역을 조금 더 부름 — 공표 한도 80% 안).
- 거래소 공개 시세(달러·원화 시세)는 키 없이 받습니다.

## 텔레그램 — `TJ_TG_TOKEN` · `TJ_TG_CHAT`

1. 텔레그램에서 @BotFather → `/newbot` 으로 봇을 만들고 토큰을 받습니다.
2. **설정 마법사 › 텔레그램** 에 토큰을 넣고 안내를 따르면 채팅 ID 는 마법사가 자동으로 채웁니다.
3. 알림 종류·조용한 시간은 **설정 › 알림 (텔레그램)** 에서 고릅니다.

---

## English

Two free keys are required: `TJ_HELIUS_KEY` when you track a Solana wallet and `TJ_ETHERSCAN_KEY` when you track an EVM wallet
(for Etherscan this is a warning only — collection still runs on public explorers/RPC without it, just slower or later). All other keys are optional.
Paste keys in **Settings › Connections & keys**; they are stored in `.env` (mode 600), shown masked, and sent only as request headers (never in URLs, logs or state files).
The one exception is the optional node keys (`TJ_NODEREAL_KEY`, `TJ_ANKR_KEY`, `TJ_QUICKNODE_BSC_KEY`, `TJ_QUICKNODE_BASE_KEY` — BNB Chain/Base archive
nodes): those providers put the key in the endpoint URL, which is built in memory only and never written to `config.json` or state files.

- **Helius** (`TJ_HELIUS_KEY`, free plan — https://dashboard.helius.dev): Solana history, tokens and NFT discovery, and backup for new-transaction
  checks (those go to the free publicnode first; Helius cross-checks it). Daily share = 80% of the monthly credits ÷ 30; old history gets it first
  from 00:00 UTC while 10% (`sol.helius_head_min_pct`) is kept for new transactions; once used up, public nodes carry on until the UTC day ends.
- **Etherscan** (`TJ_ETHERSCAN_KEY`, free — https://etherscan.io/myapikey): fast and complete Ethereum/Arbitrum/Polygon history (the free key does not
  cover Base, which is read from public RPC); NFT discovery where no Blockscout exists. Daily share = 80% of the published 100k/day, at most 2 requests/s;
  a share for new-transaction checks is kept and the rest goes to old history from 00:00 UTC. When the key is refused or the share runs out,
  that chain continues on Blockscout (if it is up) or public RPC; from public RPC it returns to Etherscan by itself once Etherscan recovers.
- **CoinGecko** (`TJ_COINGECKO_KEY`, free demo or paid pro — https://www.coingecko.com/en/developers/dashboard, plan auto-detected):
  one key shared by CoinGecko USD prices for coins no exchange priced (Binance → Bybit → CoinGecko order unchanged), DEX token prices
  (CoinGecko on-chain / GeckoTerminal data, pool liquidity included for the thin-pool guard), historical prices for cost basis and charts,
  DEX pool candles, and NFT floors. Cross-check lookups for coins an exchange already prices stay keyless. When the key's share runs out or
  the key fails (429 / 401 / 403 / outage), that single call falls back to the old keyless request and the key rests for a while.
  Demo = 24/min, 260/day (below 80% of the published 30/min, 10k/month). Pro = 10% of the plan limits by default (25/50/80% selectable,
  80% hard cap), plan limits refreshed every 6 hours. The daily share is split live prices 50% / NFT 30% / historical 20% (idle shares are
  borrowed), and all processes share one budget file.
- **OpenSea** (`TJ_OPENSEA_KEY`, free application — https://docs.opensea.io/reference/api-keys): first source for EVM NFT floors.
- **Exchanges**: read-only keys with an IP whitelist only; keys with trade/withdraw/transfer permissions are refused where the exchange lets us check.
  Binance, Bybit and OKX keys also feed futures PnL and the futures-receipt entry/exit prices (no extra permission).
- **Telegram** (`TJ_TG_TOKEN`, `TJ_TG_CHAT`): create a bot with @BotFather; the setup wizard fills the chat id.
